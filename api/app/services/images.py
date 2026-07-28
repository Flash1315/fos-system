"""Detect and bound receipt image uploads."""

from fastapi import HTTPException

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
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
            raise HTTPException(400, "File too large (max 8MB)")
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
