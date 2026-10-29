from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MemberLookup(BaseModel):
    """Identify a member by scanned QR token or (manual desk entry) by member id."""

    qr_token: str | None = Field(default=None, min_length=8, max_length=64)
    member_id: int | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if (self.qr_token is None) == (self.member_id is None):
            raise ValueError("Provide exactly one of qr_token or member_id")
        return self


class AttendanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    member_id: int
    check_in_at: datetime
    check_out_at: datetime | None
    closed_at: datetime | None
    closed_reason: str | None
    method: str


class MemberBrief(BaseModel):
    id: int
    full_name: str


class CheckResult(BaseModel):
    result: Literal["checked_in", "already_checked_in", "checked_out", "already_checked_out"]
    member: MemberBrief
    session: AttendanceOut
    # Set when an earlier visit was auto-closed because the member never checked out.
    closed_stale_session_id: int | None = None


class Occupancy(BaseModel):
    estimated_count: int
    is_estimate: bool = True
    stale_open_sessions: int
    stale_after_hours: int
    as_of: datetime
    explanation: str


class StaleCloseResult(BaseModel):
    closed: int
