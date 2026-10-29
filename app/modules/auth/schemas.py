import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.security import MIN_PASSWORD_LENGTH
from app.modules.auth.models import Role

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    value = value.strip().lower()
    if len(value) > 254 or not _EMAIL_RE.match(value):
        raise ValueError("must be a valid email address")
    return value


def clean_name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("must not be blank")
    return value


class LoginRequest(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: Role
    is_active: bool
    created_at: datetime


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime
    user: UserOut


class UserCreate(BaseModel):
    email: str
    full_name: str = Field(max_length=120)
    role: Role
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return normalize_email(v)

    @field_validator("full_name")
    @classmethod
    def check_name(cls, v: str) -> str:
        return clean_name(v)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=120)
    is_active: bool | None = None

    @field_validator("full_name")
    @classmethod
    def check_name(cls, v: str | None) -> str | None:
        return None if v is None else clean_name(v)


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
