from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.auth import (
    create_access_token, get_current_user, hash_password, require_roles, verify_password,
)
from app.db import get_db
from app.models import BalanceAdjustment, MoneyRecord, Organization, Payout, User, UserRole
from app.schemas import InviteIn, LoginIn, OrgCreate, OrgOut, OrgUpdate, PasswordChangeIn, TokenOut, UserOut

router = APIRouter(tags=["auth"])


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


@router.post("/orgs/register", response_model=TokenOut)
def register_organization(body: OrgCreate, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(owner)
    token = create_access_token(owner.id, org.id, owner.role.value)
    return TokenOut(access_token=token, user=UserOut.model_validate(owner))


@router.post("/auth/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)):
    org = db.query(Organization).filter(Organization.slug == body.organization_slug).first()
    if not org:
        raise HTTPException(401, "Invalid credentials")
    user = (
        db.query(User)
        .filter(User.organization_id == org.id, User.email == body.email.lower())
        .first()
    )
    if not user or not user.is_active or not verify_password(body.password, user.hashed_password):
        raise HTTPException(401, "Invalid credentials")
    token = create_access_token(user.id, org.id, user.role.value)
    return TokenOut(access_token=token, user=UserOut.model_validate(user))


@router.post("/auth/login-form", response_model=TokenOut)
def login_form(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """OAuth2 password form: username = email@@organization-slug."""
    raw = form.username or ""
    if "@@" not in raw:
        raise HTTPException(400, "Use username format: email@@organization-slug")
    email, slug = raw.rsplit("@@", 1)
    return login(LoginIn(email=email, password=form.password, organization_slug=slug), db)


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut.model_validate(user)


@router.post("/auth/password")
def change_password(
    body: PasswordChangeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(400, "Current password is wrong")
    user.hashed_password = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


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
    org = db.get(Organization, user.organization_id)
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


@router.post("/orgs/invite", response_model=UserOut)
def invite_user(
    body: InviteIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    exists = (
        db.query(User)
        .filter(User.organization_id == user.organization_id, User.email == body.email.lower())
        .first()
    )
    if exists:
        raise HTTPException(400, "User already in organization")
    if body.role == UserRole.owner and user.role != UserRole.owner:
        raise HTTPException(403, "Only owner can invite owner")
    invited = User(
        organization_id=user.organization_id,
        email=body.email.lower(),
        full_name=body.full_name,
        hashed_password=hash_password(body.password),
        role=body.role,
    )
    db.add(invited)
    db.commit()
    db.refresh(invited)
    return UserOut.model_validate(invited)
