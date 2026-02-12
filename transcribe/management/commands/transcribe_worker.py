"""
transcribe_worker.py（Django management command）

目的
----
DBに「queued」で溜まっている TranscriptionJob を順番に処理して、
Whisper（音声→文字起こし）＋ pyannote（話者分離）で output_text を作成する。

このファイルは Render の Background Worker 等で
  python manage.py transcribe_worker
として常駐実行される想定。

重要（Render環境）
-----------------
Webサービス側でアップロードした media/input のファイルを Worker が参照するには
WebとWorkerで同じ永続ディスクを共有する必要があります。

そこでこのWorkerは、可能なら S3互換ストレージ（Cloudflare R2）から入力音声を取得し、
一時領域（/tmp相当）に落として処理します。これにより Web/Worker のディスク共有問題を回避します。

運用方針
--------
- job.r2_key がある場合：R2から一時ファイルへダウンロードして処理
- job.r2_key が無い場合：従来通り job.input_file.path を参照（移行用フォールバック）
"""

from dotenv import load_dotenv
load_dotenv()  # ローカル用。Renderでは環境変数が基本

import os
import time
import subprocess
import shutil
import tempfile
from pathlib import Path

from pyannote.audio import Pipeline
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
import whisper

from transcribe.models import TranscriptionJob

# R2（S3互換）: download_file(job.r2_key, local_path) を想定
# ない場合は、transcribe/r2.py を作成して boto3 で実装してください
try:
    from transcribe.r2 import download_file
except Exception:
    download_file = None  # フォールバックでローカル参照は可能にしておく


# --- 起動時ログ（Renderログで「Workerが動いているか」確認用） ---
print("✅ transcribe_worker booted", flush=True)
print("DATABASE_URL set?", bool(os.environ.get("DATABASE_URL")), flush=True)
print("HF_TOKEN set?", bool(os.environ.get("HF_TOKEN")), flush=True)

def _env_bool(name: str) -> bool:
    v = os.getenv(name)
    return bool(v and v.strip())

print("R2_ACCESS_KEY_ID set?", _env_bool("R2_ACCESS_KEY_ID"), flush=True)
print("R2_SECRET_ACCESS_KEY set?", _env_bool("R2_SECRET_ACCESS_KEY"), flush=True)
print("R2_ENDPOINT_URL set?", _env_bool("R2_ENDPOINT_URL"), flush=True)
print("R2_BUCKET_NAME set?", _env_bool("R2_BUCKET_NAME"), flush=True)


def run(cmd: list[str]) -> None:
    """
    外部コマンド（ffmpeg等）を実行するヘルパー。
    失敗時に stdout/stderr を含めて例外化する。
    """
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            "Command failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{p.stdout}\n"
            f"stderr:\n{p.stderr}\n"
        )


def ensure_wav_16k_mono(input_audio: Path, out_wav: Path) -> Path:
    """
    入力音声（mp3/m4a/wav等）を 16kHz/mono WAV に統一する。
    """
    run([
        "ffmpeg", "-y",
        "-hide_banner",
        "-loglevel", "error",
        "-i", str(input_audio),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        str(out_wav),
    ])
    return out_wav


def diarize_with_pyannote(input_audio: Path, work_dir: Path):
    """
    pyannoteで話者分離（Speaker Diarization）を行い、セグメント一覧を返す。
    """
    hf = os.environ.get("HF_TOKEN", "").strip()
    if not hf:
        raise RuntimeError("HF_TOKEN is missing. Set HF_TOKEN in environment variables.")

    work_dir.mkdir(parents=True, exist_ok=True)

    wav_path = work_dir / "audio_16k.wav"
    ensure_wav_16k_mono(input_audio, wav_path)

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf,
    )

    diarization = pipeline(str(wav_path), min_speakers=2, max_speakers=4)

    segments = []
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        segments.append({
            "speaker": speaker,
            "start": float(turn.start),
            "end": float(turn.end),
        })

    segments.sort(key=lambda x: x["start"])
    return segments


def merge_segments(segments, min_dur=1.2, gap=0.4):
    """
    pyannoteのセグメントを結合して、速度と精度を改善する。
    """
    if not segments:
        return []

    merged = [segments[0].copy()]
    for s in segments[1:]:
        last = merged[-1]
        if s["speaker"] == last["speaker"] and (s["start"] - last["end"]) <= gap:
            last["end"] = max(last["end"], s["end"])
        else:
            merged.append(s.copy())

    fixed = []
    for s in merged:
        if fixed and (s["end"] - s["start"]) < min_dur:
            fixed[-1]["end"] = s["end"]
        else:
            fixed.append(s)
    return fixed


def resolve_input_audio_to_local_path(job: TranscriptionJob, base_dir: Path) -> Path:
    """
    ジョブの入力音声を「ローカルパス」として用意する。

    優先順位:
    1) job.r2_key があって download_file が使える → R2から base_dir/input_audio に落とす
    2) job.input_file.path が存在 → それを使う（フォールバック）
    """
    r2_key = getattr(job, "r2_key", "") or ""
    r2_key = r2_key.strip()

    if r2_key:
        if download_file is None:
            raise RuntimeError("job.r2_key is set but transcribe.r2.download_file() is not available.")
        local_in = base_dir / "input_audio"
        download_file(r2_key, str(local_in))
        if not local_in.exists() or local_in.stat().st_size == 0:
            raise RuntimeError("Downloaded input_audio is missing or empty.")
        return local_in

    # フォールバック（移行用）
    if hasattr(job, "input_file") and getattr(job.input_file, "path", None):
        p = Path(job.input_file.path)
        if p.exists():
            return p

    raise RuntimeError("No input source: job.r2_key is empty and job.input_file is unavailable.")


class Command(BaseCommand):
    help = "Process queued transcription jobs (offline whisper + diarization)."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=1.0)

    def handle(self, *args, **opts):
        sleep = opts["sleep"]
        self.stdout.write(self.style.SUCCESS("Transcribe worker started. Ctrl+C to stop."))

        # Whisperモデルのロードは重いのでキャッシュする
        model_cache = {}

        while True:
            job = (TranscriptionJob.objects
                   .filter(status="queued")
                   .order_by("created_at")
                   .first())

            if not job:
                time.sleep(sleep)
                continue

            # 二重処理防止
            with transaction.atomic():
                job = TranscriptionJob.objects.select_for_update().get(id=job.id)
                if job.status != "queued":
                    continue
                job.status = "running"
                job.started_at = timezone.now()
                job.progress = 0
                job.error_message = ""
                job.save()

            try:
                # ジョブごとの一時領域（/tmp）
                with tempfile.TemporaryDirectory() as td:
                    td_path = Path(td)
                    work_dir = td_path / f"job_{job.id}_temp"
                    work_dir.mkdir(parents=True, exist_ok=True)

                    # 入力音声をローカルパスとして用意（R2優先）
                    input_path = resolve_input_audio_to_local_path(job, td_path)

                    # Whisperモデルをキャッシュから取得（無ければロード）
                    if job.model_name not in model_cache:
                        model_cache[job.model_name] = whisper.load_model(job.model_name)
                    model = model_cache[job.model_name]

                    # 入力を統一wavに変換
                    wav_16k = work_dir / "audio_16k.wav"
                    ensure_wav_16k_mono(input_path, wav_16k)

                    # diarize=False：一括文字起こし
                    if not job.diarize:
                        kwargs = {"fp16": False}
                        if job.language and job.language != "auto":
                            kwargs["language"] = job.language

                        res = model.transcribe(str(wav_16k), **kwargs)
                        job.output_text = (res.get("text") or "").strip()
                        job.status = "done"
                        job.progress = 100
                        job.finished_at = timezone.now()
                        job.save()
                        self.stdout.write(self.style.SUCCESS(f"Job {job.id} finished (no diarize)."))
                        continue

                    # diarize=True：話者分離→セグメント結合
                    segments = diarize_with_pyannote(input_path, work_dir)
                    segments = merge_segments(segments, min_dur=1.2, gap=0.4)

                    results = []
                    total = len(segments) or 1

                    # セグメントごとに切り出し→Whisper
                    for idx, seg in enumerate(segments, start=1):
                        speaker = seg["speaker"]
                        start = seg["start"]
                        duration = seg["end"] - start
                        if duration < 0.1:
                            continue

                        chunk_path = work_dir / f"seg_{idx:03d}.wav"
                        run([
                            "ffmpeg", "-y",
                            "-hide_banner", "-loglevel", "error",
                            "-ss", str(start), "-t", str(duration),
                            "-i", str(wav_16k),
                            "-ac", "1", "-ar", "16000",
                            str(chunk_path)
                        ])

                        kwargs = {"fp16": False}
                        if job.language and job.language != "auto":
                            kwargs["language"] = job.language

                        res = model.transcribe(str(chunk_path), **kwargs)
                        text = (res.get("text") or "").strip()
                        if text:
                            results.append(f"[{speaker}]: {text}")

                        job.progress = int(idx * 100 / total)
                        job.save(update_fields=["progress"])

                    job.output_text = "\n".join(results)
                    job.status = "done"
                    job.progress = 100
                    job.finished_at = timezone.now()
                    job.save()
                    self.stdout.write(self.style.SUCCESS(f"Job {job.id} finished successfully."))

            except Exception as e:
                job.status = "error"
                job.error_message = f"{type(e).__name__}: {e}"
                job.finished_at = timezone.now()
                job.save()
                self.stdout.write(self.style.ERROR(f"Job {job.id} failed: {e}"))
