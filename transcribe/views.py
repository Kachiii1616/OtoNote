from django import forms
from django.http import HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from .models import TranscriptionJob
import unicodedata as ud

class JobCreateForm(forms.ModelForm):
    MODEL_CHOICES = [
        ("tiny", "tiny（最速）"),
        ("base", "base（速い）"),
        ("small", "small（おすすめ）"),
        ("medium", "medium（高精度）"),
        ("large", "large（最高精度）"),
    ]

    LANG_CHOICES = [
        ("auto", "自動判定"),
        ("ja", "日本語"),
        ("en", "英語"),
    ]

    SEGMENT_CHOICES = [
        (10, "10秒"),
        (15, "15秒"),
        (20, "20秒"),
        (30, "30秒（おすすめ）"),
        (45, "45秒"),
        (60, "60秒"),
        (120, "120秒"),
        (300, "300秒"),
        (600, "600秒"),
    ]

    model_name = forms.ChoiceField(choices=MODEL_CHOICES, initial="small")
    segment_sec = forms.TypedChoiceField(choices=SEGMENT_CHOICES, coerce=int, initial=30)
    language = forms.ChoiceField(choices=LANG_CHOICES, initial="auto")

    class Meta:
        model = TranscriptionJob
        fields = ["input_file", "model_name", "segment_sec", "language", "diarize"]
        labels = {
            "input_file": "音声ファイル",
            "model_name": "Whisperモデル",
            "segment_sec": "分割（秒）",
            "language": "言語",
            "diarize": "話者分離（pyannote）",
        }
        widgets = {
            "input_file": forms.ClearableFileInput(attrs={
                "class": "fileInput",
                "id": "id_input_file",
            }),
            "diarize": forms.CheckboxInput(attrs={
                "id": "id_diarize",
            }),
        }

def job_create(request):
    if request.method == "POST":
        form = JobCreateForm(request.POST, request.FILES)
        if form.is_valid():
            job = form.save()
            return redirect("job_detail", job_id=job.id)
    else:
        form = JobCreateForm()
    return render(request, "transcribe/job_create.html", {"form": form})

def job_detail(request, job_id: int):
    job = get_object_or_404(TranscriptionJob, id=job_id)
    return render(request, "transcribe/job_detail.html", {"job": job})

def job_download(request, job_id: int):
    job = get_object_or_404(TranscriptionJob, id=job_id)
    if job.status != "done":
        raise Http404("Not ready")
    filename = f"transcript_job_{job.id}.txt"
    resp = HttpResponse(job.output_text, content_type="text/plain; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp

def job_list(request):
    jobs = TranscriptionJob.objects.order_by("-created_at")[:50]
    return render(request, "transcribe/job_list.html", {"jobs": jobs})


