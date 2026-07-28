import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import get_current_user, user_from_token
from app.db import get_db
from app.models import User
from app.schemas import PhotoOut
from app.services import storage
from app.services.images import detect_image, read_upload_capped
from app.services.rate_limit import enforce_rate_limit

router = APIRouter(tags=["media"])
logger = logging.getLogger(__name__)

_optional_bearer = HTTPBearer(auto_error=False)


@router.post("/media/photo", response_model=PhotoOut)
async def upload_photo(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    enforce_rate_limit(
        f"upload:{user.organization_id}:{user.id}",
        limit=30,
        window_sec=60,
    )
    data = await read_upload_capped(file)
    suffix, content_type = detect_image(data)
    name = f"{uuid.uuid4().hex}{suffix}"
    try:
        url = storage.store_photo(user.organization_id, name, data, content_type)
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "photo upload failed org=%s err=%s",
            user.organization_id,
            type(exc).__name__,
        )
        raise HTTPException(500, "Upload failed") from exc
    return PhotoOut(photo_url=url)


@router.get("/media/files/{org_id}/{filename}")
def get_photo(
    org_id: int,
    filename: str,
    token: str | None = Query(default=None),
    creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    """Auth via Bearer (access or media) or ?token= (media-only) for <Image> tags."""
    if creds and creds.credentials:
        user = user_from_token(creds.credentials, db, allow_media=True)
    elif token:
        # Query tokens must be short-lived media JWTs — never long-lived access tokens.
        user = user_from_token(token, db, allow_media=True, require_media=True)
    else:
        raise HTTPException(401, "Could not validate credentials")
    if org_id != user.organization_id:
        raise HTTPException(403, "Forbidden")
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    if storage.media_backend() == "local":
        path = storage.local_path(org_id, filename)
        if not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(path)
    data, meta = storage.load_photo(org_id, filename)
    if data is None and meta and meta.startswith("http"):
        return RedirectResponse(meta)
    if data is None:
        raise HTTPException(404, "Not found")
    return Response(content=data, media_type=meta or "application/octet-stream")
