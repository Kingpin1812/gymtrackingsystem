from datetime import date

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.errors import Conflict, ValidationFailed
from app.core.pagination import Page, PageParams
from app.modules.auth.deps import get_current_user, get_db, require_staff
from app.modules.auth.models import User
from app.modules.members.access import get_accessible_member
from app.modules.members.models import MemberStatus
from app.modules.workouts import service
from app.modules.workouts.models import WorkoutSession
from app.modules.workouts.schemas import (
    ExerciseCreate,
    ExerciseOut,
    ProgressOut,
    SetOut,
    WorkoutIn,
    WorkoutOut,
)

router = APIRouter(prefix="/api", tags=["workouts"])


def _workout_out(w: WorkoutSession) -> WorkoutOut:
    return WorkoutOut(
        id=w.id,
        member_id=w.member_id,
        performed_on=w.performed_on,
        duration_minutes=w.duration_minutes,
        notes=w.notes,
        created_by_user_id=w.created_by_user_id,
        sets=[
            SetOut(
                id=s.id,
                exercise_id=s.exercise_id,
                exercise_name=s.exercise.name,
                set_number=s.set_number,
                reps=s.reps,
                weight=s.weight,
                weight_unit=s.weight_unit,
                duration_seconds=s.duration_seconds,
            )
            for s in w.sets
        ],
    )


def _accessible_workout(db: Session, user: User, workout_id: int) -> WorkoutSession:
    workout = service.get_workout(db, workout_id)
    # Raises 404 when the user cannot access the workout's member.
    get_accessible_member(db, user, workout.member_id)
    return workout


@router.get("/exercises", response_model=list[ExerciseOut])
def list_exercises(_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return service.list_exercises(db)


@router.post("/exercises", response_model=ExerciseOut, status_code=status.HTTP_201_CREATED)
def create_exercise(
    body: ExerciseCreate, _staff: User = Depends(require_staff), db: Session = Depends(get_db)
):
    return service.create_exercise(db, body.name, body.category)


@router.get("/members/{member_id}/workouts", response_model=Page[WorkoutOut])
def list_member_workouts(
    member_id: int,
    date_from: date | None = None,
    date_to: date | None = None,
    page: PageParams = Depends(),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if date_from and date_to and date_from > date_to:
        raise ValidationFailed("date_from must be on or before date_to")
    member = get_accessible_member(db, user, member_id)
    items, total = service.list_workouts(
        db, member.id, date_from, date_to, page.limit, page.offset
    )
    return Page(
        items=[_workout_out(w) for w in items], total=total, limit=page.limit, offset=page.offset
    )


@router.post(
    "/members/{member_id}/workouts",
    response_model=WorkoutOut,
    status_code=status.HTTP_201_CREATED,
)
def create_workout(
    member_id: int,
    body: WorkoutIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = get_accessible_member(db, user, member_id)
    if member.status != MemberStatus.ACTIVE:
        raise Conflict("Cannot log workouts for an inactive member", code="member_inactive")
    return _workout_out(service.create_workout(db, user, member, body))


@router.get("/workouts/{workout_id}", response_model=WorkoutOut)
def get_workout(
    workout_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    return _workout_out(_accessible_workout(db, user, workout_id))


@router.put("/workouts/{workout_id}", response_model=WorkoutOut)
def replace_workout(
    workout_id: int,
    body: WorkoutIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    workout = _accessible_workout(db, user, workout_id)
    return _workout_out(service.replace_workout(db, workout, body))


@router.delete("/workouts/{workout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workout(
    workout_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    service.delete_workout(db, _accessible_workout(db, user, workout_id))


@router.get("/members/{member_id}/progress", response_model=ProgressOut)
def member_progress(
    member_id: int,
    exercise_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = get_accessible_member(db, user, member_id)
    return service.progress(db, member.id, exercise_id)
