from datetime import datetime
from typing import Optional
import math
import re

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models import RecordKind, RecordStatus, UserRole


def _strip_optional(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    return v.strip()


_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")


def _normalize_email(v) -> str:
    return str(v or "").strip().lower()


def _require_strong_password(v: str) -> str:
    password = v or ""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters")
    if len(password) > 128:
        raise ValueError("Password too long (max 128)")
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        raise ValueError("Password must include a letter and a digit")
    return password


def _collapse_ws(v: str, *, max_len: int | None = None) -> str:
    raw = v or ""
    # Reject controls before whitespace collapse so VT/FF cannot vanish silently.
    if _CTRL_RE.search(raw):
        raise ValueError("contains invalid control characters")
    text = re.sub(r"\s+", " ", raw.strip())
    if max_len is not None:
        return text[:max_len]
    return text


def _require_finite(v: Optional[float], *, field: str) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise ValueError(f"{field} must be a finite number")
    return float(v)


class OrgCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    currency: str = "IDR"
    owner_email: EmailStr
    owner_name: str = Field(min_length=1, max_length=200)
    owner_password: str = Field(min_length=8, max_length=128)
    owner_password_confirm: str = Field(min_length=8, max_length=128)

    @field_validator("slug", mode="before")
    @classmethod
    def slug_norm(cls, v):
        return str(v or "").strip().lower()

    @field_validator("owner_email", mode="before")
    @classmethod
    def owner_email_norm(cls, v):
        return _normalize_email(v)

    @field_validator("owner_password", "owner_password_confirm")
    @classmethod
    def strong_owner_password(cls, v: str) -> str:
        return _require_strong_password(v)

    @field_validator("name", "owner_name")
    @classmethod
    def strip_required_name(cls, v: str) -> str:
        cleaned = _collapse_ws(v)
        if len(cleaned) < 2:
            raise ValueError("must be at least 2 characters")
        return cleaned

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, v: str) -> str:
        if v.startswith("-") or v.endswith("-") or "--" in v:
            raise ValueError("slug cannot start/end with a hyphen or contain --")
        return v

    @field_validator("currency")
    @classmethod
    def currency_code(cls, v: str) -> str:
        code = (v or "IDR").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise ValueError("currency must be a 3-letter code (e.g. IDR)")
        return code

    @model_validator(mode="after")
    def confirm_password(self):
        if self.owner_password_confirm != self.owner_password:
            raise ValueError("Passwords do not match")
        return self


class OrgOut(BaseModel):
    id: int
    name: str
    slug: str
    currency: str
    currency_locked: bool = False

    model_config = {"from_attributes": True}


class OrgUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    currency: Optional[str] = Field(default=None, min_length=1, max_length=8)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        cleaned = _collapse_ws(v)
        if len(cleaned) < 2:
            raise ValueError("must be at least 2 characters")
        return cleaned

    @field_validator("currency")
    @classmethod
    def currency_code(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        code = v.strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            raise ValueError("currency must be a 3-letter code (e.g. IDR)")
        return code


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    organization_id: int

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 0
    user: UserOut
    organization_slug: str = ""


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    organization_slug: str

    @field_validator("email", mode="before")
    @classmethod
    def email_norm(cls, v):
        return _normalize_email(v)

    @field_validator("organization_slug", mode="before")
    @classmethod
    def slug_norm(cls, v):
        slug = str(v or "").strip().lower()
        if len(slug) < 2 or len(slug) > 80:
            raise ValueError("organization_slug must be 2–80 characters")
        if not re.fullmatch(r"[a-z0-9-]+", slug):
            raise ValueError("organization_slug: lowercase letters, numbers, hyphens only")
        if slug.startswith("-") or slug.endswith("-") or "--" in slug:
            raise ValueError("organization_slug cannot start/end with a hyphen or contain --")
        return slug


class InviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    full_name: str = Field(min_length=1, max_length=200)
    role: UserRole = UserRole.employee
    # Optional: omit to generate a one-time invite token (preferred)
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    password_confirm: Optional[str] = Field(default=None, min_length=8, max_length=128)

    @field_validator("email", mode="before")
    @classmethod
    def email_norm(cls, v):
        return _normalize_email(v)

    @field_validator("password", "password_confirm")
    @classmethod
    def strong_temp_password(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _require_strong_password(v)

    @field_validator("full_name")
    @classmethod
    def strip_full_name(cls, v: str) -> str:
        cleaned = _collapse_ws(v)
        if len(cleaned) < 2:
            raise ValueError("must be at least 2 characters")
        return cleaned

    @model_validator(mode="after")
    def confirm_temp_password(self):
        if self.password is None:
            if self.password_confirm is not None:
                raise ValueError("password_confirm requires password")
            return self
        if self.password_confirm != self.password:
            raise ValueError("Passwords do not match")
        return self


class InviteOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    organization_id: int
    organization_slug: str = ""
    must_set_password: bool = False
    invite_token: Optional[str] = None
    email_sent: bool = False

    model_config = {"from_attributes": True}


class AcceptInviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=128)
    password: str = Field(min_length=8, max_length=128)
    password_confirm: str = Field(min_length=8, max_length=128)

    @field_validator("token", mode="before")
    @classmethod
    def token_strip(cls, v):
        token = str(v or "").strip()
        if token and not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError("invite token has invalid characters")
        return token

    @field_validator("password", "password_confirm")
    @classmethod
    def strong_password(cls, v: str) -> str:
        return _require_strong_password(v)

    @model_validator(mode="after")
    def confirm_matches(self):
        if self.password_confirm != self.password:
            raise ValueError("Passwords do not match")
        return self


class PasswordChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    password_confirm: str = Field(min_length=8, max_length=128)

    @field_validator("new_password", "password_confirm")
    @classmethod
    def strong_password(cls, v: str) -> str:
        return _require_strong_password(v)

    @model_validator(mode="after")
    def confirm_matches(self):
        if self.password_confirm != self.new_password:
            raise ValueError("Passwords do not match")
        if self.new_password == self.current_password:
            raise ValueError("New password must be different from current password")
        return self


class MemberPasswordResetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=8, max_length=128)
    password_confirm: str = Field(min_length=8, max_length=128)

    @field_validator("new_password", "password_confirm")
    @classmethod
    def strong_password(cls, v: str) -> str:
        return _require_strong_password(v)

    @model_validator(mode="after")
    def confirm_matches(self):
        if self.password_confirm != self.new_password:
            raise ValueError("Passwords do not match")
        return self


class MemberResetTokenOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    organization_slug: str
    invite_token: Optional[str] = None
    must_set_password: bool = True
    email_sent: bool = False


class RecordCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: RecordKind
    amount: float = Field(gt=0)
    category: str = Field(default="", max_length=120)
    purpose: str = Field(default="", max_length=80)
    place: str = Field(default="", max_length=200)
    bike: str = Field(default="", max_length=120)
    comment: str = Field(default="", max_length=4000)
    photo_url: str = Field(default="", max_length=500)
    liters: Optional[float] = Field(default=None, gt=0, le=10000)
    odometer: Optional[float] = Field(default=None, ge=0, le=9999999.99)
    client_name: str = Field(default="", max_length=200)
    payment_method: str = Field(default="", max_length=40)
    payment_source: str = Field(default="", max_length=40)
    # Manager can file on behalf of a teammate (balances attribute to them)
    created_for_user_id: Optional[int] = None
    # ISO datetime or date when money moved (optional; defaults to created_at)
    occurred_at: Optional[datetime] = None
    # Managers/owners can create already-approved (skip queue)
    approve_now: bool = False
    # Managers may explicitly approve into an already-settled cycle
    allow_closed_cycle: bool = False

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: float) -> float:
        from app.services.money import require_positive_money

        try:
            return require_positive_money(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator(
        "category",
        "purpose",
        "place",
        "bike",
        "photo_url",
        "client_name",
        "payment_method",
        "payment_source",
    )
    @classmethod
    def strip_text_fields(cls, v: str) -> str:
        return (v or "").strip()

    @field_validator("comment")
    @classmethod
    def collapse_comment(cls, v: str) -> str:
        return _collapse_ws(v, max_len=4000)

    @field_validator("liters")
    @classmethod
    def finite_liters(cls, v: Optional[float]) -> Optional[float]:
        return _require_finite(v, field="liters")

    @field_validator("odometer")
    @classmethod
    def finite_odometer(cls, v: Optional[float]) -> Optional[float]:
        return _require_finite(v, field="odometer")

    @model_validator(mode="after")
    def fuel_requires_liters(self):
        if self.kind == RecordKind.fuel and (self.liters is None or self.liters <= 0):
            raise ValueError("Fuel records require liters > 0")
        return self


class RecordUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Optional[float] = Field(default=None, gt=0)
    category: Optional[str] = Field(default=None, max_length=120)
    purpose: Optional[str] = Field(default=None, max_length=80)
    place: Optional[str] = Field(default=None, max_length=200)
    bike: Optional[str] = Field(default=None, max_length=120)
    comment: Optional[str] = Field(default=None, max_length=4000)
    photo_url: Optional[str] = Field(default=None, max_length=500)
    liters: Optional[float] = Field(default=None, gt=0, le=10000)
    odometer: Optional[float] = Field(default=None, ge=0, le=9999999.99)
    client_name: Optional[str] = Field(default=None, max_length=200)
    payment_method: Optional[str] = Field(default=None, max_length=40)
    payment_source: Optional[str] = Field(default=None, max_length=40)
    occurred_at: Optional[datetime] = None

    @field_validator("amount")
    @classmethod
    def positive_amount(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return v
        from app.services.money import require_positive_money

        try:
            return require_positive_money(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator(
        "category",
        "purpose",
        "place",
        "bike",
        "photo_url",
        "client_name",
        "payment_method",
        "payment_source",
    )
    @classmethod
    def strip_optional_text(cls, v: Optional[str]) -> Optional[str]:
        # Explicit JSON null → empty string so NOT NULL columns never 500.
        if v is None:
            return ""
        return v.strip()

    @field_validator("comment")
    @classmethod
    def collapse_optional_comment(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return ""
        return _collapse_ws(v, max_len=4000)

    @field_validator("liters")
    @classmethod
    def finite_liters(cls, v: Optional[float]) -> Optional[float]:
        return _require_finite(v, field="liters")

    @field_validator("odometer")
    @classmethod
    def finite_odometer(cls, v: Optional[float]) -> Optional[float]:
        return _require_finite(v, field="odometer")


class RecordOut(BaseModel):
    id: int
    kind: RecordKind
    status: RecordStatus
    amount: float
    currency: str
    category: str
    purpose: str = ""
    place: str = ""
    bike: str = ""
    comment: str
    photo_url: str
    liters: Optional[float]
    odometer: Optional[float]
    client_name: str
    payment_method: str
    payment_source: str = ""
    created_by: int
    created_by_name: str = ""
    created_by_active: bool = True
    created_at: datetime
    occurred_at: Optional[datetime] = None
    decided_at: Optional[datetime]
    decided_by: Optional[int]
    decided_by_name: str = ""
    is_voided: bool = False
    voided_at: Optional[datetime] = None
    transfer_group_id: Optional[str] = None
    can_void: bool = False
    void_blocked_reason: Optional[str] = None
    is_in_closed_cycle: bool = False
    settlement_cutoff_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BalanceOut(BaseModel):
    cash_on_hand: float
    spendings: float = 0.0
    currency: str
    pending_count: int
    last_expense_payout_at: str | None = None
    last_income_handover_at: str | None = None
    reserved_spendings: float = 0.0
    reserved_cash: float = 0.0
    available_spendings: float = 0.0
    available_cash: float = 0.0


class DecideIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approve: bool
    note: str = Field(default="", max_length=2000)
    allow_closed_cycle: bool = False

    @field_validator("note")
    @classmethod
    def note_trim(cls, v: str) -> str:
        return _collapse_ws(v, max_len=2000)

    @model_validator(mode="after")
    def reject_needs_note(self):
        if not self.approve and len(self.note or "") < 2:
            raise ValueError("Reject requires a note (min 2 characters)")
        return self


class DecideBatchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(min_length=1, max_length=100)
    approve: bool
    note: str = Field(default="", max_length=2000)
    allow_closed_cycle: bool = False

    @field_validator("note")
    @classmethod
    def note_trim(cls, v: str) -> str:
        return _collapse_ws(v, max_len=2000)

    @field_validator("ids")
    @classmethod
    def ids_unique(cls, v: list[int]) -> list[int]:
        seen: set[int] = set()
        out: list[int] = []
        for rid in v:
            if rid in seen:
                continue
            seen.add(rid)
            out.append(rid)
        if not out:
            raise ValueError("ids required")
        return out

    @model_validator(mode="after")
    def reject_needs_note(self):
        if not self.approve and len(self.note or "") < 2:
            raise ValueError("Reject requires a note (min 2 characters)")
        return self


class DecideBatchOut(BaseModel):
    decided: list[RecordOut]
    skipped: int = 0
    skipped_insufficient_cash: int = 0
    skipped_inactive: int = 0
    skipped_closed_cycle: int = 0


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1, max_length=2000)

    @field_validator("note")
    @classmethod
    def note_trimmed(cls, v: str) -> str:
        note = _collapse_ws(v, max_len=2000)
        if len(note) < 2:
            raise ValueError("Note is required (min 2 characters)")
        return note


class MemberOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    organization_id: int
    must_set_password: bool = False

    model_config = {"from_attributes": True}


class MemberActiveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    is_active: bool


class MemberRoleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: UserRole


class CategoryTotal(BaseModel):
    kind: str
    category: str
    total: float


class PurposeTotal(BaseModel):
    purpose: str
    total: float


class OrgReportOut(BaseModel):
    currency: str
    approved_expense_total: float
    approved_fuel_total: float
    approved_income_cash: float
    approved_income_transfer: float
    pending_count: int
    team_count: int
    # Period P&L: all income − all spend
    net_result: float = 0.0
    # Period cash movement: cash income − spend paid from cash_on_hand
    cash_position: float
    spend_from_cash: float = 0.0
    spend_from_pocket: float = 0.0
    # Peer cash transfers (excluded from operating expense/income totals)
    internal_transfer_total: float = 0.0
    total_spendings: float = 0.0
    total_cash_held: float = 0.0
    by_category: list[CategoryTotal]
    by_purpose: list[PurposeTotal] = []


class MyReportOut(BaseModel):
    currency: str
    cash_on_hand: float
    spendings: float
    approved_expense_total: float
    approved_fuel_total: float
    approved_income_cash: float
    pending_count: int
    by_purpose: list[PurposeTotal] = []
    by_category: list[CategoryTotal] = []


class PhotoOut(BaseModel):
    photo_url: str


class CategoriesOut(BaseModel):
    categories: dict[str, list[str]]
    purposes: list[str] = []
    payment_sources: list[str] = []
