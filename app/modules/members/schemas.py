import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import MIN_PASSWORD_LENGTH
from app.modules.auth.schemas import clean_name, normalize_email

_PHONE_RE = re.compile(r"^\+?[0-9 ()-]{6,32}$")


def _clean_phone(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip()
    if not _PHONE_RE.match(v):
        raise ValueError("must contain only digits, spaces, +, -, ( or )")
    return v


def _clean_optional_email(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    return normalize_email(v)


class MemberCreate(BaseModel):
    full_name: str = Field(max_length=120)
    email: str | None = None
    phone: str | None = None
    assigned_trainer_id: int | None = None
    # When provided, a member login account is created (requires email).
    password: str | None = Field(default=None, min_length=MIN_PASSWORD_LENGTH, max_length=200)

    @field_validator("full_name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return clean_name(v)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return _clean_optional_email(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return _clean_phone(v)


class MemberUpdate(BaseModel):
    """Partial update. Only fields present in the request body are changed."""

    full_name: str | None = Field(default=None, max_length=120)
    email: str | None = None
    phone: str | None = None
    assigned_trainer_id: int | None = None

    @field_validator("full_name")
    @classmethod
    def check_name(cls, v: str | None) -> str | None:
        return None if v is None else clean_name(v)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str | None) -> str | None:
        return _clean_optional_email(v)

    @field_validator("phone")
    @classmethod
    def check_phone(cls, v: str | None) -> str | None:
        return _clean_phone(v)


class MemberAccountCreate(BaseModel):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)


class MembershipSummary(BaseModel):
    id: int
    plan_name: str
    start_date: date
    end_date: date
    status: str  # effective status: active | scheduled | expired | suspended | cancelled


class MemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str | None
    phone: str | None
    status: str
    assigned_trainer_id: int | None
    has_login: bool
    created_at: datetime
    deactivated_at: datetime | None
    current_membership: MembershipSummary | None = None


class PlanCreate(BaseModel):
    name: str = Field(max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    duration_days: int = Field(gt=0, le=3660)
    price_cents: int = Field(default=0, ge=0, le=100_000_000)

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return clean_name(v)


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=1000)
    price_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def check_name(cls, v: str | None) -> str | None:
        return None if v is None else clean_name(v)


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    duration_days: int
    price_cents: int
    is_active: bool


class MembershipCreate(BaseModel):
    plan_id: int
    # Defaults to today in the gym's time zone.
    start_date: date | None = None


class MembershipOut(BaseModel):
    id: int
    member_id: int
    plan_id: int
    plan_name: str
    start_date: date
    end_date: date
    stored_status: str
    status: str
    created_at: datetime
