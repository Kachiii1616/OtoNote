import os
import time
import tempfile
from pathlib import Path

# Django関連
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from transcribe.models import TranscriptionJob

# Modal関連
import modal

# R2関連のインポート（既存のものを維持）
try:
    from transcribe.r2 import download_file
except Exception:
    download_file = None

# 既存の resolve_input_audio_to_local_path 関数はそのままここに配置してください

class Command(BaseCommand):
    help = "Process queued transcription jobs via Modal GPU."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=1.0)

    def handle(self, *args, **opts):
        sleep_time = opts["sleep"]
        self.stdout.write(self.style.SUCCESS("✅ Modal-based Transcribe worker started."))

        while True:
            # 1. 未処理のジョブを取得
            job = (TranscriptionJob.objects
                   .filter(status="queued")
                   .order_by("created_at")
                   .first())

            if not job:
                time.sleep(sleep_time)
                continue

            # 2. ステータスを「実行中」に更新（アトミックに実行）
            with transaction.atomic():
                job = TranscriptionJob.objects.select_for_update().get(id=job.id)
                if job.status != "queued":
                    continue
                job.status = "running"
                job.started_at = timezone.now()
                job.save()

            try:
                # 3. 処理開始
                with tempfile.TemporaryDirectory() as td:
                    td_path = Path(td)
                    
                    # R2(S3)から音声をローカルにダウンロード
                    input_path = resolve_input_audio_to_local_path(job, td_path)
                    audio_bytes = input_path.read_bytes()

                    self.stdout.write(f"🚀 Job {job.id}: Modal GPUへ送信中... (サイズ: {len(audio_bytes)/1024/1024:.2f} MB)")

                    # 4. Modal 関数のルックアップと実行
                    # otonote-engine が modal deploy されている必要があります
                    f = modal.Function.lookup("otonote-engine", "run_transcription")
                    
                    # タイムアウトに備えて実行（Modal側で設定したtimeoutが優先されます）
                    final_text = f.remote(audio_bytes=audio_bytes)

                    # 5. 成功：結果を保存
                    job.output_text = final_text
                    job.status = "done"
                    job.progress = 100
                    job.finished_at = timezone.now()
                    job.save()

                    self.stdout.write(self.style.SUCCESS(f"✅ Job {job.id} 完了"))

            except Exception as e:
                # 6. 失敗：エラー内容を記録
                self.stdout.write(self.style.ERROR(f"❌ Job {job.id} 失敗: {str(e)}"))
                job.status = "error"
                job.error_message = f"Modal Error: {str(e)}"
                job.finished_at = timezone.now()
                job.save()