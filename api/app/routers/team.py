import secrets

from fastapi import APIRouter, Depends, HTTPException
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
from app.models import Organization, User, UserRole

router = APIRouter(prefix="/orgs", tags=["team"])


@router.get("/members", response_model=list[MemberOut])
def list_members(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    rows = (
        db.query(User)
        .filter(User.organization_id == user.organization_id)
        .order_by(User.role.asc(), User.full_name.asc())
        .all()
    )
    return [MemberOut.model_validate(r) for r in rows]


@router.get("/directory", response_model=list[MemberOut])
def org_directory(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Active teammates visible to everyone (for transfers / filing)."""
    rows = (
        db.query(User)
        .filter(User.organization_id == user.organization_id, User.is_active.is_(True))
        .order_by(User.full_name.asc())
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
    member = db.get(User, member_id)
    if not member or member.organization_id != user.organization_id:
        raise HTTPException(404, "User not found")
    if member.id == user.id:
        raise HTTPException(400, "Cannot deactivate yourself")
    if member.role == UserRole.owner and not body.is_active:
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
    member.is_active = body.is_active
    if not body.is_active:
        bump_token_version(member)
        member.invite_token = None
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
    member = db.get(User, member_id)
    if not member or member.organization_id != user.organization_id:
        raise HTTPException(404, "User not found")
    if member.id == user.id and body.role != UserRole.owner:
        raise HTTPException(400, "Cannot demote yourself")
    if member.role == UserRole.owner and body.role != UserRole.owner:
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
            raise HTTPException(400, "Cannot demote the last owner")
    member.role = body.role
    db.commit()
    db.refresh(member)
    return MemberOut.model_validate(member)


@router.post("/members/{member_id}/password", response_model=MemberOut)
def reset_member_password(
    member_id: int,
    body: MemberPasswordResetIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner)),
):
    member = db.get(User, member_id)
    if not member or member.organization_id != user.organization_id:
        raise HTTPException(404, "User not found")
    member.hashed_password = hash_password(body.new_password)
    bump_token_version(member)
    member.must_set_password = False
    member.invite_token = None
    db.commit()
    db.refresh(member)
    return MemberOut.model_validate(member)


@router.post("/members/{member_id}/reset-token", response_model=MemberResetTokenOut)
def issue_member_reset_token(
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner)),
):
    """Issue a one-time token; teammate sets a new password via /auth/accept-invite."""
    member = db.get(User, member_id)
    if not member or member.organization_id != user.organization_id:
        raise HTTPException(404, "User not found")
    if not member.is_active:
        raise HTTPException(400, "Member is inactive")
    org = db.get(Organization, user.organization_id)
    token = secrets.token_urlsafe(24)
    member.hashed_password = hash_password(secrets.token_urlsafe(24))
    member.invite_token = token
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
            reset_token=token,
        )
        notify_org(org, f"Fos: password reset token issued for {member.full_name}")
    return MemberResetTokenOut(
        id=member.id,
        email=member.email,
        full_name=member.full_name,
        organization_slug=org.slug if org else "",
        invite_token=token,
        must_set_password=True,
        email_sent=emailed,
    )
