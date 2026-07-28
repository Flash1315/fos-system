from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.config import settings
from app.db import get_db
from app.models import Organization, User, UserRole
from app.services.notify import notify_org, telegram_configured

router = APIRouter(tags=["billing"])


class BillingOut(BaseModel):
    plan: str
    billing_status: str
    currency: str
    organization_slug: str
    telegram_configured: bool
    telegram_chat_id: str
    email_configured: bool
    media_backend: str


class TelegramChatIn(BaseModel):
    telegram_chat_id: str = Field(max_length=64)


class PlanIn(BaseModel):
    plan: str = Field(pattern=r"^(free|trial|pro)$")


@router.get("/billing/me", response_model=BillingOut)
def billing_me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    org = db.get(Organization, user.organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    from app.services.email import email_configured
    from app.services.storage import media_backend

    return BillingOut(
        plan=getattr(org, "plan", None) or "free",
        billing_status=getattr(org, "billing_status", None) or "ok",
        currency=org.currency,
        organization_slug=org.slug,
        telegram_configured=telegram_configured(),
        telegram_chat_id=getattr(org, "telegram_chat_id", "") or "",
        email_configured=email_configured(),
        media_backend=media_backend(),
    )


@router.post("/billing/plan", response_model=BillingOut)
def set_plan(
    body: PlanIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner)),
):
    """Stub plan switch — disabled unless BILLING_PLAN_SWITCH=1.

    Even with the flag on, paid `pro` is refused until real billing exists.
    """
    if not settings.billing_plan_switch:
        raise HTTPException(
            400,
            "Plan changes are disabled until billing is enabled (set BILLING_PLAN_SWITCH=1)",
        )
    if body.plan == "pro":
        raise HTTPException(
            400,
            "Paid plans require billing integration — only free/trial available in stub mode",
        )
    org = db.get(Organization, user.organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    org.plan = body.plan
    db.commit()
    db.refresh(org)
    return billing_me(user, db)


@router.post("/integrations/telegram/chat", response_model=BillingOut)
def set_telegram_chat(
    body: TelegramChatIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner)),
):
    org = db.get(Organization, user.organization_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    org.telegram_chat_id = body.telegram_chat_id.strip()
    db.commit()
    db.refresh(org)
    return billing_me(user, db)


@router.post("/integrations/telegram/test")
def test_telegram(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"telegram-test:{user.organization_id}:{user.id}",
        limit=5,
        window_sec=60,
    )
    if not telegram_configured():
        raise HTTPException(400, "TELEGRAM_BOT_TOKEN is not configured on the server")
    org = db.get(Organization, user.organization_id)
    if not org or not (org.telegram_chat_id or "").strip():
        raise HTTPException(400, "Set telegram_chat_id first")
    ok = notify_org(org, f"Fos test from {org.name} (/{org.slug}) — ok")
    if not ok:
        raise HTTPException(502, "Telegram API call failed")
    return {"ok": True}
