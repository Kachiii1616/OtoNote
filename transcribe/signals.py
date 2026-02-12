from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver
from .models import TranscriptionJob

@receiver(post_delete, sender=TranscriptionJob)
def delete_input_file_on_delete(sender, instance, **kwargs):
    # 管理画面でJobを削除した時に、紐づくファイルも消す
    if instance.input_file:
        instance.input_file.delete(save=False)

@receiver(pre_save, sender=TranscriptionJob)
def delete_old_file_on_change(sender, instance, **kwargs):
    # ファイルを差し替えた時に、古い方のファイルを消す（任意だけど事故防止になる）
    if not instance.pk:
        return
    try:
        old = TranscriptionJob.objects.get(pk=instance.pk)
    except TranscriptionJob.DoesNotExist:
        return
    if old.input_file and old.input_file != instance.input_file:
        old.input_file.delete(save=False)
