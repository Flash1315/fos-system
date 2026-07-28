"""Append-only audit journal helpers."""

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent


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
    event = AuditEvent(
        organization_id=org_id,
        actor_user_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        detail_json=(
            json.dumps(detail, ensure_ascii=False, default=str, sort_keys=True)
            if detail is not None
            else None
        ),
    )
    db.add(event)
    db.flush()
    return event
