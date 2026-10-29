# ADR 0001 — Modular monolith on FastAPI + SQLite, single gym

**Status:** accepted (2026-10-29)

## Context
No existing openGym code was available. The owner chose a fresh FastAPI + SQLite build and the
core MVP scope (phases 1–7). Instructions require the smallest maintainable design.

## Decision
- One FastAPI application with domain modules (auth, members, attendance, workouts).
- SQLite file database via SQLAlchemy 2 with Alembic migrations.
- Single gym; no `gym_id` tenancy column.
- Static vanilla-JS front end served by the same app (no Node build step).

## Consequences
- Runs with only Python installed; trivial backup (`app.cli backup-db`).
- SQLite serialises writes — fine for one gym's front desk, not for many concurrent gyms.
- Multi-gym support later requires adding `gym_id` to members/plans/users and scoping every
  query (extend `members/access.py`), plus cross-gym isolation tests.
