from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Body, Header, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_roles
from app.categories import PAYMENT_METHODS
from app.db import get_db
from app.models import (
    Organization,
    Payout,
    PayoutKind,
    SettlementRequest,
    SettlementRequestStatus,
    User,
    UserRole,
)
from app.routers.records import _append_text, _utcnow
from app.schemas import _collapse_ws
from app.services.balances import last_payout, pending_reserved, user_balance

router = APIRouter(prefix="/payouts", tags=["payouts"])


class PayoutCreate(BaseModel):
    """Create body — overpayment is computed server-side; clients must not send it."""

    model_config = ConfigDict(extra="forbid")

    user_id: int
    kind: PayoutKind
    amount: float = Field(gt=0)
    payment_method: str = "cash"
    note: str = Field(default="", max_length=2000)

    @field_validator("payment_method")
    @classmethod
    def payment_method_norm(cls, v: str) -> str:
        return (v or "cash").strip().lower() or "cash"

    @field_validator("note")
    @classmethod
    def note_trim(cls, v: str) -> str:
        return _collapse_ws(v, max_len=2000)

    @field_validator("amount")
    @classmethod
    def amount_finite(cls, v: float) -> float:
        from app.services.money import require_positive_money

        try:
            return require_positive_money(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class PayoutOut(BaseModel):
    id: int
    user_id: int
    user_name: str = ""
    kind: PayoutKind
    amount: float
    currency: str
    payment_method: str
    note: str
    overpayment: float = 0.0
    balance_after: float = 0.0
    is_voided: bool = False
    voided_at: datetime | None = None
    void_note: str = ""
    can_void: bool = False
    void_blocked_reason: str | None = None
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


class VoidIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def note_trimmed(cls, v: str) -> str:
        note = _collapse_ws(v, max_len=2000)
        if len(note) < 2:
            raise ValueError("Note is required (min 2 characters)")
        return note


class CancelRequestIn(BaseModel):
    note: str = Field(default="", max_length=2000)

    @field_validator("note")
    @classmethod
    def note_trim(cls, v: str) -> str:
        return _collapse_ws(v, max_len=2000)


class SettlementRequestIn(BaseModel):
    kind: PayoutKind
    amount: float = Field(gt=0)
    note: str = Field(default="", max_length=2000)

    @field_validator("note")
    @classmethod
    def note_trim(cls, v: str) -> str:
        return _collapse_ws(v, max_len=2000)

    @field_validator("amount")
    @classmethod
    def amount_finite(cls, v: float) -> float:
        from app.services.money import require_positive_money

        try:
            return require_positive_money(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc


class SettlementRequestOut(BaseModel):
    id: int
    user_id: int
    user_name: str = ""
    kind: PayoutKind
    amount: float
    note: str
    status: SettlementRequestStatus
    created_at: datetime
    settled_amount: float | None = None
    payout_id: int | None = None

    model_config = {"from_attributes": True}


def _can_void_payout(db: Session, row: Payout) -> bool:
    if row.is_voided:
        return False
    latest = last_payout(db, row.organization_id, row.user_id, row.kind)
    return latest is not None and latest.id == row.id


def _payout_void_blocked_reason(db: Session, row: Payout) -> str | None:
    if row.is_voided or _can_void_payout(db, row):
        return None
    return "Only the latest settlement of this kind can be voided."


def _payout_out(db: Session, row: Payout, user_name: str) -> PayoutOut:
    return PayoutOut(
        id=row.id,
        user_id=row.user_id,
        user_name=user_name,
        kind=row.kind,
        amount=row.amount,
        currency=row.currency,
        payment_method=row.payment_method,
        note=row.note,
        overpayment=float(row.overpayment or 0),
        balance_after=float(row.balance_after or 0),
        is_voided=bool(row.is_voided),
        voided_at=row.voided_at,
        void_note=row.void_note or "",
        can_void=_can_void_payout(db, row),
        void_blocked_reason=_payout_void_blocked_reason(db, row),
        created_by=row.created_by,
        created_at=row.created_at,
    )


def _request_out(row: SettlementRequest, user_name: str) -> SettlementRequestOut:
    return SettlementRequestOut(
        id=row.id,
        user_id=row.user_id,
        user_name=user_name,
        kind=row.kind,
        amount=row.amount,
        note=row.note,
        status=row.status,
        created_at=row.created_at,
        settled_amount=row.settled_amount,
        payout_id=row.payout_id,
    )


def _create_payout_row(
    body: PayoutCreate,
    db: Session,
    manager: User,
    *,
    exclude_request_id: int | None = None,
) -> tuple[Payout, User]:
    """Build a payout row and flush (no commit) so callers can batch atomically.

    Direct/batch settlements cannot eat amounts reserved by pending settlement
    requests. Approving a request passes exclude_request_id so its own reserve
    does not block itself.
    """
    from app.services.money import require_positive_money, round_money
    from app.services.locks import lock_users
    from app.services.org_gates import require_member_ready, require_org_writable

    require_org_writable(db, manager.organization_id)
    target = db.get(User, body.user_id)
    if not target or target.organization_id != manager.organization_id:
        raise HTTPException(404, "User not found")
    require_member_ready(target, action="settlement")
    lock_users(db, target.id)
    org = db.get(Organization, manager.organization_id)
    bal = user_balance(db, target)
    method = (body.payment_method or "cash").strip().lower()
    if method not in PAYMENT_METHODS:
        raise HTTPException(400, f"payment_method must be one of {PAYMENT_METHODS}")
    try:
        amount = require_positive_money(body.amount)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    overpayment = 0.0
    balance_after = 0.0
    if body.kind == PayoutKind.expense_payout:
        owed = float(bal.get("spendings") or 0)
        credit = float(bal.get("remaining_overpayment_credit") or 0)
        reserved = pending_reserved(
            db, target.id, manager.organization_id, PayoutKind.expense_payout, exclude_request_id
        )
        available = max(0.0, owed - reserved)
        if amount > available + 1e-6:
            if reserved <= 1e-9 and amount > owed + 1e-6:
                # Preserve unused prior overpayment credit across payout cutoffs.
                overpayment = round_money(amount - owed + credit)
                balance_after = 0.0
            else:
                raise HTTPException(
                    400,
                    f"Only {available} available to pay "
                    f"({owed} owed, {reserved} reserved by pending requests).",
                )
        else:
            # owed > 0 implies prior credit was already consumed in balance calc.
            overpayment = round_money(credit) if owed <= 1e-9 else 0.0
            balance_after = round_money(max(0.0, owed - amount))
    elif body.kind == PayoutKind.income_handover:
        held = float(bal.get("cash_on_hand") or 0)
        reserved = pending_reserved(
            db, target.id, manager.organization_id, PayoutKind.income_handover, exclude_request_id
        )
        available = max(0.0, held - reserved)
        if amount > available + 1e-6:
            raise HTTPException(
                400,
                f"Only {available} available to take "
                f"({held} held, {reserved} reserved by pending requests).",
            )
        balance_after = round_money(max(0.0, held - amount))
        overpayment = 0.0
    row = Payout(
        organization_id=manager.organization_id,
        user_id=target.id,
        kind=body.kind,
        amount=amount,
        currency=org.currency if org else "IDR",
        payment_method=method,
        note=body.note,
        overpayment=overpayment,
        balance_after=balance_after,
        created_by=manager.id,
        created_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    return row, target


@router.post("", response_model=PayoutOut)
def create_payout(
    body: PayoutCreate,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"payout-create:{manager.organization_id}:{manager.id}",
        limit=60,
        window_sec=60,
    )

    key = normalize_idem_key(idempotency_key)
    fp = fingerprint(body.model_dump(mode="json")) if key else None
    if key:
        hit = lookup_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="payouts.create",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(Payout, hit.resource_id)
            if existing and existing.organization_id == manager.organization_id:
                u = db.get(User, existing.user_id)
                return _payout_out(db, existing, u.full_name if u else "")
    row, target = _create_payout_row(body, db, manager)
    if key:
        store_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="payouts.create",
            key=key,
            resource_id=row.id,
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=manager.organization_id,
        user_id=manager.id,
        scope="payouts.create",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            _payout_out(
                db,
                existing,
                (u.full_name if (u := db.get(User, existing.user_id)) else ""),
            )
            if (existing := db.get(Payout, hit.resource_id))
            and existing.organization_id == manager.organization_id
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(row)
    return _payout_out(db, row, target.full_name)


@router.get("/mine", response_model=list[PayoutOut])
def my_payouts(
    voided: bool | None = None,
    kind: PayoutKind | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"payouts-mine:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    q = db.query(Payout).filter(
        Payout.organization_id == user.organization_id, Payout.user_id == user.id
    )
    if voided is True:
        q = q.filter(Payout.is_voided.is_(True))
    elif voided is False:
        q = q.filter(Payout.is_voided.is_(False))
    if kind is not None:
        q = q.filter(Payout.kind == kind)
    rows = q.order_by(Payout.created_at.desc(), Payout.id.desc()).offset(offset).limit(limit).all()
    return [_payout_out(db, r, user.full_name) for r in rows]


@router.get("/org", response_model=list[PayoutOut])
def org_payouts(
    voided: bool | None = None,
    user_id: int | None = None,
    kind: PayoutKind | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"payouts-org:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    q = db.query(Payout).filter(Payout.organization_id == user.organization_id)
    if voided is True:
        q = q.filter(Payout.is_voided.is_(True))
    elif voided is False:
        q = q.filter(Payout.is_voided.is_(False))
    if user_id is not None:
        q = q.filter(Payout.user_id == user_id)
    if kind is not None:
        q = q.filter(Payout.kind == kind)
    rows = q.order_by(Payout.created_at.desc(), Payout.id.desc()).offset(offset).limit(limit).all()
    out = []
    for r in rows:
        u = db.get(User, r.user_id)
        out.append(_payout_out(db, r, u.full_name if u else ""))
    return out


@router.post("/{payout_id}/void", response_model=PayoutOut)
def void_payout(
    payout_id: int,
    body: VoidIn,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"payout-void:{manager.organization_id}:{manager.id}",
        limit=30,
        window_sec=60,
    )
    from app.services.org_gates import require_org_writable

    key = normalize_idem_key(idempotency_key)
    fp = (
        fingerprint({"payout_id": payout_id, **body.model_dump(mode="json")})
        if key
        else None
    )
    if key:
        hit = lookup_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="payouts.void",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(Payout, hit.resource_id)
            if existing and existing.organization_id == manager.organization_id:
                u = db.get(User, existing.user_id)
                return _payout_out(db, existing, u.full_name if u else "")
    require_org_writable(db, manager.organization_id)
    row = db.get(Payout, payout_id)
    if not row or row.organization_id != manager.organization_id:
        raise HTTPException(404, "Payout not found")
    if row.is_voided:
        u = db.get(User, row.user_id)
        return _payout_out(db, row, u.full_name if u else "")
    if not _can_void_payout(db, row):
        raise HTTPException(
            400,
            "Only the latest settlement of this type for the teammate can be voided",
        )
    from app.services.locks import lock_users

    lock_users(db, row.user_id)
    row = (
        db.query(Payout)
        .filter(
            Payout.id == payout_id,
            Payout.organization_id == manager.organization_id,
        )
        .with_for_update()
        .first()
    )
    if not row or row.organization_id != manager.organization_id:
        raise HTTPException(404, "Payout not found")
    if row.is_voided:
        u = db.get(User, row.user_id)
        return _payout_out(db, row, u.full_name if u else "")
    if not _can_void_payout(db, row):
        raise HTTPException(
            400,
            "Only the latest settlement of this type for the teammate can be voided",
        )
    row.is_voided = True
    row.voided_at = _utcnow()
    row.voided_by = manager.id
    row.void_note = body.note
    linked = (
        db.query(SettlementRequest)
        .filter(
            SettlementRequest.organization_id == manager.organization_id,
            SettlementRequest.payout_id == row.id,
        )
        .with_for_update()
        .first()
    )
    if linked is not None:
        db.flush()
        target = db.get(User, row.user_id)
        reopen = bool(target and target.is_active)
        if reopen and target:
            bal = user_balance(db, target)
            if row.kind == PayoutKind.expense_payout:
                track = float(bal.get("spendings") or 0)
                reserved = float(bal.get("reserved_spendings") or 0)
                available = float(
                    bal.get("available_spendings")
                    if bal.get("available_spendings") is not None
                    else max(0.0, track - reserved)
                )
            else:
                track = float(bal.get("cash_on_hand") or 0)
                reserved = float(bal.get("reserved_cash") or 0)
                available = float(
                    bal.get("available_cash")
                    if bal.get("available_cash") is not None
                    else max(0.0, track - reserved)
                )
            if float(linked.amount) > available + 1e-6:
                reopen = False
        if reopen:
            linked.status = SettlementRequestStatus.pending
            linked.decided_at = None
            linked.decided_by = None
            linked.settled_amount = None
            linked.payout_id = None
            linked.note = _append_text(
                linked.note, f"[reopened after payout void] {body.note}", label="Note"
            )
        else:
            reason = (
                "teammate inactive or missing"
                if not target or not target.is_active
                else "amount no longer fits available"
            )
            linked.status = SettlementRequestStatus.cancelled
            linked.decided_at = _utcnow()
            linked.decided_by = manager.id
            linked.settled_amount = None
            linked.payout_id = None
            linked.note = _append_text(
                linked.note,
                f"[cancelled after payout void — {reason}] {body.note}",
                label="Note",
            )
    if key:
        store_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="payouts.void",
            key=key,
            resource_id=row.id,
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=manager.organization_id,
        user_id=manager.id,
        scope="payouts.void",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            _payout_out(
                db,
                existing,
                (u.full_name if (u := db.get(User, existing.user_id)) else ""),
            )
            if (existing := db.get(Payout, hit.resource_id))
            and existing.organization_id == manager.organization_id
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(row)
    target = db.get(User, row.user_id)
    return _payout_out(db, row, target.full_name if target else "")


@router.post("/batch-spendings", response_model=list[PayoutOut])
def batch_pay_all_spendings(
    payment_method: str = "cash",
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Create expense_payout for every teammate with available spendings > 0 (one commit)."""
    from app.services.idempotency import (
        dumps_json,
        fingerprint,
        loads_json,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"payout-batch:{manager.organization_id}:{manager.id}",
        limit=10,
        window_sec=60,
    )
    from app.services.org_gates import require_org_writable

    method = (payment_method or "cash").strip().lower() or "cash"
    if method not in PAYMENT_METHODS:
        raise HTTPException(400, f"payment_method must be one of {PAYMENT_METHODS}")
    payment_method = method

    key = normalize_idem_key(idempotency_key)
    fp = fingerprint({"payment_method": payment_method}) if key else None
    if key:
        hit = lookup_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="payouts.batch_spendings",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            if hit.response_json:
                cached = loads_json(hit.response_json)
                if isinstance(cached, list):
                    return [PayoutOut.model_validate(item) for item in cached]
    require_org_writable(db, manager.organization_id)
    from app.services.org_limits import require_org_member_capacity

    require_org_member_capacity(db, manager.organization_id, active_only=True)
    members = (
        db.query(User)
        .filter(
            User.organization_id == manager.organization_id,
            User.is_active.is_(True),
            User.must_set_password.is_(False),
        )
        .all()
    )
    from app.services.locks import lock_users

    if members:
        lock_users(db, *[m.id for m in members])
    built: list[tuple[Payout, User]] = []
    for m in members:
        bal = user_balance(db, m)
        available = float(bal.get("available_spendings") or 0)
        if available <= 0:
            continue
        built.append(
            _create_payout_row(
                PayoutCreate(
                    user_id=m.id,
                    kind=PayoutKind.expense_payout,
                    amount=available,
                    payment_method=payment_method,
                    note="batch pay available spendings",
                ),
                db=db,
                manager=manager,
            )
        )
    out: list[PayoutOut] = []
    for row, target in built:
        db.refresh(row)
        out.append(_payout_out(db, row, target.full_name))
    if key:
        store_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="payouts.batch_spendings",
            key=key,
            resource_id=out[0].id if out else 0,
            response_json=dumps_json([o.model_dump(mode="json") for o in out]),
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=manager.organization_id,
        user_id=manager.id,
        scope="payouts.batch_spendings",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            [PayoutOut.model_validate(item) for item in cached]
            if hit.response_json
            and isinstance((cached := loads_json(hit.response_json)), list)
            else None
        ),
    )
    if replay is not None:
        return replay
    return out


@router.post("/batch-cash", response_model=list[PayoutOut])
def batch_take_all_cash(
    payment_method: str = "cash",
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    """Create income_handover for every teammate with available cash > 0 (one commit)."""
    from app.services.idempotency import (
        dumps_json,
        fingerprint,
        loads_json,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"payout-batch:{manager.organization_id}:{manager.id}",
        limit=10,
        window_sec=60,
    )
    from app.services.org_gates import require_org_writable

    method = (payment_method or "cash").strip().lower() or "cash"
    if method not in PAYMENT_METHODS:
        raise HTTPException(400, f"payment_method must be one of {PAYMENT_METHODS}")
    payment_method = method

    key = normalize_idem_key(idempotency_key)
    fp = fingerprint({"payment_method": payment_method}) if key else None
    if key:
        hit = lookup_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="payouts.batch_cash",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            if hit.response_json:
                cached = loads_json(hit.response_json)
                if isinstance(cached, list):
                    return [PayoutOut.model_validate(item) for item in cached]
    require_org_writable(db, manager.organization_id)
    from app.services.org_limits import require_org_member_capacity

    require_org_member_capacity(db, manager.organization_id, active_only=True)
    members = (
        db.query(User)
        .filter(
            User.organization_id == manager.organization_id,
            User.is_active.is_(True),
            User.must_set_password.is_(False),
        )
        .all()
    )
    from app.services.locks import lock_users

    if members:
        lock_users(db, *[m.id for m in members])
    built: list[tuple[Payout, User]] = []
    for m in members:
        bal = user_balance(db, m)
        available = float(bal.get("available_cash") or 0)
        if available <= 0:
            continue
        built.append(
            _create_payout_row(
                PayoutCreate(
                    user_id=m.id,
                    kind=PayoutKind.income_handover,
                    amount=available,
                    payment_method=payment_method,
                    note="batch take available cash on hand",
                ),
                db=db,
                manager=manager,
            )
        )
    out: list[PayoutOut] = []
    for row, target in built:
        db.refresh(row)
        out.append(_payout_out(db, row, target.full_name))
    if key:
        store_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="payouts.batch_cash",
            key=key,
            resource_id=out[0].id if out else 0,
            response_json=dumps_json([o.model_dump(mode="json") for o in out]),
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=manager.organization_id,
        user_id=manager.id,
        scope="payouts.batch_cash",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            [PayoutOut.model_validate(item) for item in cached]
            if hit.response_json
            and isinstance((cached := loads_json(hit.response_json)), list)
            else None
        ),
    )
    if replay is not None:
        return replay
    return out


@router.get("/requests/mine", response_model=list[SettlementRequestOut])
def my_settlement_requests(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"settle-mine:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    q = db.query(SettlementRequest).filter(
        SettlementRequest.organization_id == user.organization_id,
        SettlementRequest.user_id == user.id,
    )
    if status and status != "all":
        try:
            st = SettlementRequestStatus(status)
        except ValueError as exc:
            raise HTTPException(400, "Invalid status") from exc
        q = q.filter(SettlementRequest.status == st)
    rows = (
        q.order_by(SettlementRequest.created_at.desc(), SettlementRequest.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_request_out(r, user.full_name) for r in rows]


@router.get("/requests/mine/pending/count")
def my_pending_settlement_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from sqlalchemy import func

    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"settle-mine-count:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    count = (
        db.query(func.count(SettlementRequest.id))
        .filter(
            SettlementRequest.organization_id == user.organization_id,
            SettlementRequest.user_id == user.id,
            SettlementRequest.status == SettlementRequestStatus.pending,
        )
        .scalar()
    )
    return {"count": int(count or 0)}


@router.post("/requests", response_model=SettlementRequestOut)
def request_settlement(
    body: SettlementRequestIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.money import require_positive_money
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"settle-request:{user.organization_id}:{user.id}",
        limit=30,
        window_sec=60,
    )
    from app.services.org_gates import require_org_writable

    key = normalize_idem_key(idempotency_key)
    fp = fingerprint(body.model_dump(mode="json")) if key else None
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="payouts.request",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(SettlementRequest, hit.resource_id)
            if existing and existing.organization_id == user.organization_id:
                return _request_out(existing, user.full_name)

    require_org_writable(db, user.organization_id)
    try:
        amount = require_positive_money(body.amount)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    from app.services.locks import lock_users

    lock_users(db, user.id)
    bal = user_balance(db, user)
    if body.kind == PayoutKind.expense_payout:
        available = float(bal.get("spendings") or 0)
        label = "spendings owed"
    else:
        available = float(bal.get("cash_on_hand") or 0)
        label = "cash on hand"
    reserved = pending_reserved(db, user.id, user.organization_id, body.kind)
    open_to_request = max(0.0, available - reserved)
    if amount > open_to_request + 1e-6:
        raise HTTPException(
            400,
            f"Request exceeds available {label} ({open_to_request}; "
            f"balance {available}, reserved by pending {reserved}).",
        )
    row = SettlementRequest(
        organization_id=user.organization_id,
        user_id=user.id,
        kind=body.kind,
        amount=amount,
        note=body.note,
        status=SettlementRequestStatus.pending,
        created_at=_utcnow(),
    )
    db.add(row)
    db.flush()
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="payouts.request",
            key=key,
            resource_id=row.id,
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        scope="payouts.request",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            _request_out(existing, user.full_name)
            if (existing := db.get(SettlementRequest, hit.resource_id))
            and existing.organization_id == user.organization_id
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(row)
    return _request_out(row, user.full_name)


@router.get("/requests", response_model=list[SettlementRequestOut])
def list_settlement_requests(
    status: str | None = "pending",
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"settle-list:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    q = db.query(SettlementRequest).filter(
        SettlementRequest.organization_id == user.organization_id,
    )
    if status and status != "all":
        try:
            st = SettlementRequestStatus(status)
        except ValueError as exc:
            raise HTTPException(400, "Invalid status") from exc
        q = q.filter(SettlementRequest.status == st)
        if st == SettlementRequestStatus.pending:
            q = q.order_by(SettlementRequest.created_at.asc(), SettlementRequest.id.asc())
        else:
            q = q.order_by(SettlementRequest.created_at.desc(), SettlementRequest.id.desc())
    else:
        q = q.order_by(SettlementRequest.created_at.desc(), SettlementRequest.id.desc())
    rows = q.offset(offset).limit(limit).all()
    out = []
    for r in rows:
        u = db.get(User, r.user_id)
        out.append(_request_out(r, u.full_name if u else ""))
    return out


@router.get("/requests/pending/count")
def org_pending_settlement_count(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
):
    from sqlalchemy import func

    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"settle-org-count:{user.organization_id}:{user.id}",
        limit=120,
        window_sec=60,
    )
    count = (
        db.query(func.count(SettlementRequest.id))
        .filter(
            SettlementRequest.organization_id == user.organization_id,
            SettlementRequest.status == SettlementRequestStatus.pending,
        )
        .scalar()
    )
    return {"count": int(count or 0)}


class ApproveRequestIn(BaseModel):
    payment_method: str = "cash"

    @field_validator("payment_method")
    @classmethod
    def payment_method_norm(cls, v: str) -> str:
        return (v or "cash").strip().lower() or "cash"


@router.post("/requests/{request_id}/approve", response_model=PayoutOut)
def approve_settlement_request(
    request_id: int,
    body: ApproveRequestIn | None = Body(default=None),
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles(UserRole.owner, UserRole.manager)),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"settle-approve:{manager.organization_id}:{manager.id}",
        limit=60,
        window_sec=60,
    )
    from app.services.org_gates import require_org_writable

    key = normalize_idem_key(idempotency_key)
    method = ((body.payment_method if body else None) or "cash").strip().lower()
    fp = (
        fingerprint({"request_id": request_id, "payment_method": method})
        if key
        else None
    )
    if key:
        hit = lookup_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="payouts.approve_request",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(Payout, hit.resource_id)
            # Voided payouts must not short-circuit — request may have reopened.
            if (
                existing
                and existing.organization_id == manager.organization_id
                and not existing.is_voided
            ):
                u = db.get(User, existing.user_id)
                return _payout_out(db, existing, u.full_name if u else "")
            db.delete(hit)
            db.flush()
    require_org_writable(db, manager.organization_id)
    req = (
        db.query(SettlementRequest)
        .filter(
            SettlementRequest.id == request_id,
            SettlementRequest.organization_id == manager.organization_id,
        )
        .with_for_update()
        .first()
    )

    if not req or req.organization_id != manager.organization_id:
        raise HTTPException(404, "Request not found")
    if req.status != SettlementRequestStatus.pending:
        # Soft retry: already approved → return linked payout
        if (
            req.status == SettlementRequestStatus.approved
            and req.payout_id is not None
        ):
            existing = db.get(Payout, req.payout_id)
            if existing and existing.organization_id == manager.organization_id:
                u = db.get(User, existing.user_id)
                return _payout_out(db, existing, u.full_name if u else "")
        raise HTTPException(400, "Request already decided")
    target = db.get(User, req.user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if not target.is_active:
        raise HTTPException(400, "Cannot approve — teammate is inactive")
    if method not in PAYMENT_METHODS:
        raise HTTPException(400, f"payment_method must be one of {PAYMENT_METHODS}")
    from app.services.locks import lock_users

    lock_users(db, target.id)
    bal = user_balance(db, target)
    track = (
        float(bal.get("spendings") or 0)
        if req.kind == PayoutKind.expense_payout
        else float(bal.get("cash_on_hand") or 0)
    )
    reserved_others = pending_reserved(
        db, req.user_id, manager.organization_id, req.kind, exclude_id=req.id
    )
    available = max(0.0, track - reserved_others)
    if float(req.amount) > available + 1e-6:
        raise HTTPException(
            400,
            f"Balance is only {available} after other pending requests "
            f"(track {track}, reserved by others {reserved_others}); "
            f"cancel or reduce other activity, then retry (request is {req.amount}).",
        )
    amount = float(req.amount)
    row, target = _create_payout_row(
        PayoutCreate(
            user_id=req.user_id,
            kind=req.kind,
            amount=amount,
            payment_method=method,
            note=req.note or f"From request #{req.id}",
        ),
        db=db,
        manager=manager,
        exclude_request_id=req.id,
    )
    req.status = SettlementRequestStatus.approved
    req.decided_at = _utcnow()
    req.decided_by = manager.id
    req.settled_amount = amount
    req.payout_id = row.id
    if key:
        store_idem(
            db,
            organization_id=manager.organization_id,
            user_id=manager.id,
            scope="payouts.approve_request",
            key=key,
            resource_id=row.id,
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    replay = commit_or_replay(
        db,
        organization_id=manager.organization_id,
        user_id=manager.id,
        scope="payouts.approve_request",
        key=key,
        request_hash=fp,
        load_replay=lambda hit: (
            _payout_out(
                db,
                existing,
                (u.full_name if (u := db.get(User, existing.user_id)) else ""),
            )
            if (existing := db.get(Payout, hit.resource_id))
            and existing.organization_id == manager.organization_id
            and not existing.is_voided
            else None
        ),
    )
    if replay is not None:
        return replay
    db.refresh(row)
    return _payout_out(db, row, target.full_name)


@router.post("/requests/{request_id}/cancel", response_model=SettlementRequestOut)
def cancel_settlement_request(
    request_id: int,
    body: CancelRequestIn = CancelRequestIn(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    from app.services.idempotency import (
        fingerprint,
        lookup_idem,
        normalize_idem_key,
        require_idem_match,
        store_idem,
    )
    from app.services.rate_limit import enforce_rate_limit

    enforce_rate_limit(
        f"settle-cancel:{user.organization_id}:{user.id}",
        limit=60,
        window_sec=60,
    )
    # Cancel is allowed during billing freeze so reserved amounts can be released.

    key = normalize_idem_key(idempotency_key)
    fp = (
        fingerprint({"request_id": request_id, **body.model_dump(mode="json")})
        if key
        else None
    )
    if key:
        hit = lookup_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="payouts.cancel_request",
            key=key,
        )
        if hit:
            require_idem_match(hit, fp)
            existing = db.get(SettlementRequest, hit.resource_id)
            if existing and existing.organization_id == user.organization_id:
                is_manager = user.role in (UserRole.owner, UserRole.manager)
                if existing.user_id != user.id and not is_manager:
                    raise HTTPException(403, "Insufficient role")
                u = db.get(User, existing.user_id)
                return _request_out(existing, u.full_name if u else "")
    req = (
        db.query(SettlementRequest)
        .filter(
            SettlementRequest.id == request_id,
            SettlementRequest.organization_id == user.organization_id,
        )
        .with_for_update()
        .first()
    )
    if not req or req.organization_id != user.organization_id:
        raise HTTPException(404, "Request not found")
    is_manager = user.role in (UserRole.owner, UserRole.manager)
    if req.user_id != user.id and not is_manager:
        raise HTTPException(403, "Insufficient role")
    if req.status != SettlementRequestStatus.pending:
        if req.status == SettlementRequestStatus.cancelled:
            u = db.get(User, req.user_id)
            return _request_out(req, u.full_name if u else "")
        raise HTTPException(400, "Request already decided")
    # Manager cancelling someone else's request must leave a note
    if req.user_id != user.id and len(body.note or "") < 2:
        raise HTTPException(400, "Cancel requires a note (min 2 characters)")
    req.status = SettlementRequestStatus.cancelled
    req.decided_at = _utcnow()
    req.decided_by = user.id
    if body.note:
        req.note = _append_text(req.note, f"[cancelled] {body.note}", label="Note")
    if key:
        store_idem(
            db,
            organization_id=user.organization_id,
            user_id=user.id,
            scope="payouts.cancel_request",
            key=key,
            resource_id=req.id,
            request_hash=fp,
        )
    from app.services.idempotency import commit_or_replay

    def _load_cancel_replay(hit):
        existing = db.get(SettlementRequest, hit.resource_id)
        if not existing or existing.organization_id != user.organization_id:
            return None
        is_mgr = user.role in (UserRole.owner, UserRole.manager)
        if existing.user_id != user.id and not is_mgr:
            raise HTTPException(403, "Insufficient role")
        u = db.get(User, existing.user_id)
        return _request_out(existing, u.full_name if u else "")

    replay = commit_or_replay(
        db,
        organization_id=user.organization_id,
        user_id=user.id,
        scope="payouts.cancel_request",
        key=key,
        request_hash=fp,
        load_replay=_load_cancel_replay,
    )
    if replay is not None:
        return replay
    db.refresh(req)
    u = db.get(User, req.user_id)
    return _request_out(req, u.full_name if u else "")
