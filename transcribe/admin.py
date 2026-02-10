from django.contrib import admin
from .models import TranscriptionJob

@admin.register(TranscriptionJob)
class TranscriptionJobAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "progress", "created_at", "input_file", "diarize")
    list_filter = ("status", "diarize")
    search_fields = ("id", "status", "input_file")
    ordering = ("-created_at",)
