"""Colleague cash transfer — RJ-inspired, multi-tenant SQL.

Creates paired expense (sender, cash_on_hand) + income (recipient, cash).
Peer transfers are auto-approved so cash balances move immediately; they
remain visible in the org ledger and share transfer_group_id for atomic void.
"""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import MoneyRecord, Organization, RecordKind, RecordStatus, User
from app.schemas import RecordOut
from app.routers.records import _record_out, _utcnow
from app.services.balances import user_balance
from app.services.idempotency import (
    commit_or_replay,
    fingerprint,
    lookup_idem,
    normalize_idem_key,
    require_idem_match,
    store_idem,
)
from app.services.money import require_positive_money

router = APIRouter(prefix="/transfers", tags=["transfers"])


class TransferIn(BaseModel):
    to_email: EmailStr
    amount: float = Field(gt=0)
    comment: str = Field(default="", max_length=2000)

    @field_validator("comment")
    @classmethod
    def strip_comment(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("amount")
    @classmethod
    def amount_finite(cls, v: float) -> float:
        try:
            return require_positive_money(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class TransferOut(BaseModel):
    sender_record: RecordOut
    recipient_record: RecordOut
    transfer_group_id: str


@router.post("", response_model=TransferOut)
def create_transfer(
    body: TransferIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    key = normalize_idem_key(idempotency_key)
    fp = fingerprint(body.model_dump(mode="json")) if key else None
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="transfers.create",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            sender = db.get(MoneyRecord, hit.resource_id)
            recipient_rec = db.get(MoneyRecord, hit.secondary_id) if hit.secondary_id else None
            if (
                sender
                and recipient_rec
                and sender.organization_id == user.organization_id
                and recipient_rec.organization_id == user.organization_id
            ):
                return TransferOut(
                    sender_record=_record_out(db, sender),
                    recipient_record=_record_out(db, recipient_rec),
                    transfer_group_id=sender.transfer_group_id or "",
                )

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

    from app.services.locks import lock_users

    lock_users(db, user.id, recipient.id)

    try:
        amount = require_positive_money(body.amount)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    bal = user_balance(db, user)
    held = float(bal.get("cash_on_hand") or 0)
    reserved = float(bal.get("reserved_cash") or 0)
    available = float(
        bal.get("available_cash")
        if bal.get("available_cash") is not None
        else max(0.0, held - reserved)
    )
    if amount > available + 1e-6:
        raise HTTPException(
            400,
            f"Only {available} available to transfer "
            f"({held} held, {reserved} reserved by pending requests).",
        )

    org = db.get(Organization, user.organization_id)
    currency = org.currency if org else "IDR"
    note = body.comment or f"Cash transfer to {recipient.full_name}"
    now = _utcnow()
    group_id = uuid.uuid4().hex[:16]

    sender_rec = MoneyRecord(
        organization_id=user.organization_id,
        created_by=user.id,
        kind=RecordKind.expense,
        status=RecordStatus.approved,
        amount=amount,
        currency=currency,
        category="Transfer",
        purpose="Other",
        comment=note,
        payment_source="cash_on_hand",
        decided_at=now,
        decided_by=user.id,
        occurred_at=now,
        transfer_group_id=group_id,
    )
    recipient_rec = MoneyRecord(
        organization_id=user.organization_id,
        created_by=recipient.id,
        kind=RecordKind.income,
        status=RecordStatus.approved,
        amount=amount,
        currency=currency,
        category="Transfer",
        purpose="Other",
        comment=f"Cash from {user.full_name}" + (f" — {body.comment}" if body.comment else ""),
        client_name=user.full_name,
        payment_method="cash",
        decided_at=now,
        decided_by=user.id,
        occurred_at=now,
        transfer_group_id=group_id,
    )
    db.add(sender_rec)
    db.add(recipient_rec)
    db.flush()
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="transfers.create",
            key=key,
            resource_id=sender_rec.id,
            secondary_id=recipient_rec.id,
            request_hash=fp,
        )
    replay = commit_or_replay(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        scope="transfers.create",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            TransferOut(
                sender_record=_record_out(db, sender),
                recipient_record=_record_out(db, recipient_row),
                transfer_group_id=sender.transfer_group_id or "",
            )
            if (sender := db.get(MoneyRecord, hit.resource_id))
            and (recipient_row := db.get(MoneyRecord, hit.secondary_id) if hit.secondary_id else None)
            and sender.organization_id == user.organization_id
            and recipient_row.organization_id == user.organization_id
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(sender_rec)
    db.refresh(recipient_rec)
    return TransferOut(
        sender_record=_record_out(db, sender_rec),
        recipient_record=_record_out(db, recipient_rec),
        transfer_group_id=group_id,
    )
