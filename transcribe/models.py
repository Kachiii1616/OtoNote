import os
import re
from django.db import models
import unicodedata as ud



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

    model_name = models.CharField(max_length=32, default="small")  # base/small/medium
    segment_sec = models.PositiveIntegerField(default=600)          # 10min
    language = models.CharField(max_length=8, default="ja")         # ja/en/auto

    input_file = models.FileField(upload_to="input/")
    output_text = models.TextField(blank=True, default="")
    error_message = models.TextField(blank=True, default="")

    original_filename = models.CharField(max_length=255, blank=True, default="")


    def __str__(self):
        return f"Job#{self.id} {self.status} {self.progress}%"
    
    diarize = models.BooleanField(default=True)
    
    @property
    def display_filename(self):
        if not self.input_file:
            return ""

        base = os.path.basename(self.input_file.name)
        name, ext = os.path.splitext(base)

        name = re.sub(r"_[A-Za-z0-9]{6,10}$", "", name)
        return f"{name}{ext}"
    
    