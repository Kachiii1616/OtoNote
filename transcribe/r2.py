# transcribe/r2.py
import os
import boto3
from botocore.config import Config

def _require_env(name: str) -> str:
    v = os.getenv(name)
    if not v or not v.strip():
        raise RuntimeError(f"{name} is missing")
    return v.strip()

def r2_client():
    return boto3.client(
        "s3",
        endpoint_url=_require_env("R2_ENDPOINT_URL"),
        aws_access_key_id=_require_env("R2_ACCESS_KEY_ID"),
        aws_secret_access_key=_require_env("R2_SECRET_ACCESS_KEY"),
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )

def bucket_name() -> str:
    return _require_env("R2_BUCKET_NAME")

def upload_fileobj(fileobj, key: str, content_type: str | None = None):
    s3 = r2_client()
    extra = {}
    if content_type:
        extra["ContentType"] = content_type
    s3.upload_fileobj(fileobj, bucket_name(), key, ExtraArgs=extra)

def download_file(key: str, local_path: str):
    s3 = r2_client()
    s3.download_file(bucket_name(), key, local_path)
