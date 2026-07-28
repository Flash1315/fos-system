from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.models import RecordKind, RecordStatus, UserRole


class OrgCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9-]+$")
    currency: str = "IDR"
    owner_email: EmailStr
    owner_name: str = Field(min_length=2, max_length=200)
    owner_password: str = Field(min_length=6, max_length=128)


class OrgOut(BaseModel):
    id: int
    name: str
    slug: str
    currency: str

    model_config = {"from_attributes": True}


class OrgUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=200)
    currency: Optional[str] = Field(default=None, min_length=1, max_length=8)


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
    user: UserOut


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    organization_slug: str


class InviteIn(BaseModel):
    email: EmailStr
    full_name: str
    role: UserRole = UserRole.employee
    password: str = Field(min_length=6, max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class MemberPasswordResetIn(BaseModel):
    new_password: str = Field(min_length=6, max_length=128)


class RecordCreate(BaseModel):
    kind: RecordKind
    amount: float = Field(gt=0)
    category: str = ""
    purpose: str = ""
    place: str = ""
    bike: str = ""
    comment: str = ""
    photo_url: str = ""
    liters: Optional[float] = None
    odometer: Optional[float] = None
    client_name: str = ""
    payment_method: str = ""
    payment_source: str = ""
    # Manager can file on behalf of a teammate (balances attribute to them)
    created_for_user_id: Optional[int] = None
    # ISO datetime or date when money moved (optional; defaults to created_at)
    occurred_at: Optional[datetime] = None
    # Managers/owners can create already-approved (skip queue)
    approve_now: bool = False


class RecordUpdate(BaseModel):
    amount: Optional[float] = Field(default=None, gt=0)
    category: Optional[str] = None
    purpose: Optional[str] = None
    place: Optional[str] = None
    bike: Optional[str] = None
    comment: Optional[str] = None
    photo_url: Optional[str] = None
    liters: Optional[float] = None
    odometer: Optional[float] = None
    client_name: Optional[str] = None
    payment_method: Optional[str] = None
    payment_source: Optional[str] = None
    occurred_at: Optional[datetime] = None


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
    created_at: datetime
    occurred_at: Optional[datetime] = None
    decided_at: Optional[datetime]
    decided_by: Optional[int]
    decided_by_name: str = ""
    is_voided: bool = False
    voided_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class BalanceOut(BaseModel):
    cash_on_hand: float
    spendings: float = 0.0
    currency: str
    pending_count: int


class DecideIn(BaseModel):
    approve: bool
    note: str = ""


class DecideBatchIn(BaseModel):
    ids: list[int] = Field(min_length=1)
    approve: bool
    note: str = ""


class CommentIn(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


class MemberOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: UserRole
    is_active: bool
    organization_id: int

    model_config = {"from_attributes": True}


class MemberActiveIn(BaseModel):
    is_active: bool


class MemberRoleIn(BaseModel):
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
