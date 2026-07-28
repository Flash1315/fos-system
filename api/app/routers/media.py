import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth import get_current_user, user_from_token
from app.db import get_db
from app.models import User
from app.schemas import PhotoOut

router = APIRouter(tags=["media"])

UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
ALLOWED = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
_optional_bearer = HTTPBearer(auto_error=False)


def _user_from_token(token: str, db: Session) -> User:
    return user_from_token(token, db)


@router.post("/media/photo", response_model=PhotoOut)
async def upload_photo(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    suffix = Path(file.filename or "photo.jpg").suffix.lower() or ".jpg"
    if suffix not in ALLOWED:
        raise HTTPException(400, "Only image uploads allowed")
    org_dir = UPLOAD_ROOT / str(user.organization_id)
    org_dir.mkdir(parents=True, exist_ok=True)
    name = f"{uuid.uuid4().hex}{suffix}"
    dest = org_dir / name
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "File too large (max 8MB)")
    if len(data) < 24:
        raise HTTPException(400, "File too small or empty")
    dest.write_bytes(data)
    print(f"photo uploaded org={user.organization_id} user={user.id} path={dest}")
    url = f"/media/files/{user.organization_id}/{name}"
    return PhotoOut(photo_url=url)


@router.get("/media/files/{org_id}/{filename}")
def get_photo(
    org_id: int,
    filename: str,
    token: str | None = Query(default=None),
    creds: HTTPAuthorizationCredentials | None = Depends(_optional_bearer),
    db: Session = Depends(get_db),
):
    """Auth via Bearer header or ?token= for <Image> tags that cannot set headers."""
    raw = None
    if creds and creds.credentials:
        raw = creds.credentials
    elif token:
        raw = token
    if not raw:
        raise HTTPException(401, "Could not validate credentials")
    user = _user_from_token(raw, db)
    if org_id != user.organization_id:
        raise HTTPException(403, "Forbidden")
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    path = UPLOAD_ROOT / str(org_id) / filename
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(path)
