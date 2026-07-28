import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth import (
    bump_token_version,
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    verify_password,
)
from app.db import get_db
from app.models import BalanceAdjustment, MoneyRecord, Organization, Payout, User, UserRole
from app.schemas import (
    AcceptInviteIn,
    InviteIn,
    InviteOut,
    LoginIn,
    OrgCreate,
    OrgOut,
    OrgUpdate,
    PasswordChangeIn,
    TokenOut,
    UserOut,
)
from app.services.rate_limit import client_ip, enforce_rate_limit

router = APIRouter(tags=["auth"])

INVITE_TTL_DAYS = 7


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _invite_expiry() -> datetime:
    return _utcnow() + timedelta(days=INVITE_TTL_DAYS)


def _currency_locked(db: Session, org_id: int) -> bool:
    if db.query(MoneyRecord.id).filter(MoneyRecord.organization_id == org_id).first():
        return True
    if db.query(Payout.id).filter(Payout.organization_id == org_id).first():
        return True
    if db.query(BalanceAdjustment.id).filter(BalanceAdjustment.organization_id == org_id).first():
        return True
    return False


def _org_out(db: Session, org: Organization) -> OrgOut:
    return OrgOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        currency=org.currency,
        currency_locked=_currency_locked(db, org.id),
    )


def _token_for(user: User) -> str:
    return create_access_token(
        user.id, user.organization_id, user.role.value, user.token_version or 0
    )


def _token_out(db: Session, user: User) -> TokenOut:
    org = db.get(Organization, user.organization_id)
    return TokenOut(
        access_token=_token_for(user),
        user=UserOut.model_validate(user),
        organization_slug=org.slug if org else "",
    )


@router.post("/orgs/register", response_model=TokenOut)
def register_organization(body: OrgCreate, request: Request, db: Session = Depends(get_db)):
    from sqlalchemy.exc import IntegrityError

    enforce_rate_limit(f"register:{client_ip(request)}", limit=5, window_sec=60)
    if db.query(Organization).filter(Organization.slug == body.slug).first():
        raise HTTPException(400, "Organization slug already taken")
    currency = (body.currency or "IDR").strip().upper() or "IDR"
    org = Organization(name=body.name, slug=body.slug, currency=currency)
    db.add(org)
    db.flush()
    owner = User(
        organization_id=org.id,
        email=body.owner_email.lower(),
        full_name=body.owner_name,
        hashed_password=hash_password(body.owner_password),
        role=UserRole.owner,
    )
    db.add(owner)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(400, "Organization slug already taken") from None
    db.refresh(owner)
    return _token_out(db, owner)


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = client_ip(request)
    enforce_rate_limit(f"login:{ip}", limit=20, window_sec=60)
    slug = (body.organization_slug or "").strip().lower()
    email = (body.email or "").strip().lower()
    enforce_rate_limit(f"login-acct:{slug}:{email}", limit=10, window_sec=60)
    return _authenticate_login(body, db)


def _authenticate_login(body: LoginIn, db: Session) -> TokenOut:
    org = db.query(Organization).filter(Organization.slug == body.organization_slug).first()
    if not org:
        raise HTTPException(401, "Invalid credentials")
    user = (
        db.query(User)
        .filter(User.organization_id == org.id, User.email == body.email.lower())
        .first()
    )
    if not user or not user.is_active:
        raise HTTPException(401, "Invalid credentials")
    if getattr(user, "must_set_password", False):
        raise HTTPException(401, "Accept invite first — set your password with the invite token")
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    return _token_out(db, user)


@router.post("/auth/login-form", response_model=TokenOut)
def login_form(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """OAuth2 password form: username = email@@organization-slug."""
    ip = client_ip(request)
    enforce_rate_limit(f"login:{ip}", limit=20, window_sec=60)
    raw = form.username or ""
    if "@@" not in raw:
        raise HTTPException(400, "Use username format: email@@organization-slug")
    email, slug = raw.rsplit("@@", 1)
    enforce_rate_limit(
        f"login-acct:{(slug or '').strip().lower()}:{(email or '').strip().lower()}",
        limit=10,
        window_sec=60,
    )
    return _authenticate_login(
        LoginIn(email=email, password=form.password, organization_slug=slug),
        db,
    )


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/auth/password", response_model=TokenOut)
def change_password(
    body: PasswordChangeIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    enforce_rate_limit(
        f"password:{user.id}:{client_ip(request)}",
        limit=10,
        window_sec=300,
    )
    locked = db.query(User).filter(User.id == user.id).with_for_update().first()
    if not locked:
        raise HTTPException(404, "User not found")
    if not verify_password(body.current_password, locked.hashed_password):
        raise HTTPException(400, "Current password is wrong")
    locked.hashed_password = hash_password(body.new_password)
    bump_token_version(locked)
    locked.must_set_password = False
    locked.invite_token = None
    locked.invite_token_expires_at = None
    db.commit()
    db.refresh(locked)
    return _token_out(db, locked)


@router.post("/auth/accept-invite", response_model=TokenOut)
def accept_invite(body: AcceptInviteIn, request: Request, db: Session = Depends(get_db)):
    from app.services.invite_tokens import find_user_by_invite_token, hash_invite_token

    enforce_rate_limit(f"accept-invite:{client_ip(request)}", limit=15, window_sec=60)
    token = body.token.strip()
    digest = hash_invite_token(token)
    enforce_rate_limit(f"accept-invite-tok:{digest[:16]}", limit=10, window_sec=60)
    found = find_user_by_invite_token(db, token)
    if not found:
        raise HTTPException(400, "Invalid or expired invite token")
    # Lock row so concurrent accepts cannot both succeed
    user = (
        db.query(User)
        .filter(User.id == found.id, User.organization_id == found.organization_id)
        .with_for_update()
        .first()
    )
    if not user or not user.is_active or not getattr(user, "must_set_password", False):
        raise HTTPException(400, "Invalid or expired invite token")
    stored = user.invite_token or ""
    if stored != digest and stored != token:
        raise HTTPException(400, "Invalid or expired invite token")
    expires = getattr(user, "invite_token_expires_at", None)
    if expires is not None and expires < _utcnow():
        user.invite_token = None
        user.invite_token_expires_at = None
        db.commit()
        raise HTTPException(400, "Invalid or expired invite token")
    user.hashed_password = hash_password(body.password)
    user.must_set_password = False
    user.invite_token = None
    user.invite_token_expires_at = None
    bump_token_version(user)
    db.commit()
    db.refresh(user)
    return _token_out(db, user)


@router.get("/orgs/me", response_model=OrgOut)
def my_org(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = db.get(Organization, user.organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    return _org_out(db, org)


@router.patch("/orgs/me", response_model=OrgOut)
def update_org(
    body: OrgUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner)),
):
    from app.services.locks import lock_organization

    org = lock_organization(db, user.organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        org.name = data["name"].strip()
    if "currency" in data and data["currency"] is not None:
        new_currency = data["currency"].strip().upper()
        if not new_currency:
            raise HTTPException(400, "currency is required")
        if new_currency != org.currency:
            if _currency_locked(db, org.id):
                raise HTTPException(
                    400,
                    "Currency cannot change after money activity exists",
                )
            org.currency = new_currency
    db.commit()
    db.refresh(org)
    return _org_out(db, org)


@router.post("/orgs/invite", response_model=InviteOut)
def invite_user(
    body: InviteIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    enforce_rate_limit(f"invite:{user.organization_id}:{user.id}", limit=30, window_sec=60)
    exists = (
        db.query(User)
        .filter(User.organization_id == user.organization_id, User.email == body.email.lower())
        .first()
    )
    if exists:
        if not exists.is_active:
            raise HTTPException(
                400,
                "User is inactive — reactivate them in Team instead of inviting again",
            )
        raise HTTPException(400, "User already in organization")
    if body.role == UserRole.owner and user.role != UserRole.owner:
        raise HTTPException(403, "Only owner can invite owner")
    if user.role == UserRole.manager and body.role != UserRole.employee:
        raise HTTPException(403, "Managers can only invite employees")
    org = db.get(Organization, user.organization_id)
    invite_token: str | None = None
    raw_invite: str | None = None
    must_set = False
    invite_expires = None
    if body.password:
        hashed = hash_password(body.password)
    else:
        # Unusable random hash; teammate sets password via accept-invite
        from app.services.invite_tokens import store_invite_token

        hashed = hash_password(secrets.token_urlsafe(24))
        raw_invite = secrets.token_urlsafe(24)
        invite_token = store_invite_token(raw_invite)
        must_set = True
        invite_expires = _invite_expiry()
    invited = User(
        organization_id=user.organization_id,
        email=body.email.lower(),
        full_name=body.full_name,
        hashed_password=hashed,
        role=body.role,
        invite_token=invite_token,
        invite_token_expires_at=invite_expires,
        must_set_password=must_set,
    )
    db.add(invited)
    try:
        db.commit()
    except Exception as exc:
        from sqlalchemy.exc import IntegrityError

        db.rollback()
        if isinstance(exc, IntegrityError):
            raise HTTPException(400, "User already in organization") from None
        raise
    db.refresh(invited)
    emailed = False
    if org:
        from app.services.email import send_invite_email
        from app.services.notify import notify_org

        emailed = send_invite_email(
            to=invited.email,
            full_name=invited.full_name,
            org_name=org.name,
            org_slug=org.slug,
            invite_token=raw_invite,
            temp_password=bool(body.password),
        )
        notify_org(
            org,
            f"Fos: invited {invited.full_name} ({invited.email}) as {invited.role.value}",
        )
    return InviteOut(
        id=invited.id,
        email=invited.email,
        full_name=invited.full_name,
        role=invited.role,
        organization_id=invited.organization_id,
        organization_slug=org.slug if org else "",
        must_set_password=must_set,
        invite_token=raw_invite,
        email_sent=emailed,
    )
