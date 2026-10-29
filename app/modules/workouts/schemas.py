from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.auth.schemas import clean_name
from app.modules.workouts.models import WeightUnit

MAX_WEIGHT = 1000  # in the given unit; generous upper bound to reject typos like 8000
MAX_REPS = 1000
MAX_SET_SECONDS = 24 * 3600


class ExerciseCreate(BaseModel):
    name: str = Field(max_length=80)
    category: str = Field(max_length=40)

    @field_validator("name", "category")
    @classmethod
    def check_text(cls, v: str) -> str:
        return clean_name(v)


class ExerciseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    category: str
    is_active: bool


class SetIn(BaseModel):
    exercise_id: int
    reps: int | None = Field(default=None, ge=0, le=MAX_REPS)
    weight: float | None = Field(default=None, ge=0, le=MAX_WEIGHT)
    weight_unit: WeightUnit = WeightUnit.KG
    duration_seconds: int | None = Field(default=None, ge=0, le=MAX_SET_SECONDS)

    @model_validator(mode="after")
    def has_measurement(self):
        if self.reps is None and self.duration_seconds is None:
            raise ValueError("Each set needs reps or duration_seconds")
        return self


class WorkoutIn(BaseModel):
    performed_on: date
    duration_minutes: int | None = Field(default=None, gt=0, le=1440)
    notes: str | None = Field(default=None, max_length=2000)
    sets: list[SetIn] = Field(min_length=1, max_length=200)


class SetOut(BaseModel):
    id: int
    exercise_id: int
    exercise_name: str
    set_number: int
    reps: int | None
    weight: float | None
    weight_unit: str
    duration_seconds: int | None


class WorkoutOut(BaseModel):
    id: int
    member_id: int
    performed_on: date
    duration_minutes: int | None
    notes: str | None
    created_by_user_id: int | None
    sets: list[SetOut]


class ProgressPoint(BaseModel):
    performed_on: date
    workout_id: int
    sets: int
    total_reps: int
    max_weight_kg: float | None
    volume_kg: float  # sum of reps x weight (kg) over sets that have both


class ProgressOut(BaseModel):
    member_id: int
    exercise_id: int
    exercise_name: str
    points: list[ProgressPoint]
    best_weight_kg: float | None
    disclaimer: str
