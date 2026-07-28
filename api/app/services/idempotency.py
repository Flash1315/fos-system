"""Request idempotency for mutating money endpoints."""

from datetime import datetime, timezone

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
    return key


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


def store_idem(
    db: Session,
    *,
    organization_id: int,
    user_id: int,
    scope: str,
    key: str,
    resource_id: int,
    secondary_id: int | None = None,
) -> IdempotencyKey:
    row = IdempotencyKey(
        organization_id=organization_id,
        user_id=user_id,
        scope=scope,
        key=key,
        resource_id=resource_id,
        secondary_id=secondary_id,
        created_at=_utcnow(),
    )
    db.add(row)
    return row
