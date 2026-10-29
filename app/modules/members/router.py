import io

import segno
from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import gym_today
from app.core.errors import NotFound
from app.core.pagination import Page, PageParams
from app.modules.auth.deps import get_current_user, get_db, require_admin, require_staff
from app.modules.auth.models import Role, User
from app.modules.members import service
from app.modules.members.access import (
    get_accessible_member,
    member_for_user,
    scope_members_query,
)
from app.modules.members.models import Member, Membership, MembershipStatus, MemberStatus
from app.modules.members.schemas import (
    MemberAccountCreate,
    MemberCreate,
    MemberOut,
    MembershipCreate,
    MembershipOut,
    MembershipSummary,
    MemberUpdate,
    PlanCreate,
    PlanOut,
    PlanUpdate,
)

router = APIRouter(prefix="/api", tags=["members"])


def _membership_out(m: Membership) -> MembershipOut:
    return MembershipOut(
        id=m.id,
        member_id=m.member_id,
        plan_id=m.plan_id,
        plan_name=m.plan.name,
        start_date=m.start_date,
        end_date=m.end_date,
        stored_status=m.status,
        status=service.effective_status(m, gym_today()),
        created_at=m.created_at,
    )


def _member_out(db: Session, member: Member) -> MemberOut:
    today = gym_today()
    current = service.latest_membership(db, member.id, today)
    summary = None
    if current is not None:
        summary = MembershipSummary(
            id=current.id,
            plan_name=current.plan.name,
            start_date=current.start_date,
            end_date=current.end_date,
            status=service.effective_status(current, today),
        )
    return MemberOut(
        id=member.id,
        full_name=member.full_name,
        email=member.email,
        phone=member.phone,
        status=member.status,
        assigned_trainer_id=member.assigned_trainer_id,
        has_login=member.user_id is not None,
        created_at=member.created_at,
        deactivated_at=member.deactivated_at,
        current_membership=summary,
    )


# ---------------------------------------------------------------- members


@router.get("/members", response_model=Page[MemberOut])
def list_members(
    q: str | None = None,
    member_status: MemberStatus | None = Query(None, alias="status"),
    page: PageParams = Depends(),
    user: User = Depends(require_staff),
    db: Session = Depends(get_db),
):
    stmt = scope_members_query(select(Member), user)
    items, total = service.list_members(db, stmt, q, member_status, page.limit, page.offset)
    return Page(
        items=[_member_out(db, m) for m in items],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.post("/members", response_model=MemberOut, status_code=status.HTTP_201_CREATED)
def create_member(
    body: MemberCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    member = service.create_member(db, **body.model_dump())
    return _member_out(db, member)


@router.get("/members/me", response_model=MemberOut)
def my_member_profile(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _member_out(db, member_for_user(db, user))


@router.get("/members/{member_id}", response_model=MemberOut)
def get_member(
    member_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return _member_out(db, get_accessible_member(db, user, member_id))


@router.patch("/members/{member_id}", response_model=MemberOut)
def update_member(
    member_id: int,
    body: MemberUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    member = get_accessible_member(db, admin, member_id)
    return _member_out(db, service.update_member(db, member, body.model_dump(exclude_unset=True)))


@router.post("/members/{member_id}/deactivate", response_model=MemberOut)
def deactivate_member(
    member_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    member = get_accessible_member(db, admin, member_id)
    return _member_out(db, service.deactivate_member(db, member))


@router.post("/members/{member_id}/reactivate", response_model=MemberOut)
def reactivate_member(
    member_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    member = get_accessible_member(db, admin, member_id)
    return _member_out(db, service.reactivate_member(db, member))


@router.post("/members/{member_id}/account", response_model=MemberOut)
def create_member_account(
    member_id: int,
    body: MemberAccountCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    member = get_accessible_member(db, admin, member_id)
    return _member_out(db, service.create_member_account(db, member, body.password))


def _qr_member(db: Session, user: User, member_id: int) -> Member:
    """QR codes are visible to admins and to the member themselves (not trainers)."""
    member = get_accessible_member(db, user, member_id)
    if user.role == Role.TRAINER:
        raise NotFound("Member not found")
    return member


@router.get("/members/{member_id}/qr.svg")
def member_qr_svg(
    member_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    member = _qr_member(db, user, member_id)
    buf = io.BytesIO()
    # A standalone SVG file needs the xmlns attribute (svg_inline omits it).
    segno.make(member.qr_token, error="m").save(buf, kind="svg", scale=6, border=2, xmldecl=False)
    svg = buf.getvalue()
    return Response(
        content=svg, media_type="image/svg+xml", headers={"Cache-Control": "no-store"}
    )


@router.get("/members/{member_id}/qr-token")
def member_qr_token(
    member_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """The raw token, for front-desk manual entry when a camera/scanner is unavailable."""
    member = _qr_member(db, user, member_id)
    return {"qr_token": member.qr_token}


@router.post("/members/{member_id}/qr/rotate", status_code=status.HTTP_204_NO_CONTENT)
def rotate_member_qr(
    member_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    service.rotate_qr_token(db, _qr_member(db, user, member_id))


# ---------------------------------------------------------------- memberships


@router.get("/members/{member_id}/memberships", response_model=list[MembershipOut])
def list_member_memberships(
    member_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    member = get_accessible_member(db, user, member_id)
    return [_membership_out(m) for m in member.memberships]


@router.post(
    "/members/{member_id}/memberships",
    response_model=MembershipOut,
    status_code=status.HTTP_201_CREATED,
)
def add_membership(
    member_id: int,
    body: MembershipCreate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    member = get_accessible_member(db, admin, member_id)
    return _membership_out(service.add_membership(db, member, body.plan_id, body.start_date))


def _transition(membership_id: int, new_status: MembershipStatus, db: Session) -> MembershipOut:
    membership = service.get_membership(db, membership_id)
    return _membership_out(service.change_membership_status(db, membership, new_status))


@router.post("/memberships/{membership_id}/suspend", response_model=MembershipOut)
def suspend_membership(
    membership_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return _transition(membership_id, MembershipStatus.SUSPENDED, db)


@router.post("/memberships/{membership_id}/resume", response_model=MembershipOut)
def resume_membership(
    membership_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return _transition(membership_id, MembershipStatus.ACTIVE, db)


@router.post("/memberships/{membership_id}/cancel", response_model=MembershipOut)
def cancel_membership(
    membership_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return _transition(membership_id, MembershipStatus.CANCELLED, db)


# ---------------------------------------------------------------- plans


@router.get("/plans", response_model=list[PlanOut])
def list_plans(
    include_inactive: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return service.list_plans(db, include_inactive and user.role == Role.ADMIN)


@router.post("/plans", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(
    body: PlanCreate, _admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    return service.create_plan(db, **body.model_dump())


@router.patch("/plans/{plan_id}", response_model=PlanOut)
def update_plan(
    plan_id: int,
    body: PlanUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    return service.update_plan(db, plan_id, body.model_dump(exclude_unset=True))
