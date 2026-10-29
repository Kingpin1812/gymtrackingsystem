"""Workout logging and progress history."""

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.clock import gym_today
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.modules.auth.models import User
from app.modules.members.models import Member
from app.modules.workouts.models import (
    LB_TO_KG,
    Exercise,
    WeightUnit,
    WorkoutSession,
    WorkoutSet,
)
from app.modules.workouts.schemas import WorkoutIn

EARLIEST_WORKOUT_DATE = date(2000, 1, 1)
DISCLAIMER = (
    "Progress figures are calculated from your own logged sets. They are informational only "
    "and are not medical or health advice."
)


def to_kg(weight: float | None, unit: str) -> float | None:
    if weight is None:
        return None
    return weight * LB_TO_KG if unit == WeightUnit.LB else weight


# ---------------------------------------------------------------- exercises


def list_exercises(db: Session) -> list[Exercise]:
    return list(
        db.scalars(
            select(Exercise).where(Exercise.is_active.is_(True)).order_by(Exercise.name)
        )
    )


def create_exercise(db: Session, name: str, category: str) -> Exercise:
    if db.scalar(select(Exercise.id).where(func.lower(Exercise.name) == name.lower())):
        raise Conflict("An exercise with this name already exists", code="exercise_exists")
    exercise = Exercise(name=name, category=category)
    db.add(exercise)
    db.commit()
    return exercise


# ---------------------------------------------------------------- workouts


def _validate(db: Session, data: WorkoutIn) -> None:
    if data.performed_on > gym_today():
        raise ValidationFailed("performed_on cannot be in the future", code="future_date")
    if data.performed_on < EARLIEST_WORKOUT_DATE:
        raise ValidationFailed("performed_on is too far in the past", code="date_out_of_range")
    ids = {s.exercise_id for s in data.sets}
    found = set(
        db.scalars(select(Exercise.id).where(Exercise.id.in_(ids), Exercise.is_active.is_(True)))
    )
    missing = sorted(ids - found)
    if missing:
        raise ValidationFailed(
            "Unknown or inactive exercise", code="invalid_exercise", details={"ids": missing}
        )


def _build_sets(data: WorkoutIn) -> list[WorkoutSet]:
    """Number sets per exercise in the order they were submitted (1, 2, 3, ...)."""
    counters: dict[int, int] = defaultdict(int)
    sets = []
    for s in data.sets:
        counters[s.exercise_id] += 1
        sets.append(
            WorkoutSet(
                exercise_id=s.exercise_id,
                set_number=counters[s.exercise_id],
                reps=s.reps,
                weight=s.weight,
                weight_unit=s.weight_unit.value,
                duration_seconds=s.duration_seconds,
            )
        )
    return sets


def create_workout(db: Session, author: User, member: Member, data: WorkoutIn) -> WorkoutSession:
    _validate(db, data)
    workout = WorkoutSession(
        member_id=member.id,
        performed_on=data.performed_on,
        duration_minutes=data.duration_minutes,
        notes=data.notes,
        created_by_user_id=author.id,
        sets=_build_sets(data),
    )
    db.add(workout)
    db.commit()
    return workout


def replace_workout(db: Session, workout: WorkoutSession, data: WorkoutIn) -> WorkoutSession:
    _validate(db, data)
    workout.performed_on = data.performed_on
    workout.duration_minutes = data.duration_minutes
    workout.notes = data.notes
    workout.sets.clear()
    db.flush()  # delete old sets first so set numbers can be reused
    workout.sets.extend(_build_sets(data))
    db.commit()
    return workout


def delete_workout(db: Session, workout: WorkoutSession) -> None:
    db.delete(workout)
    db.commit()


def get_workout(db: Session, workout_id: int) -> WorkoutSession:
    workout = db.get(WorkoutSession, workout_id)
    if workout is None:
        raise NotFound("Workout not found")
    return workout


def list_workouts(
    db: Session,
    member_id: int,
    date_from: date | None,
    date_to: date | None,
    limit: int,
    offset: int,
) -> tuple[list[WorkoutSession], int]:
    stmt = select(WorkoutSession).where(WorkoutSession.member_id == member_id)
    if date_from:
        stmt = stmt.where(WorkoutSession.performed_on >= date_from)
    if date_to:
        stmt = stmt.where(WorkoutSession.performed_on <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    items = db.scalars(
        stmt.options(selectinload(WorkoutSession.sets).selectinload(WorkoutSet.exercise))
        .order_by(WorkoutSession.performed_on.desc(), WorkoutSession.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(items), total


def progress(db: Session, member_id: int, exercise_id: int) -> dict:
    exercise = db.get(Exercise, exercise_id)
    if exercise is None:
        raise NotFound("Exercise not found")
    rows = db.execute(
        select(WorkoutSession.id, WorkoutSession.performed_on, WorkoutSet)
        .join(WorkoutSet, WorkoutSet.workout_id == WorkoutSession.id)
        .where(WorkoutSession.member_id == member_id, WorkoutSet.exercise_id == exercise_id)
        .order_by(WorkoutSession.performed_on, WorkoutSession.id, WorkoutSet.set_number)
    ).all()
    by_workout: dict[int, dict] = {}
    for workout_id, performed_on, s in rows:
        point = by_workout.setdefault(
            workout_id,
            {
                "workout_id": workout_id,
                "performed_on": performed_on,
                "sets": 0,
                "total_reps": 0,
                "max_weight_kg": None,
                "volume_kg": 0.0,
            },
        )
        kg = to_kg(s.weight, s.weight_unit)
        point["sets"] += 1
        point["total_reps"] += s.reps or 0
        if kg is not None:
            point["max_weight_kg"] = max(point["max_weight_kg"] or 0.0, kg)
            if s.reps:
                point["volume_kg"] += kg * s.reps
    points = list(by_workout.values())
    for p in points:
        p["volume_kg"] = round(p["volume_kg"], 2)
        if p["max_weight_kg"] is not None:
            p["max_weight_kg"] = round(p["max_weight_kg"], 2)
    weights = [p["max_weight_kg"] for p in points if p["max_weight_kg"] is not None]
    return {
        "member_id": member_id,
        "exercise_id": exercise.id,
        "exercise_name": exercise.name,
        "points": points,
        "best_weight_kg": max(weights) if weights else None,
        "disclaimer": DISCLAIMER,
    }
