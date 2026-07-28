"""Soft organization size ceilings for expensive list/report endpoints."""

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User


def require_org_member_capacity(
    db: Session,
    org_id: int,
    *,
    active_only: bool = False,
) -> int:
    q = db.query(func.count(User.id)).filter(User.organization_id == org_id)
    if active_only:
        q = q.filter(User.is_active.is_(True))
    count = int(q.scalar() or 0)
    limit = max(1, int(settings.max_org_members or 300))
    if count > limit:
        raise HTTPException(
            400,
            f"Organization has too many members for this endpoint (max {limit})",
        )
    return count
