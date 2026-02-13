import modal
import os

# 1. 実行環境の定義
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg")
    .pip_install(
        "openai-whisper",
        "pyannote.audio",
        "torch",
        "torchaudio",
        "librosa",
        "transformers",
        "accelerate",
        "boto3",
        "numpy<2.1.0" # NumPyの互換性を保つ
    )
)

app = modal.App(name="otonote-engine", image=image)

@app.function(
    gpu="T4", 
    timeout=1200, 
    secrets=[modal.Secret.from_name("huggingface-secret")]
)
def run_transcription(audio_bytes: bytes):
    import torch
    import numpy as np
    import librosa
    from pyannote.audio import Pipeline
    from transformers import pipeline
    import tempfile
    from pathlib import Path

    # Colabのパッチをここに適用
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    
    with tempfile.TemporaryDirectory() as td:
        wav_path = Path(td) / "audio_16k.wav"
        # 直接バイナリから読み込んで保存
        with open(wav_path, "wb") as f:
            f.write(audio_bytes)

        # 1. 話者分離
        pipeline_diar = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", 
            use_auth_token=os.environ["HF_TOKEN"]
        ).to(device)
        diarization = pipeline_diar(str(wav_path))

        # 2. 精密文字起こし
        asr_model = pipeline(
            "automatic-speech-recognition", 
            model="openai/whisper-large-v3",
            device=0 if torch.cuda.is_available() else -1, 
            torch_dtype=torch.float16
        )

        audio, sr = librosa.load(str(wav_path), sr=16000)
        
        speaker_map, next_num, final_lines = {}, 1, []

        for turn, _, speaker in diarization.itertracks(yield_label=True):
            start_sample = int(turn.start * sr)
            end_sample = int(turn.end * sr)
            segment = audio[start_sample:end_sample]

            if len(segment) < sr * 0.5: continue

            res = asr_model(segment, return_timestamps=True, generate_kwargs={"language": "japanese"})
            text = res["text"].strip()
            if not text: continue

            if speaker not in speaker_map:
                speaker_map[speaker] = f"話者 {next_num}"
                next_num += 1

            line = f"[{turn.start:5.1f}s - {turn.end:5.1f}s] {speaker_map[speaker]}: {text}"
            final_lines.append(line)

        return "\n".join(final_lines)