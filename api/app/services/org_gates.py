"""Organization / member readiness gates for money and auth flows."""

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Organization, User


def require_member_ready(user: User | None, *, action: str = "this action") -> User:
    """Active teammate who has finished invite/password setup."""
    if not user or not user.is_active:
        raise HTTPException(404, "User not found")
    if getattr(user, "must_set_password", False):
        raise HTTPException(
            400,
            f"Teammate must accept invite / set password before {action}",
        )
    return user


def require_org_writable(db: Session, org_id: int) -> Organization:
    """Refuse money mutations when billing is canceled."""
    org = db.get(Organization, org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    status = (getattr(org, "billing_status", None) or "ok").strip().lower()
    if status == "canceled":
        raise HTTPException(403, "Organization billing is canceled")
    return org
