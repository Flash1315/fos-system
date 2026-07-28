"""Hash invite/reset tokens at rest; keep transitional plaintext lookup."""

from __future__ import annotations

import hashlib

from sqlalchemy.orm import Session

from app.models import User


def hash_invite_token(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode("utf-8")).hexdigest()


def store_invite_token(raw: str) -> str:
    """Return value to persist on User.invite_token (SHA-256 hex)."""
    return hash_invite_token(raw)


def find_user_by_invite_token(db: Session, raw: str) -> User | None:
    token = (raw or "").strip()
    if not token:
        return None
    digest = hash_invite_token(token)
    user = db.query(User).filter(User.invite_token == digest).first()
    if user:
        return user
    # Transitional: tokens issued before hashing were stored plaintext
    return db.query(User).filter(User.invite_token == token).first()
