"""Request idempotency for mutating money endpoints."""

from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import IdempotencyKey


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def normalize_idem_key(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip()
    if not key:
        return None
    if len(key) > 128:
        raise HTTPException(400, "Idempotency-Key too long (max 128)")
    # Printable ASCII only — reject control chars / non-ASCII noise
    if any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
        raise HTTPException(400, "Idempotency-Key contains invalid characters")
    return key


def fingerprint(payload: Any) -> str:
    """Stable SHA-256 of a request payload (sorted JSON)."""
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def lookup_idem(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    scope: str,
    key: str,
) -> IdempotencyKey | None:
    return (
        db.query(IdempotencyKey)
        .filter(
            IdempotencyKey.organization_id == organization_id,
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.scope == scope,
            IdempotencyKey.key == key,
        )
        .first()
    )


def require_idem_match(hit: IdempotencyKey, request_hash: str | None) -> None:
    """Reject reuse of the same key with a different payload (409)."""
    if not request_hash:
        return
    stored = (getattr(hit, "request_hash", None) or "").strip()
    if stored and stored != request_hash:
        raise HTTPException(
            409,
            "Idempotency-Key was already used with a different request",
        )


def store_idem(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    scope: str,
    key: str,
    resource_id: int,
    secondary_id: int | None = None,
    response_json: str | None = None,
    request_hash: str | None = None,
) -> IdempotencyKey:
    row = IdempotencyKey(
        organization_id=organization_id,
        user_id=user_id,
        scope=scope,
        key=key,
        resource_id=resource_id,
        secondary_id=secondary_id,
        response_json=response_json,
        request_hash=request_hash,
        created_at=_utcnow(),
    )
    db.add(row)
    return row


def dumps_json(payload) -> str:
    return json.dumps(payload, default=str)


def loads_json(raw: str | None):
    if not raw:
        return None
    return json.loads(raw)


def commit_or_replay(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    scope: str,
    key: str | None,
    request_hash: str | None,
    load_replay,
):
    """Commit; on unique idempotency race, roll back and return the winner's response."""
    from sqlalchemy.exc import IntegrityError

    try:
        db.commit()
        return None
    except IntegrityError:
        db.rollback()
        if not key:
            raise HTTPException(409, "Concurrent request conflict — retry") from None
        hit = lookup_idem(
            db,
            organization_id=organization_id,
            user_id=user_id,
            scope=scope,
            key=key,
        )
        if hit:
            require_idem_match(hit, request_hash)
            replay = load_replay(hit)
            if replay is not None:
                return replay
        raise HTTPException(409, "Concurrent request conflict — retry") from None
