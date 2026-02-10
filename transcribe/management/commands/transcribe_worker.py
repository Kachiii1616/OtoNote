from dotenv import load_dotenv
load_dotenv()
import os
from pyannote.audio import Pipeline
import time
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

import whisper

from transcribe.models import TranscriptionJob

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

# 機械的な分割関数（今回は使いませんが、残しておいても問題ありません）python3 -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.environ.get('HF_TOKEN'))"

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

                # 1. 話者分離を実行
                segments = diarize_with_pyannote(input_path, work_dir)
                wav_16k = work_dir / "audio_16k.wav"

                speakers = sorted({s["speaker"] for s in segments})
                print(f"=== DIARIZATION SUMMARY (Job {job.id}) ===")
                print("speakers:", speakers)
                print("segments:", len(segments))
                print("===========================")

                # 2. Whisperモデルの準備
                if job.model_name not in model_cache:
                    model_cache[job.model_name] = whisper.load_model(job.model_name)
                model = model_cache[job.model_name]

                results = []
                total = len(segments)

                # 3. 話者ごとのセグメントを1つずつ文字起こし
                for idx, seg in enumerate(segments, start=1):
                    speaker = seg["speaker"]
                    start = seg["start"]
                    duration = seg["end"] - start

                    if duration < 0.1: # 短すぎるものは無視
                        continue

                    # その話者の区間だけを切り出し
                    chunk_path = work_dir / f"seg_{idx:03d}.wav"
                    subprocess.run([
                        "ffmpeg", "-y", "-ss", str(start), "-t", str(duration),
                        "-i", str(wav_16k), "-ac", "1", "-ar", "16000", str(chunk_path)
                    ], capture_output=True)

                    # 文字起こし実行
                    kwargs = {"fp16": False}
                    if job.language and job.language != "auto":
                        kwargs["language"] = job.language

                    res = model.transcribe(str(chunk_path), **kwargs)
                    text = res.get("text", "").strip()

                    if text:
                        # 形式: [SPEAKER_00]: こんにちは
                        results.append(f"[{speaker}]: {text}")

                    # 進捗更新
                    job.progress = int(idx * 100 / total)
                    job.save(update_fields=["progress"])

                # 4. 結果の保存
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