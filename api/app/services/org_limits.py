"""Soft organization size ceilings for expensive list/report endpoints."""

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.models import User


def org_member_limit() -> int:
    return max(1, min(10_000, int(settings.max_org_members or 300)))


def count_org_members(
    db: Session,
    org_id: int,
    *,
    active_only: bool = False,
) -> int:
    q = db.query(func.count(User.id)).filter(User.organization_id == org_id)
    if active_only:
        q = q.filter(User.is_active.is_(True))
    return int(q.scalar() or 0)


def require_org_member_capacity(
    db: Session,
    org_id: int,
    *,
    active_only: bool = False,
) -> int:
    count = count_org_members(db, org_id, active_only=active_only)
    limit = org_member_limit()
    if count > limit:
        raise HTTPException(
            400,
            f"Organization has too many members for this endpoint (max {limit})",
        )
    return count


def require_org_can_add_member(db: Session, org_id: int) -> int:
    """Block invite / reactivate when the org is already at the soft ceiling."""
    count = count_org_members(db, org_id)
    limit = org_member_limit()
    if count >= limit:
        raise HTTPException(
            400,
            f"Organization member limit reached (max {limit})",
        )
    return count
