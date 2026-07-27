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
    decided_at: Optional[datetime]
    decided_by: Optional[int]

    model_config = {"from_attributes": True}


class BalanceOut(BaseModel):
    cash_on_hand: float
    spendings: float = 0.0
    currency: str
    pending_count: int


class DecideIn(BaseModel):
    approve: bool
    note: str = ""


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


class CategoryTotal(BaseModel):
    kind: str
    category: str
    total: float


class OrgReportOut(BaseModel):
    currency: str
    approved_expense_total: float
    approved_fuel_total: float
    approved_income_cash: float
    approved_income_transfer: float
    pending_count: int
    team_count: int
    cash_position: float
    by_category: list[CategoryTotal]


class PhotoOut(BaseModel):
    photo_url: str


class CategoriesOut(BaseModel):
    categories: dict[str, list[str]]
    purposes: list[str] = []
    payment_sources: list[str] = []
