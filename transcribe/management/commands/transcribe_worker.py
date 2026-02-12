"""
transcribe_worker.py（Django management command）

目的
----
DBに「queued」で溜まっている TranscriptionJob を順番に処理して、
Whisper（音声→文字起こし）＋ pyannote（話者分離）で output_text を作成する。

このファイルは Render の Background Worker 等で
  python manage.py transcribe_worker
として常駐実行される想定。

全体の流れ
----------
1) DBから status="queued" のジョブを1件取得
2) transaction + select_for_update でロックして status="running" に更新
3) 作業用ディレクトリ（job_{id}_temp）を作る
4) ffmpegで入力音声を 16kHz/mono WAV に統一（処理の安定化）
5) job.diarize が False なら、Whisperで一括文字起こしして終了
6) job.diarize が True なら、pyannoteで話者分離→セグメントごとにWhisperで文字起こし
7) output_text / status / progress / finished_at を保存
8) 成否に関わらず作業用ディレクトリを削除してディスク節約

この実装のポイント
------------------
- run(): subprocess失敗時に stdout/stderr を含めて例外化する
  → Render環境で ffmpeg が無い / codec不足 / 入力壊れ 等の原因特定が容易になる
- model_cache: Whisperモデルをジョブごとに毎回ロードすると激遅なのでメモ化する
- merge_segments(): pyannoteの細切れセグメントを結合して、速度と精度を改善する
- finally: 一時ファイルを削除（Renderのディスク節約、ゴミ蓄積防止）

注意（Render環境）
-----------------
- Renderの一部環境では apt-get が使えないことがある
  → ffmpegがOSレベルで入れられない場合は、別手段（同梱ffmpeg等）を検討する
- Webサービス側でアップロードした media/input のファイルを Worker が参照するには、
  WebとWorkerで同じ永続ディスク or 同じストレージ（S3/R2等）を共有する必要がある

"""

from dotenv import load_dotenv
load_dotenv()  # .env を読み込む（ローカル用。Renderでは環境変数設定が基本）

import os
import time
import subprocess
import shutil
from pathlib import Path

from pyannote.audio import Pipeline
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
import whisper

from transcribe.models import TranscriptionJob

# --- 起動時ログ（Renderログで「Workerが動いているか」確認用） ---
print("✅ transcribe_worker booted", flush=True)
print("DATABASE_URL set?", bool(os.environ.get("DATABASE_URL")), flush=True)
print("HF_TOKEN set?", bool(os.environ.get("HF_TOKEN")), flush=True)


def run(cmd: list[str]) -> None:
    """
    外部コマンド（ffmpeg等）を実行するヘルパー。

    重要:
    - subprocess.run(check=True) だと、Renderで失敗したとき stderr が見えず原因が不明になりがち。
    - ここでは capture_output=True で stdout/stderr を取得し、
      失敗時にエラー内容を丸ごと例外に含める。

    これにより job.error_message に「本当の原因」が残りやすくなる。
    """
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            "Command failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{p.stdout}\n"
            f"stderr:\n{p.stderr}\n"
        )


def ensure_wav_16k_mono(input_audio: Path, out_wav: Path):
    """
    入力音声（mp3/m4a/wav等）を、Whisper/pyannote処理しやすい形式に統一する。

    - 16kHz
    - mono（1ch）
    - wav

    ここで落ちる場合の典型原因:
    - Render環境に ffmpeg が無い
    - 対応コーデックが無い / 入力ファイルが壊れている
    - Workerがファイルにアクセスできていない（WebとWorkerでmedia共有ができていない）
    """
    run([
        "ffmpeg", "-y",
        "-hide_banner",
        "-loglevel", "error",   # 余計なログを減らし、エラーだけ出す
        "-i", str(input_audio),
        "-vn",                  # 映像がある場合は無視
        "-ac", "1",             # mono
        "-ar", "16000",         # 16kHz
        str(out_wav),
    ])
    return out_wav


def get_audio_duration_sec(path: Path) -> float:
    """
    ffprobeで音声の長さを取得する関数（現状は未使用）。

    将来:
    - 長尺音声を segment_sec で分割して安定処理したい場合
    - タイムライン表示などをしたい場合
    に使える。

    ※Renderで ffprobe が無い場合はここで落ちるので、使うなら環境整備が必要。
    """
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    )
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr}")
    return float(p.stdout.strip() or 0.0)


def diarize_with_pyannote(input_audio: Path, work_dir: Path):
    """
    pyannoteで話者分離（Speaker Diarization）を行い、セグメント一覧を返す。

    prerequisites:
    - HF_TOKEN（Hugging Faceのアクセストークン）が必要
    - 初回はモデルダウンロード/ロードがあるため重い

    戻り値:
    [
      {"speaker": "SPEAKER_00", "start": 0.0, "end": 3.2},
      {"speaker": "SPEAKER_01", "start": 3.2, "end": 5.1},
      ...
    ]
    """
    hf = os.environ.get("HF_TOKEN", "").strip()
    if not hf:
        raise RuntimeError("HF_TOKEN is missing. Set HF_TOKEN in environment variables.")

    work_dir.mkdir(parents=True, exist_ok=True)

    # diarizationはwav推奨なので、先に統一wavを作る
    wav_path = work_dir / "audio_16k.wav"
    ensure_wav_16k_mono(input_audio, wav_path)

    # pyannote/speaker-diarization-3.1 をロード
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=hf,
    )

    # 話者数の推定範囲（必要ならUIで設定できるようにしても良い）
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
    pyannoteのセグメントは細切れになりがちで、
    - Whisper呼び出し回数が増える（遅くなる）
    - 文字起こしが断片化する（精度が下がる）
    ことがあるため、連続セグメントを結合する簡易ロジック。

    仕様（簡易版）:
    - 同じ speaker が連続
    - かつ前のendと次のstartの間が gap 以下
    → 1つのセグメントに結合

    また、min_dur未満の短すぎるセグメントは前のセグメントに吸収する。
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


class Command(BaseCommand):
    """
    Djangoのカスタム管理コマンド
      python manage.py transcribe_worker
    で起動される。

    --sleep で「キューが空のとき何秒待つか」を調整可能。
    """
    help = "Process queued transcription jobs (offline whisper + diarization)."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=1.0)

    def handle(self, *args, **opts):
        sleep = opts["sleep"]
        self.stdout.write(self.style.SUCCESS("Transcribe worker started. Ctrl+C to stop."))

        # Whisperモデルのロードは重いのでキャッシュする
        model_cache = {}

        while True:
            # 1) queuedのジョブを古い順に1件取る
            job = (TranscriptionJob.objects
                   .filter(status="queued")
                   .order_by("created_at")
                   .first())

            if not job:
                time.sleep(sleep)
                continue

            # 2) ロックして running に変更（二重処理防止）
            with transaction.atomic():
                job = TranscriptionJob.objects.select_for_update().get(id=job.id)
                if job.status != "queued":
                    continue
                job.status = "running"
                job.started_at = timezone.now()
                job.progress = 0
                job.error_message = ""
                job.save()

            # 3) 作業用ディレクトリ（ジョブごと）
            #    成否に関わらず finally で削除する
            input_path = Path(job.input_file.path)
            work_dir = input_path.parent / f"job_{job.id}_temp"
            work_dir.mkdir(parents=True, exist_ok=True)

            try:
                # 4) Whisperモデルをキャッシュから取得（無ければロード）
                if job.model_name not in model_cache:
                    model_cache[job.model_name] = whisper.load_model(job.model_name)
                model = model_cache[job.model_name]

                # 5) 入力を統一wavに変換（ここでffmpegが必要）
                wav_16k = work_dir / "audio_16k.wav"
                ensure_wav_16k_mono(input_path, wav_16k)

                # 6) diarize=False の場合は全体を一括文字起こしして終了
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

                # 7) diarize=True の場合：話者分離 → セグメント結合
                segments = diarize_with_pyannote(input_path, work_dir)
                segments = merge_segments(segments, min_dur=1.2, gap=0.4)

                results = []
                total = len(segments) or 1

                # 8) セグメントごとにwavを切り出し → Whisperで文字起こし
                for idx, seg in enumerate(segments, start=1):
                    speaker = seg["speaker"]
                    start = seg["start"]
                    duration = seg["end"] - start
                    if duration < 0.1:
                        continue

                    # セグメント音声を切り出す
                    chunk_path = work_dir / f"seg_{idx:03d}.wav"
                    run([
                        "ffmpeg", "-y",
                        "-hide_banner", "-loglevel", "error",
                        "-ss", str(start), "-t", str(duration),
                        "-i", str(wav_16k),
                        "-ac", "1", "-ar", "16000",
                        str(chunk_path)
                    ])

                    # Whisper設定
                    kwargs = {"fp16": False}
                    if job.language and job.language != "auto":
                        kwargs["language"] = job.language

                    # 文字起こし
                    res = model.transcribe(str(chunk_path), **kwargs)
                    text = (res.get("text") or "").strip()
                    if text:
                        results.append(f"[{speaker}]: {text}")

                    # 進捗更新（UIの進捗バー用）
                    job.progress = int(idx * 100 / total)
                    job.save(update_fields=["progress"])

                # 9) 完了保存
                job.output_text = "\n".join(results)
                job.status = "done"
                job.progress = 100
                job.finished_at = timezone.now()
                job.save()
                self.stdout.write(self.style.SUCCESS(f"Job {job.id} finished successfully."))

            except Exception as e:
                # 10) 失敗保存（原因はerror_messageへ）
                job.status = "error"
                job.error_message = f"{type(e).__name__}: {e}"
                job.finished_at = timezone.now()
                job.save()
                self.stdout.write(self.style.ERROR(f"Job {job.id} failed: {e}"))

            finally:
                # 11) Render節約：作業ディレクトリ掃除
                #     永続ディスクが小さい/無い場合でもゴミが溜まらないようにする
                if work_dir.exists():
                    shutil.rmtree(work_dir, ignore_errors=True)
