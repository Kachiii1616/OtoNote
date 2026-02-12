from dotenv import load_dotenv
load_dotenv()

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

print("✅ transcribe_worker booted", flush=True)
print("DATABASE_URL set?", bool(os.environ.get("DATABASE_URL")), flush=True)
print("HF_TOKEN set?", bool(os.environ.get("HF_TOKEN")), flush=True)


def run(cmd: list[str]) -> None:
    """失敗時にstdout/stderr込みで例外化（Renderの原因特定ができる）"""
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            "Command failed\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{p.stdout}\n"
            f"stderr:\n{p.stderr}\n"
        )


def ensure_wav_16k_mono(input_audio: Path, out_wav: Path):
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


def get_audio_duration_sec(path: Path) -> float:
    """ffprobeで音声長を取得（diarize=False の一括起こし用）"""
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True
    )
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr}")
    return float(p.stdout.strip() or 0.0)


def diarize_with_pyannote(input_audio: Path, work_dir: Path):
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
    """短すぎる断片を同一speakerで結合（速度・精度改善）"""
    if not segments:
        return []

    merged = [segments[0].copy()]
    for s in segments[1:]:
        last = merged[-1]
        if s["speaker"] == last["speaker"] and (s["start"] - last["end"]) <= gap:
            last["end"] = max(last["end"], s["end"])
        else:
            merged.append(s.copy())

    # min_dur 未満を前後に吸収（簡易版）
    fixed = []
    for s in merged:
        if fixed and (s["end"] - s["start"]) < min_dur:
            fixed[-1]["end"] = s["end"]
        else:
            fixed.append(s)
    return fixed


class Command(BaseCommand):
    help = "Process queued transcription jobs (offline whisper + diarization)."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=1.0)

    def handle(self, *args, **opts):
        sleep = opts["sleep"]
        self.stdout.write(self.style.SUCCESS("Transcribe worker started. Ctrl+C to stop."))

        model_cache = {}

        while True:
            job = (TranscriptionJob.objects
                   .filter(status="queued")
                   .order_by("created_at")
                   .first())

            if not job:
                time.sleep(sleep)
                continue

            with transaction.atomic():
                job = TranscriptionJob.objects.select_for_update().get(id=job.id)
                if job.status != "queued":
                    continue
                job.status = "running"
                job.started_at = timezone.now()
                job.progress = 0
                job.error_message = ""
                job.save()

            input_path = Path(job.input_file.path)
            work_dir = input_path.parent / f"job_{job.id}_temp"
            work_dir.mkdir(parents=True, exist_ok=True)

            try:
                # Whisperモデルロード（キャッシュ）
                if job.model_name not in model_cache:
                    model_cache[job.model_name] = whisper.load_model(job.model_name)
                model = model_cache[job.model_name]

                wav_16k = work_dir / "audio_16k.wav"
                ensure_wav_16k_mono(input_path, wav_16k)

                # ✅ 改善策①：diarize=Falseなら一括文字起こし
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

                # diarize=True の場合
                segments = diarize_with_pyannote(input_path, work_dir)
                segments = merge_segments(segments, min_dur=1.2, gap=0.4)

                results = []
                total = len(segments) or 1

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

            finally:
                # ✅ Render節約：作業ディレクトリ掃除
                if work_dir.exists():
                    shutil.rmtree(work_dir, ignore_errors=True)
