"""Colleague cash transfer — RJ-inspired, multi-tenant SQL.

Creates:
- pending expense (payment_source=cash_on_hand) for sender, category Transfer
- pending income (payment_method=cash) for recipient
Both still go through approval unless caller is owner/manager and auto flag set later.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import MoneyRecord, Organization, RecordKind, RecordStatus, User
from app.schemas import RecordOut
from app.routers.records import _record_out

router = APIRouter(prefix="/transfers", tags=["transfers"])


class TransferIn(BaseModel):
    to_email: EmailStr
    amount: float = Field(gt=0)
    comment: str = ""


class TransferOut(BaseModel):
    sender_record: RecordOut
    recipient_record: RecordOut


@router.post("", response_model=TransferOut)
def create_transfer(
    body: TransferIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    recipient = (
        db.query(User)
        .filter(
            User.organization_id == user.organization_id,
            User.email == body.to_email.lower(),
            User.is_active.is_(True),
        )
        .first()
    )
    if not recipient:
        raise HTTPException(404, "Recipient not found in your organization")
    if recipient.id == user.id:
        raise HTTPException(400, "Cannot transfer to yourself")

    org = db.get(Organization, user.organization_id)
    currency = org.currency if org else "IDR"
    note = body.comment or f"Cash transfer to {recipient.full_name}"

    sender_rec = MoneyRecord(
        organization_id=user.organization_id,
        created_by=user.id,
        kind=RecordKind.expense,
        status=RecordStatus.pending,
        amount=body.amount,
        currency=currency,
        category="Transfer",
        purpose="Other",
        comment=note,
        payment_source="cash_on_hand",
    )
    recipient_rec = MoneyRecord(
        organization_id=user.organization_id,
        created_by=recipient.id,
        kind=RecordKind.income,
        status=RecordStatus.pending,
        amount=body.amount,
        currency=currency,
        category="Transfer",
        purpose="Other",
        comment=f"Cash from {user.full_name}" + (f" — {body.comment}" if body.comment else ""),
        client_name=user.full_name,
        payment_method="cash",
    )
    db.add(sender_rec)
    db.add(recipient_rec)
    db.commit()
    db.refresh(sender_rec)
    db.refresh(recipient_rec)
    print(f"transfer org={user.organization_id} from={user.id} to={recipient.id} amount={body.amount}")
    return TransferOut(
        sender_record=_record_out(db, sender_rec),
        recipient_record=_record_out(db, recipient_rec),
    )
