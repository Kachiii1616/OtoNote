from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings

from transcribe.models import TranscriptionJob


class Command(BaseCommand):
    help = "Delete orphan files under MEDIA_ROOT/input that are not referenced by TranscriptionJob.input_file."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted, but do not delete.",
        )
        parser.add_argument(
            "--only",
            choices=["input"],
            default="input",
            help="Which subdir under MEDIA_ROOT to check (default: input).",
        )

    def handle(self, *args, **opts):
        dry = opts["dry_run"]
        subdir = opts["only"]

        media_root = Path(settings.MEDIA_ROOT)
        target_dir = media_root / subdir

        if not target_dir.exists():
            self.stdout.write(self.style.WARNING(f"Target dir does not exist: {target_dir}"))
            return

        # DBに存在するファイル（例: "input/xxx.wav"）を全部集める
        referenced = set(
            TranscriptionJob.objects.exclude(input_file="")
            .values_list("input_file", flat=True)
        )

        # filesystem側（MEDIA_ROOT/input/xxx.wav）を走査して突合
        deleted = 0
        kept = 0

        for path in target_dir.rglob("*"):
            if path.is_dir():
                continue

            rel = path.relative_to(media_root).as_posix()  # "input/xxx.wav" 形式
            if rel in referenced:
                kept += 1
                continue

            # DBに紐づいてない → 孤児
            self.stdout.write(f"ORPHAN: {rel}")
            deleted += 1
            if not dry:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass

        # 空ディレクトリの掃除（任意、dry-runではやらない）
        if not dry:
            for d in sorted(target_dir.rglob("*"), reverse=True):
                if d.is_dir():
                    try:
                        d.rmdir()  # 空なら消える、空じゃなければ例外で残る
                    except OSError:
                        pass

        if dry:
            self.stdout.write(self.style.WARNING(f"[dry-run] orphan files that would be deleted: {deleted}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Deleted orphan files: {deleted}"))

        self.stdout.write(f"Kept (referenced) files: {kept}")
