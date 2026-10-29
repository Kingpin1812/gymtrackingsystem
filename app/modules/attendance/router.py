from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ValidationFailed
from app.core.pagination import Page, PageParams
from app.modules.attendance import service
from app.modules.attendance.schemas import (
    AttendanceOut,
    CheckResult,
    MemberBrief,
    MemberLookup,
    Occupancy,
    StaleCloseResult,
)
from app.modules.auth.deps import (
    get_current_user,
    get_db,
    get_settings_dep,
    require_admin,
    require_staff,
)
from app.modules.auth.models import User
from app.modules.members.access import (
    get_accessible_member,
    member_for_user,
    scope_members_query,
)
from app.modules.members.models import Member

router = APIRouter(prefix="/api/attendance", tags=["attendance"])


def _result(result: str, member: Member, session, stale_id: int | None = None) -> CheckResult:
    return CheckResult(
        result=result,
        member=MemberBrief(id=member.id, full_name=member.full_name),
        session=AttendanceOut.model_validate(session),
        closed_stale_session_id=stale_id,
    )


# Check-in/out is front-desk work: any staff member (admin or trainer) may record it for any
# member. The response contains only the member's id and name.
@router.post("/check-in", response_model=CheckResult)
def check_in(
    body: MemberLookup,
    staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    member = service.find_member(db, body.qr_token, body.member_id)
    method = "qr" if body.qr_token else "manual"
    result, session, stale_id = service.check_in(db, settings, staff, member, method)
    return _result(result, member, session, stale_id)


@router.post("/check-out", response_model=CheckResult)
def check_out(
    body: MemberLookup,
    staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    member = service.find_member(db, body.qr_token, body.member_id)
    result, session = service.check_out(db, settings, staff, member)
    return _result(result, member, session)


@router.get("/occupancy", response_model=Occupancy)
def occupancy(
    _staff: User = Depends(require_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    return service.occupancy(db, settings)


@router.post("/close-stale", response_model=StaleCloseResult)
def close_stale(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    return StaleCloseResult(closed=service.close_stale_sessions(db, settings))


def _check_range(date_from: date | None, date_to: date | None) -> None:
    if date_from and date_to and date_from > date_to:
        raise ValidationFailed("date_from must be on or before date_to")


@router.get("", response_model=Page[AttendanceOut])
def list_attendance(
    member_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    open_only: bool = False,
    page: PageParams = Depends(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    """Admins see all visits; trainers see assigned members; members see their own."""
    _check_range(date_from, date_to)
    if member_id is not None:
        member_ids = select(Member.id).where(
            Member.id == get_accessible_member(db, user, member_id).id
        )
    else:
        member_ids = scope_members_query(select(Member.id), user)
    items, total = service.list_sessions(
        db, settings, member_ids, date_from, date_to, open_only, page.limit, page.offset
    )
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/me", response_model=Page[AttendanceOut])
def my_attendance(
    page: PageParams = Depends(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_dep),
):
    member = member_for_user(db, user)
    member_ids = select(Member.id).where(Member.id == member.id)
    items, total = service.list_sessions(
        db, settings, member_ids, None, None, False, page.limit, page.offset
    )
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)
