"""Append-only audit journal helpers."""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent

_REDACT_KEYS = {
    "password",
    "token",
    "secret",
    "authorization",
    "current_password",
    "new_password",
    "invite_token",
    "access_token",
}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            key = str(k).lower()
            if key in _REDACT_KEYS or any(x in key for x in ("password", "token", "secret")):
                out[k] = "[redacted]"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def write_audit(
    db: Session,
    *,
    org_id: int,
    actor_id: int | None,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    detail: Any = None,
) -> AuditEvent:
    """Add and flush an audit event in the caller's transaction."""
    action = (action or "")[:64]
    entity_type = (entity_type or "")[:32]
    payload = _redact(detail) if detail is not None else None
    raw = (
        json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True)
        if payload is not None
        else None
    )
    if raw is not None and len(raw) > 8000:
        raw = raw[:8000]
    event = AuditEvent(
        organization_id=org_id,
        actor_user_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail_json=raw,
    )
    db.add(event)
    db.flush()
    return event
