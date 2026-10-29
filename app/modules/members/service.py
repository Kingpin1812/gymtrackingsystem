"""Member, membership-plan and membership business rules."""

import secrets
from datetime import date, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import gym_today, utcnow
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.attendance.models import AttendanceSession, CloseReason
from app.modules.auth import service as auth_service
from app.modules.auth.models import Role, User
from app.modules.members.models import (
    Member,
    Membership,
    MembershipPlan,
    MembershipStatus,
    MemberStatus,
)

# ---------------------------------------------------------------- memberships: state rules

# Allowed transitions between *stored* statuses. "expired" and "scheduled" are derived from
# dates, never stored, so a membership expires without any background job.
TRANSITIONS: dict[str, set[str]] = {
    MembershipStatus.ACTIVE: {MembershipStatus.SUSPENDED, MembershipStatus.CANCELLED},
    MembershipStatus.SUSPENDED: {MembershipStatus.ACTIVE, MembershipStatus.CANCELLED},
    MembershipStatus.CANCELLED: set(),
}


def effective_status(m: Membership, today: date) -> str:
    if m.status != MembershipStatus.ACTIVE:
        return m.status
    if today < m.start_date:
        return "scheduled"
    if today > m.end_date:
        return "expired"
    return "active"


def is_valid_on(m: Membership, day: date) -> bool:
    return m.status == MembershipStatus.ACTIVE and m.start_date <= day <= m.end_date


def current_membership(db: Session, member_id: int, day: date) -> Membership | None:
    """The membership that grants access on `day`, if any."""
    return db.scalar(
        select(Membership)
        .where(
            Membership.member_id == member_id,
            Membership.status == MembershipStatus.ACTIVE,
            Membership.start_date <= day,
            Membership.end_date >= day,
        )
        .order_by(Membership.end_date.desc())
    )


def latest_membership(db: Session, member_id: int, day: date) -> Membership | None:
    """The membership to show on a member's profile: the valid one, else the most recent."""
    return current_membership(db, member_id, day) or db.scalar(
        select(Membership)
        .where(Membership.member_id == member_id)
        .order_by(Membership.end_date.desc(), Membership.id.desc())
    )


# ---------------------------------------------------------------- members


def _new_qr_token() -> str:
    return secrets.token_urlsafe(24)


def _ensure_trainer(db: Session, trainer_id: int | None) -> None:
    if trainer_id is None:
        return
    trainer = db.get(User, trainer_id)
    if trainer is None or trainer.role != Role.TRAINER or not trainer.is_active:
        raise ValidationFailed(
            "assigned_trainer_id must refer to an active trainer", code="invalid_trainer"
        )


def _ensure_email_free(db: Session, email: str | None, exclude_member_id: int | None = None):
    if email is None:
        return
    stmt = select(Member.id).where(Member.email == email)
    if exclude_member_id is not None:
        stmt = stmt.where(Member.id != exclude_member_id)
    if db.scalar(stmt) is not None:
        raise Conflict("A member with this email already exists", code="email_taken")


def create_member(
    db: Session,
    *,
    full_name: str,
    email: str | None,
    phone: str | None,
    assigned_trainer_id: int | None,
    password: str | None,
) -> Member:
    if password and not email:
        raise ValidationFailed("An email is required to create a login", code="email_required")
    _ensure_trainer(db, assigned_trainer_id)
    _ensure_email_free(db, email)
    member = Member(
        full_name=full_name,
        email=email,
        phone=phone,
        assigned_trainer_id=assigned_trainer_id,
        qr_token=_new_qr_token(),
    )
    if password:
        user = auth_service.create_user(
            db, email=email, full_name=full_name, role=Role.MEMBER, password=password
        )
        member.user_id = user.id
    db.add(member)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("A member with this email already exists", code="email_taken") from exc
    return member


def list_members(
    db: Session, stmt, q: str | None, status: MemberStatus | None, limit: int, offset: int
) -> tuple[list[Member], int]:
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Member.full_name).like(like),
                func.lower(Member.email).like(like),
                Member.phone.like(like),
            )
        )
    if status:
        stmt = stmt.where(Member.status == status.value)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(stmt.order_by(Member.full_name, Member.id).limit(limit).offset(offset))
    return list(items), total


def update_member(db: Session, member: Member, changes: dict) -> Member:
    if "full_name" in changes and changes["full_name"] is None:
        raise ValidationFailed("full_name cannot be empty")
    if "assigned_trainer_id" in changes:
        _ensure_trainer(db, changes["assigned_trainer_id"])
    if "email" in changes:
        if member.user_id and changes["email"] is None:
            raise ValidationFailed(
                "A member with a login must keep an email", code="email_required"
            )
        _ensure_email_free(db, changes["email"], exclude_member_id=member.id)
    for field, value in changes.items():
        setattr(member, field, value)
    if member.user_id and ("email" in changes or "full_name" in changes):
        # Keep the linked login account in sync with the member profile.
        user = db.get(User, member.user_id)
        if "email" in changes and changes["email"] != user.email:
            if db.scalar(select(User.id).where(User.email == changes["email"])):
                raise Conflict("A user with this email already exists", code="email_taken")
            user.email = changes["email"]
        user.full_name = member.full_name
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise Conflict("Email is already in use", code="email_taken") from exc
    return member


def create_member_account(db: Session, member: Member, password: str) -> Member:
    if member.user_id:
        raise Conflict("This member already has a login", code="account_exists")
    if not member.email:
        raise ValidationFailed("Add an email to the member before creating a login",
                               code="email_required")
    user = auth_service.create_user(
        db, email=member.email, full_name=member.full_name, role=Role.MEMBER, password=password
    )
    user.is_active = member.status == MemberStatus.ACTIVE
    member.user_id = user.id
    db.commit()
    return member


def deactivate_member(db: Session, member: Member) -> Member:
    """Deactivate: block check-ins and login. History (memberships, visits, workouts) is kept."""
    if member.status == MemberStatus.INACTIVE:
        return member
    now = utcnow()
    member.status = MemberStatus.INACTIVE
    member.deactivated_at = now
    if member.user_id:
        db.get(User, member.user_id).is_active = False
        auth_service.revoke_all_sessions(db, member.user_id)
    db.execute(
        update(AttendanceSession)
        .where(AttendanceSession.member_id == member.id, AttendanceSession.closed_reason.is_(None))
        .values(closed_at=now, closed_reason=CloseReason.MEMBER_DEACTIVATED)
    )
    db.commit()
    return member


def reactivate_member(db: Session, member: Member) -> Member:
    if member.status == MemberStatus.ACTIVE:
        return member
    member.status = MemberStatus.ACTIVE
    member.deactivated_at = None
    if member.user_id:
        db.get(User, member.user_id).is_active = True
    db.commit()
    return member


def rotate_qr_token(db: Session, member: Member) -> Member:
    """Issue a new QR identifier; the old QR code stops working immediately."""
    member.qr_token = _new_qr_token()
    db.commit()
    return member


# ---------------------------------------------------------------- plans


def create_plan(db: Session, **fields) -> MembershipPlan:
    if db.scalar(select(MembershipPlan.id).where(MembershipPlan.name == fields["name"])):
        raise Conflict("A plan with this name already exists", code="plan_name_taken")
    plan = MembershipPlan(**fields)
    db.add(plan)
    db.commit()
    return plan


def update_plan(db: Session, plan_id: int, changes: dict) -> MembershipPlan:
    plan = db.get(MembershipPlan, plan_id)
    if plan is None:
        raise NotFound("Plan not found")
    if changes.get("name") and changes["name"] != plan.name:
        if db.scalar(select(MembershipPlan.id).where(MembershipPlan.name == changes["name"])):
            raise Conflict("A plan with this name already exists", code="plan_name_taken")
    for field, value in changes.items():
        if value is not None or field == "description":
            setattr(plan, field, value)
    db.commit()
    return plan


def list_plans(db: Session, include_inactive: bool) -> list[MembershipPlan]:
    stmt = select(MembershipPlan).order_by(MembershipPlan.duration_days, MembershipPlan.name)
    if not include_inactive:
        stmt = stmt.where(MembershipPlan.is_active.is_(True))
    return list(db.scalars(stmt))


# ---------------------------------------------------------------- memberships


def add_membership(
    db: Session, member: Member, plan_id: int, start_date: date | None
) -> Membership:
    plan = db.get(MembershipPlan, plan_id)
    if plan is None or not plan.is_active:
        raise ValidationFailed("plan_id must refer to an active plan", code="invalid_plan")
    if member.status != MemberStatus.ACTIVE:
        raise Conflict("Cannot add a membership to an inactive member", code="member_inactive")
    start = start_date or gym_today()
    end = start + timedelta(days=plan.duration_days - 1)
    overlap = db.scalar(
        select(Membership.id).where(
            Membership.member_id == member.id,
            Membership.status != MembershipStatus.CANCELLED,
            Membership.start_date <= end,
            Membership.end_date >= start,
        )
    )
    if overlap is not None:
        raise Conflict(
            "This membership would overlap an existing membership", code="membership_overlap"
        )
    membership = Membership(member_id=member.id, plan_id=plan.id, start_date=start, end_date=end)
    db.add(membership)
    db.commit()
    return membership


def change_membership_status(db: Session, membership: Membership, new_status: str) -> Membership:
    if new_status not in TRANSITIONS[membership.status]:
        raise Conflict(
            f"Cannot change a {membership.status} membership to {new_status}",
            code="invalid_transition",
        )
    if new_status == MembershipStatus.ACTIVE:
        overlap = db.scalar(
            select(Membership.id).where(
                Membership.member_id == membership.member_id,
                Membership.id != membership.id,
                Membership.status != MembershipStatus.CANCELLED,
                Membership.start_date <= membership.end_date,
                Membership.end_date >= membership.start_date,
            )
        )
        if overlap is not None:
            raise Conflict("Resuming would overlap another membership", code="membership_overlap")
    membership.status = new_status
    db.commit()
    return membership


def get_membership(db: Session, membership_id: int) -> Membership:
    membership = db.get(Membership, membership_id)
    if membership is None:
        raise NotFound("Membership not found")
    return membership
