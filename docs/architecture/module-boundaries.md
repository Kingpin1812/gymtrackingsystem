# Module Boundaries

Each module under `app/modules/<name>/` has `models.py`, `schemas.py`, `service.py`, `router.py`.

| Module | Owns | May depend on |
|---|---|---|
| `core` | config, DB engine, errors, security primitives, clock, pagination | nothing in `modules` |
| `auth` | `users`, `auth_sessions`; login/logout; role dependencies | `core` |
| `members` | `members`, `membership_plans`, `memberships`; `access.py` (who may see a member) | `core`, `auth`, `attendance.models` (to close open visits on deactivation) |
| `attendance` | `attendance_sessions`; check-in/out, occupancy | `core`, `auth`, `members` (validity + access) |
| `workouts` | `exercises`, `workout_sessions`, `workout_sets`; progress | `core`, `auth`, `members.access` |

Rules:

- No module imports another module's `router`.
- Member-level access is decided only in `members/access.py` — never re-implemented.
- `app/models.py` imports all models so Alembic sees the full schema.
- There are no import cycles (`members.service` imports only `attendance.models`, not its service).
