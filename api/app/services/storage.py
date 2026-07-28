"""Local disk or S3-compatible object storage for receipt photos."""

import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


def media_backend() -> str:
    backend = (settings.media_backend or "local").strip().lower()
    if backend == "s3" and settings.s3_bucket.strip():
        return "s3"
    return "local"


def _s3_client():
    try:
        import boto3  # type: ignore
    except ImportError as exc:
        raise RuntimeError("boto3 is required for MEDIA_BACKEND=s3") from exc
    kwargs: dict = {
        "service_name": "s3",
        "region_name": settings.s3_region or "us-east-1",
    }
    if settings.s3_access_key:
        kwargs["aws_access_key_id"] = settings.s3_access_key
        kwargs["aws_secret_access_key"] = settings.s3_secret_key
    if settings.s3_endpoint_url:
        kwargs["endpoint_url"] = settings.s3_endpoint_url
    return boto3.client(**kwargs)


def store_photo(org_id: int, filename: str, data: bytes, content_type: str = "image/jpeg") -> str:
    """Persist bytes; return API-relative photo_url path."""
    if media_backend() == "s3":
        key = f"{org_id}/{filename}"
        client = _s3_client()
        client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        logger.info("photo uploaded s3 bucket=%s", settings.s3_bucket)
        return f"/media/files/{org_id}/{filename}"
    org_dir = UPLOAD_ROOT / str(org_id)
    org_dir.mkdir(parents=True, exist_ok=True)
    dest = org_dir / filename
    dest.write_bytes(data)
    logger.info("photo uploaded local org=%s", org_id)
    return f"/media/files/{org_id}/{filename}"


def content_type_for(filename: str) -> str:
    lower = (filename or "").lower()
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    return "application/octet-stream"


def local_path(org_id: int, filename: str) -> Path:
    org_root = (UPLOAD_ROOT / str(org_id)).resolve()
    path = (UPLOAD_ROOT / str(org_id) / filename).resolve()
    if not path.is_relative_to(org_root):
        raise ValueError("invalid media path")
    return path


def load_photo(org_id: int, filename: str) -> tuple[bytes | None, str | None]:
    """Return (bytes, content_type) or (None, None). For S3 may return redirect URL in second."""
    if media_backend() == "s3":
        key = f"{org_id}/{filename}"
        if settings.s3_public_base_url.strip():
            base = settings.s3_public_base_url.strip().rstrip("/")
            return None, f"{base}/{key}"
        client = _s3_client()
        try:
            obj = client.get_object(Bucket=settings.s3_bucket, Key=key)
            body = obj["Body"].read()
            ctype = obj.get("ContentType") or "application/octet-stream"
            return body, ctype
        except Exception as exc:  # noqa: BLE001
            logger.warning("s3 get failed org=%s err=%s", org_id, type(exc).__name__)
            return None, None
    try:
        path = local_path(org_id, filename)
    except ValueError:
        return None, None
    if not path.is_file():
        return None, None
    return path.read_bytes(), content_type_for(filename)