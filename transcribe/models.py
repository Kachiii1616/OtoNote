import os
import re
from django.db import models


class TranscriptionJob(models.Model):
    STATUS_CHOICES = [
        ("queued", "queued"),
        ("running", "running"),
        ("done", "done"),
        ("error", "error"),
    ]

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="queued")
    progress = models.PositiveIntegerField(default=0)

    # Whisper設定
    model_name = models.CharField(max_length=32, default="small")   # tiny/base/small/medium/large
    segment_sec = models.PositiveIntegerField(default=600)          # 10min
    language = models.CharField(max_length=8, default="auto")       # auto/ja/en
    diarize = models.BooleanField(default=True)

    # R2に上げるので、ローカル保存は必須にしない（移行/保険として残す）
    input_file = models.FileField(upload_to="input/", blank=True, null=True)

    # R2情報
    original_filename = models.CharField(max_length=255, blank=True, default="")
    r2_key = models.CharField(max_length=1024, blank=True, default="")

    # 結果
    output_text = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    def __str__(self):
        return f"Job#{self.id} {self.status} {self.progress}%"

    @property
    def display_filename(self) -> str:
        """
        画面表示用ファイル名。
        - まず original_filename を優先（R2運用）
        - 無ければ input_file.name を使う（フォールバック）
        """
        base = self.original_filename or (os.path.basename(self.input_file.name) if self.input_file else "")
        if not base:
            return ""
        name, ext = os.path.splitext(base)
        name = re.sub(r"_[A-Za-z0-9]{6,10}$", "", name)
        return f"{name}{ext}"
