"""Attendance rules: check-in/out lifecycle, duplicate handling, stale sessions, occupancy.

Policy (documented in docs/architecture/attendance-policy.md):
- One open session per member (enforced by a partial unique index).
- Check-in requires an active member with a membership valid today (gym time zone).
- Repeated check-in while a session is open returns the open session ("already_checked_in").
- An open session older than STALE_SESSION_HOURS is "stale": it is excluded from occupancy and is
  closed with reason "stale" (check_out_at left NULL) on the member's next check-in.
- Check-out with no open session returns the last session if it was checked out within
  CHECKOUT_DEDUPE_SECONDS ("already_checked_out"); otherwise 409 not_checked_in.
"""

from datetime import date, datetime, time, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import gym_today, utcnow
from app.core.config import Settings
from app.core.errors import Conflict, NotFound
from app.modules.attendance.models import AttendanceSession, CloseReason
from app.modules.auth.models import User
from app.modules.members import service as members_service
from app.modules.members.models import Member, MemberStatus


def find_member(db: Session, qr_token: str | None, member_id: int | None) -> Member:
    if qr_token is not None:
        member = db.scalar(select(Member).where(Member.qr_token == qr_token))
        if member is None:
            raise NotFound("QR code not recognised. It may have been replaced.", code="unknown_qr")
        return member
    member = db.get(Member, member_id)
    if member is None:
        raise NotFound("Member not found")
    return member


def _open_session(db: Session, member_id: int) -> AttendanceSession | None:
    return db.scalar(
        select(AttendanceSession).where(
            AttendanceSession.member_id == member_id, AttendanceSession.closed_reason.is_(None)
        )
    )


def _stale_cutoff(settings: Settings, now: datetime) -> datetime:
    return now - timedelta(hours=settings.stale_session_hours)


def check_in(
    db: Session, settings: Settings, staff: User, member: Member, method: str
) -> tuple[str, AttendanceSession, int | None]:
    if member.status != MemberStatus.ACTIVE:
        raise Conflict("Member is inactive", code="member_inactive")
    if members_service.current_membership(db, member.id, gym_today()) is None:
        raise Conflict(
            "No valid membership for today (expired, suspended, cancelled or not started)",
            code="membership_invalid",
        )
    now = utcnow()
    closed_stale_id = None
    existing = _open_session(db, member.id)
    if existing is not None:
        if existing.check_in_at > _stale_cutoff(settings, now):
            return "already_checked_in", existing, None
        existing.closed_reason = CloseReason.STALE
        existing.closed_at = now
        closed_stale_id = existing.id
        db.flush()
    session = AttendanceSession(
        member_id=member.id, check_in_at=now, method=method, checked_in_by_user_id=staff.id
    )
    db.add(session)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request opened a session first; return that one (idempotent).
        db.rollback()
        existing = _open_session(db, member.id)
        if existing is None:
            raise
        return "already_checked_in", existing, None
    return "checked_in", session, closed_stale_id


def check_out(
    db: Session, settings: Settings, staff: User, member: Member
) -> tuple[str, AttendanceSession]:
    now = utcnow()
    session = _open_session(db, member.id)
    if session is None:
        last = db.scalar(
            select(AttendanceSession)
            .where(AttendanceSession.member_id == member.id)
            .order_by(AttendanceSession.check_in_at.desc(), AttendanceSession.id.desc())
        )
        if (
            last is not None
            and last.closed_reason == CloseReason.CHECKED_OUT
            and now - last.check_out_at <= timedelta(seconds=settings.checkout_dedupe_seconds)
        ):
            return "already_checked_out", last
        raise Conflict("Member is not checked in", code="not_checked_in")
    session.check_out_at = now
    session.closed_at = now
    session.closed_reason = CloseReason.CHECKED_OUT
    session.checked_out_by_user_id = staff.id
    db.commit()
    return "checked_out", session


def occupancy(db: Session, settings: Settings) -> dict:
    now = utcnow()
    cutoff = _stale_cutoff(settings, now)
    open_q = select(func.count()).where(AttendanceSession.closed_reason.is_(None))
    fresh = db.scalar(open_q.where(AttendanceSession.check_in_at > cutoff))
    stale = db.scalar(open_q.where(AttendanceSession.check_in_at <= cutoff))
    return {
        "estimated_count": fresh,
        "stale_open_sessions": stale,
        "stale_after_hours": settings.stale_session_hours,
        "as_of": now,
        "explanation": (
            "Estimate: members checked in during the last "
            f"{settings.stale_session_hours} hours who have not checked out. People who leave "
            "without checking out are counted until their check-in becomes stale."
        ),
    }


def close_stale_sessions(db: Session, settings: Settings) -> int:
    now = utcnow()
    result = db.execute(
        update(AttendanceSession)
        .where(
            AttendanceSession.closed_reason.is_(None),
            AttendanceSession.check_in_at <= _stale_cutoff(settings, now),
        )
        .values(closed_reason=CloseReason.STALE, closed_at=now)
    )
    db.commit()
    return result.rowcount


def gym_day_bounds_utc(settings: Settings, day_from: date | None, day_to: date | None):
    """Convert inclusive gym-local dates into a UTC [start, end) range."""
    tz = settings.tz
    start = datetime.combine(day_from, time.min, tz) if day_from else None
    end = datetime.combine(day_to + timedelta(days=1), time.min, tz) if day_to else None
    return start, end


def list_sessions(
    db: Session,
    settings: Settings,
    member_ids_stmt,
    date_from: date | None,
    date_to: date | None,
    open_only: bool,
    limit: int,
    offset: int,
) -> tuple[list[AttendanceSession], int]:
    stmt = select(AttendanceSession).where(AttendanceSession.member_id.in_(member_ids_stmt))
    start, end = gym_day_bounds_utc(settings, date_from, date_to)
    if start:
        stmt = stmt.where(AttendanceSession.check_in_at >= start)
    if end:
        stmt = stmt.where(AttendanceSession.check_in_at < end)
    if open_only:
        stmt = stmt.where(AttendanceSession.closed_reason.is_(None))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(
        stmt.order_by(AttendanceSession.check_in_at.desc(), AttendanceSession.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(items), total
