"""Row-lock helpers for balance-changing paths (no-op-ish on SQLite)."""

from sqlalchemy.orm import Session

from app.models import Organization, User


def lock_users(db: Session, *user_ids: int | None) -> None:
    """Lock user rows in ascending id order to avoid deadlocks."""
    ids = sorted({int(uid) for uid in user_ids if uid is not None})
    for uid in ids:
        db.query(User).filter(User.id == uid).with_for_update().first()


def lock_organization(db: Session, organization_id: int) -> Organization | None:
    return (
        db.query(Organization)
        .filter(Organization.id == organization_id)
        .with_for_update()
        .first()
    )
