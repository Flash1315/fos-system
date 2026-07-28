import hashlib
import logging
import re

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

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
_MEDIA_NAME_RE = re.compile(r"^[0-9a-f]{32}\.(?:jpg|png|webp)$")


@router.post("/media/photo", response_model=PhotoOut)
async def upload_photo(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from app.services.idempotency import (
        commit_or_replay,
        dumps_json,
        fingerprint,
        loads_json,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.org_gates import require_org_writable

    enforce_rate_limit(
        f"upload:{user.organization_id}:{user.id}",
        limit=30,
        window_sec=60,
    )
    key = normalize_idem_key(idempotency_key)
    data = await read_upload_capped(file)
    content_sha = hashlib.sha256(data).hexdigest()
    fp = fingerprint({"bytes_sha": content_sha}) if key else None
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="media.photo",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            if hit.response_json:
                cached = loads_json(hit.response_json)
                if isinstance(cached, dict) and cached.get("photo_url"):
                    return PhotoOut.model_validate(cached)

    require_org_writable(db, user.organization_id)
    suffix, content_type = detect_image(data)
    # Content-addressed name (32 hex) — same bytes → same path, fewer orphan uploads.
    name = f"{content_sha[:32]}{suffix}"
    try:
        url = await run_in_threadpool(
            storage.store_photo,
            user.organization_id,
            name,
            data,
            content_type,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "photo upload failed org=%s err=%s",
            user.organization_id,
            type(exc).__name__,
        )
        raise HTTPException(503, "Media storage unavailable") from exc
    out = PhotoOut(photo_url=url)
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="media.photo",
            key=key,
            resource_id=-1,
            response_json=dumps_json(out.model_dump(mode="json")),
            request_hash=fp,
        )
        replay = commit_or_replay(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="media.photo",
            key=key,
            request_hash=fp,
            load_replay=lambda hit: (
                PhotoOut.model_validate(cached)
                if hit.response_json
                and isinstance((cached := loads_json(hit.response_json)), dict)
                else None
            ),
        )
        if replay is not None:
            return replay
    return out


@router.get("/media/files/{org_id}/{filename}")
def get_photo(
    org_id: int,
    filename: str,
    token: str | None = Query(default=None, max_length=2048),
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
    enforce_rate_limit(
        f"media-get:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    if org_id != user.organization_id:
        raise HTTPException(403, "Forbidden")
    if "/" in filename or ".." in filename or not _MEDIA_NAME_RE.match(filename):
        raise HTTPException(400, "Invalid filename")
    # Always go through load_photo so local OSError maps to 503 like S3 outages.
    data, _meta, err = storage.load_photo(org_id, filename)
    if err == "unavailable":
        raise HTTPException(503, "Media storage unavailable")
    if data is None or err == "not_found":
        raise HTTPException(404, "Not found")
    return Response(
        content=data,
        media_type=storage.content_type_for(filename),
        headers={"Cache-Control": "no-store"},
    )
