"""Detect and bound receipt image uploads."""

from io import BytesIO

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_SIDE = 8_000
_MIN_BYTES = 24
_CHUNK = 64 * 1024


async def read_upload_capped(file, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(413, "File too large (max 8MB)")
        chunks.append(chunk)
    data = b"".join(chunks)
    if len(data) < _MIN_BYTES:
        raise HTTPException(400, "File too small or empty")
    return data


def detect_image(data: bytes) -> tuple[str, str]:
    """Return (suffix, content_type) from magic bytes; reject non-images."""
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg", "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png", "image/png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp", "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12].lower()
        heic_brands = {
            b"heic",
            b"heif",
            b"mif1",
            b"msf1",
            b"heix",
            b"hevc",
            b"heim",
            b"hevx",
        }
        if brand in heic_brands or any(
            b in data[8:24].lower() for b in (b"heic", b"heif", b"heix")
        ):
            raise HTTPException(
                400,
                "HEIC/HEIF is not supported. Upload JPEG, PNG, or WebP.",
            )
    raise HTTPException(400, "Only image uploads allowed")


def sanitize_image(data: bytes) -> tuple[bytes, str, str]:
    """Validate and re-encode a receipt, removing metadata and embedded payloads."""
    suffix, _content_type = detect_image(data)
    try:
        with Image.open(BytesIO(data)) as source:
            width, height = source.size
            if (
                width <= 0
                or height <= 0
                or width * height > MAX_IMAGE_PIXELS
                or max(width, height) > MAX_IMAGE_SIDE
            ):
                raise HTTPException(400, "Image dimensions are too large")
            source.load()
            cleaned = source.convert("RGB")
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise HTTPException(400, "Invalid or corrupted image") from exc

    output = BytesIO()
    if suffix == ".png":
        cleaned.save(output, format="PNG", optimize=True)
        return output.getvalue(), ".png", "image/png"
    if suffix == ".webp":
        cleaned.save(output, format="WEBP", quality=85, method=4)
        return output.getvalue(), ".webp", "image/webp"
    cleaned.save(output, format="JPEG", quality=85, optimize=True)
    return output.getvalue(), ".jpg", "image/jpeg"
