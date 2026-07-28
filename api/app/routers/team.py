import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.schemas import (
    MemberOut,
    MemberActiveIn,
    MemberRoleIn,
    MemberPasswordResetIn,
    MemberResetTokenOut,
)
from app.auth import bump_token_version, get_current_user, require_roles, hash_password
from app.db import get_db
from app.models import (
    MoneyRecord,
    Organization,
    RecordStatus,
    SettlementRequest,
    SettlementRequestStatus,
    User,
    UserRole,
)
from app.services.org_limits import require_org_can_add_member, require_org_member_capacity

router = APIRouter(prefix="/orgs", tags=["team"])

RESET_TTL_DAYS = 2
_LIST_LIMIT_DEFAULT = 200
_LIST_LIMIT_MAX = 200
_LIST_OFFSET_MAX = 10_000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.get("/members", response_model=list[MemberOut])
def list_members(
    limit: int = Query(default=_LIST_LIMIT_DEFAULT, ge=1, le=_LIST_LIMIT_MAX),
    offset: int = Query(default=0, ge=0, le=_LIST_OFFSET_MAX),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"members-list:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    require_org_member_capacity(db, user.organization_id)
    rows = (
        db.query(User)
        .filter(User.organization_id == user.organization_id)
        .order_by(User.role.asc(), User.full_name.asc(), User.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [MemberOut.model_validate(r) for r in rows]


@router.get("/directory", response_model=list[MemberOut])
def org_directory(
    limit: int = Query(default=_LIST_LIMIT_DEFAULT, ge=1, le=_LIST_LIMIT_MAX),
    offset: int = Query(default=0, ge=0, le=_LIST_OFFSET_MAX),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Active teammates visible to everyone (for transfers / filing)."""
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"org-directory:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    require_org_member_capacity(db, user.organization_id, active_only=True)
    rows = (
        db.query(User)
        .filter(
            User.organization_id == user.organization_id,
            User.is_active.is_(True),
            User.must_set_password.is_(False),
        )
        .order_by(User.full_name.asc(), User.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [MemberOut.model_validate(r) for r in rows]


@router.post("/members/{member_id}/active", response_model=MemberOut)
def set_member_active(
    member_id: int,
    body: MemberActiveIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner)),
):
    from app.services.locks import lock_organization, lock_users
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"member-active:{user.organization_id}:{user.id}",
        limit=30,
        window_sec=60,
    )
    lock_organization(db, user.organization_id)
    member = (
        db.query(User)
        .filter(User.id == member_id, User.organization_id == user.organization_id)
        .with_for_update()
        .first()
    )
    if not member or member.organization_id != user.organization_id:
        raise HTTPException(404, "User not found")
    if member.id == user.id:
        raise HTTPException(400, "Cannot deactivate yourself")
    if member.role == UserRole.owner and member.is_active and not body.is_active:
        owners = (
            db.query(User)
            .filter(
                User.organization_id == user.organization_id,
                User.role == UserRole.owner,
                User.is_active.is_(True),
            )
            .count()
        )
        if owners <= 1:
            raise HTTPException(400, "Cannot deactivate the last active owner")
    if not body.is_active:
        lock_users(db, member.id)
        pending_recs = (
            db.query(MoneyRecord.id)
            .filter(
                MoneyRecord.organization_id == user.organization_id,
                MoneyRecord.created_by == member.id,
                MoneyRecord.status == RecordStatus.pending,
            )
            .first()
        )
        if pending_recs:
            raise HTTPException(
                400,
                "Cannot deactivate — teammate still has pending records to decide",
            )
        pending_req = (
            db.query(SettlementRequest.id)
            .filter(
                SettlementRequest.organization_id == user.organization_id,
                SettlementRequest.user_id == member.id,
                SettlementRequest.status == SettlementRequestStatus.pending,
            )
            .first()
        )
        if pending_req:
            raise HTTPException(
                400,
                "Cannot deactivate — teammate still has pending settlement requests",
            )
        from app.services.balances import user_balance

        bal = user_balance(db, member)
        cash = float(bal.get("cash_on_hand") or 0)
        spend = float(bal.get("spendings") or 0)
        reserved_cash = float(bal.get("reserved_cash") or 0)
        reserved_spend = float(bal.get("reserved_spendings") or 0)
        if (
            cash > 1e-6
            or spend > 1e-6
            or reserved_cash > 1e-6
            or reserved_spend > 1e-6
        ):
            raise HTTPException(
                400,
                "Cannot deactivate — teammate still holds cash or spendings "
                "(settle or adjust to zero first)",
            )
    if body.is_active and not member.is_active:
        require_org_can_add_member(db, user.organization_id)
        if member.must_set_password and not member.invite_token:
            raise HTTPException(
                400,
                "Issue a reset token before reactivating — teammate still must set a password",
            )
        expires = getattr(member, "invite_token_expires_at", None)
        if (
            member.must_set_password
            and expires is not None
            and expires < _utcnow()
        ):
            raise HTTPException(
                400,
                "Invite/reset token expired — issue a new reset token before reactivating",
            )
    member.is_active = body.is_active
    if not body.is_active:
        bump_token_version(member)
        # Keep invite/reset token for unsettled invitees so they can still accept after reactivate.
        if not member.must_set_password:
            member.invite_token = None
            member.invite_token_expires_at = None
    db.commit()
    db.refresh(member)
    return MemberOut.model_validate(member)


@router.post("/members/{member_id}/role", response_model=MemberOut)
def set_member_role(
    member_id: int,
    body: MemberRoleIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner)),
):
    from app.services.locks import lock_organization
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"member-role:{user.organization_id}:{user.id}",
        limit=30,
        window_sec=60,
    )
    lock_organization(db, user.organization_id)
    member = (
        db.query(User)
        .filter(User.id == member_id, User.organization_id == user.organization_id)
        .with_for_update()
        .first()
    )
    if not member or member.organization_id != user.organization_id:
        raise HTTPException(404, "User not found")
    if member.id == user.id and body.role != UserRole.owner:
        raise HTTPException(400, "Cannot demote yourself")
    if (
        member.role == UserRole.owner
        and body.role != UserRole.owner
        and member.is_active
    ):
        owners = (
            db.query(User)
            .filter(
                User.organization_id == user.organization_id,
                User.role == UserRole.owner,
                User.is_active.is_(True),
            )
            .count()
        )
        if owners <= 1:
            raise HTTPException(400, "Cannot demote the last active owner")
    if member.role != body.role:
        member.role = body.role
        bump_token_version(member)
    db.commit()
    db.refresh(member)
    return MemberOut.model_validate(member)


@router.post("/members/{member_id}/password", response_model=MemberOut)
def reset_member_password(
    member_id: int,
    body: MemberPasswordResetIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner)),
):
    from app.services.locks import lock_organization
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"reset-password:{user.organization_id}:{user.id}",
        limit=20,
        window_sec=60,
    )
    enforce_rate_limit(
        f"reset-password-member:{user.organization_id}:{member_id}",
        limit=5,
        window_sec=900,
    )
    lock_organization(db, user.organization_id)
    member = (
        db.query(User)
        .filter(User.id == member_id, User.organization_id == user.organization_id)
        .with_for_update()
        .first()
    )
    if not member or member.organization_id != user.organization_id:
        raise HTTPException(404, "User not found")
    if member.id == user.id:
        raise HTTPException(400, "Use Account → Change password for your own password")
    member.hashed_password = hash_password(body.new_password)
    bump_token_version(member)
    member.must_set_password = False
    member.invite_token = None
    member.invite_token_expires_at = None
    db.commit()
    db.refresh(member)
    org = db.get(Organization, user.organization_id)
    if org:
        from app.services.notify import notify_org

        notify_org(org, f"Fos: password set by owner for {member.full_name}")
    return MemberOut.model_validate(member)


@router.post("/members/{member_id}/reset-token", response_model=MemberResetTokenOut)
def issue_member_reset_token(
    member_id: int,
    request: Request,
    force: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner)),
):
    """Issue a one-time token; teammate sets a new password via /auth/accept-invite."""
    from app.services.invite_tokens import store_invite_token
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(f"reset-token:{user.organization_id}:{user.id}", limit=20, window_sec=60)
    enforce_rate_limit(
        f"reset-token-member:{user.organization_id}:{member_id}",
        limit=3,
        window_sec=900,
    )
    from app.services.org_gates import require_org_writable

    require_org_writable(db, user.organization_id)
    member = (
        db.query(User)
        .filter(User.id == member_id, User.organization_id == user.organization_id)
        .with_for_update()
        .first()
    )
    if not member or member.organization_id != user.organization_id:
        raise HTTPException(404, "User not found")
    if member.id == user.id:
        raise HTTPException(400, "Use Account → Change password for your own password")
    # Inactive members may receive a recovery token only when they still must set a password.
    if not member.is_active and not member.must_set_password:
        raise HTTPException(400, "Member is inactive")
    expires = getattr(member, "invite_token_expires_at", None)
    if (
        not force
        and member.must_set_password
        and member.invite_token
        and (expires is None or expires >= _utcnow())
    ):
        raise HTTPException(
            409,
            "Active reset/invite token already exists — share the previous token "
            "or pass force=true to rotate",
        )
    org = db.get(Organization, user.organization_id)
    raw_token = secrets.token_urlsafe(24)
    member.hashed_password = hash_password(secrets.token_urlsafe(24))
    member.invite_token = store_invite_token(raw_token)
    member.invite_token_expires_at = _utcnow() + timedelta(days=RESET_TTL_DAYS)
    member.must_set_password = True
    bump_token_version(member)
    db.commit()
    db.refresh(member)
    emailed = False
    if org:
        from app.services.email import send_reset_email
        from app.services.notify import notify_org

        emailed = send_reset_email(
            to=member.email,
            full_name=member.full_name,
            org_name=org.name,
            org_slug=org.slug,
            reset_token=raw_token,
        )
        notify_org(org, f"Fos: password reset token issued for {member.full_name}")
    return MemberResetTokenOut(
        id=member.id,
        email=member.email,
        full_name=member.full_name,
        organization_slug=org.slug if org else "",
        invite_token="" if emailed else raw_token,
        must_set_password=True,
        email_sent=emailed,
    )
