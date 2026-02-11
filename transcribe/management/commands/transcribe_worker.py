from dotenv import load_dotenv
load_dotenv()

import os
import time
import subprocess
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
    subprocess.run(cmd, check=True)


def ensure_wav_16k_mono(input_audio: Path, out_wav: Path):
    subprocess.run([
        "ffmpeg", "-y",
        "-i", str(input_audio),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        str(out_wav),
    ], check=True)
    return out_wav


def diarize_with_pyannote(input_audio: Path, work_dir: Path):
    hf = os.environ.get("HF_TOKEN", "").strip()
    if not hf:
        raise RuntimeError("HF_TOKEN is missing. export HF_TOKEN='...'")

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


def split_audio(input_path: Path, out_dir: Path, segment_sec: int) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / "chunk_%03d.wav")
    run([
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "segment",
        "-segment_time", str(segment_sec),
        pattern
    ])
    return sorted(out_dir.glob("chunk_*.wav"))


class Command(BaseCommand):
    help = "Process queued transcription jobs (offline whisper + diarization)."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=1.0)

    def handle(self, *args, **opts):
        sleep = opts["sleep"]
        self.stdout.write(self.style.SUCCESS("Transcribe worker started. Ctrl+C to stop."))

        print("🔎 worker runtime check", flush=True)
        print("queued count:", TranscriptionJob.objects.filter(status="queued").count(), flush=True)

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

            try:
                input_path = Path(job.input_file.path)
                work_dir = input_path.parent / f"job_{job.id}_chunks"
                work_dir.mkdir(parents=True, exist_ok=True)

                segments = diarize_with_pyannote(input_path, work_dir)
                wav_16k = work_dir / "audio_16k.wav"

                speakers = sorted({s["speaker"] for s in segments})
                print(f"=== DIARIZATION SUMMARY (Job {job.id}) ===", flush=True)
                print("speakers:", speakers, flush=True)
                print("segments:", len(segments), flush=True)
                print("===========================", flush=True)

                if job.model_name not in model_cache:
                    model_cache[job.model_name] = whisper.load_model(job.model_name)
                model = model_cache[job.model_name]

                results = []
                total = len(segments)

                for idx, seg in enumerate(segments, start=1):
                    speaker = seg["speaker"]
                    start = seg["start"]
                    duration = seg["end"] - start

                    if duration < 0.1:
                        continue

                    chunk_path = work_dir / f"seg_{idx:03d}.wav"
                    subprocess.run([
                        "ffmpeg", "-y", "-ss", str(start), "-t", str(duration),
                        "-i", str(wav_16k), "-ac", "1", "-ar", "16000", str(chunk_path)
                    ], capture_output=True)

                    kwargs = {"fp16": False}
                    if job.language and job.language != "auto":
                        kwargs["language"] = job.language

                    res = model.transcribe(str(chunk_path), **kwargs)
                    text = res.get("text", "").strip()

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
