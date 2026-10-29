# API Reference (summary)

Interactive, always-current docs: run the app and open `/docs`.
All endpoints except login and health need `Authorization: Bearer <token>`.
Errors: `{"error": {"code": "...", "message": "...", "details": ...}}`.

## Auth & users
| Method | Path | Who | Notes |
|---|---|---|---|
| POST | `/api/auth/login` | anyone | `{email, password}` → `{token, expires_at, user}`; 429 after 5 failures/15 min |
| POST | `/api/auth/logout` | any | revokes current token |
| GET | `/api/auth/me` | any | |
| POST | `/api/auth/change-password` | any | signs out other sessions |
| GET/POST | `/api/users` | admin | `?role=trainer` |
| PATCH | `/api/users/{id}` | admin | `{full_name?, is_active?}`; cannot deactivate self |

## Members, plans, memberships
| Method | Path | Who |
|---|---|---|
| GET | `/api/members?q=&status=&limit=&offset=` | admin (all), trainer (assigned) |
| POST | `/api/members` | admin — `{full_name, email?, phone?, assigned_trainer_id?, password?}` |
| GET | `/api/members/me` | member |
| GET / PATCH | `/api/members/{id}` | view: admin/assigned trainer/self · edit: admin |
| POST | `/api/members/{id}/deactivate` · `/reactivate` · `/account` | admin |
| GET | `/api/members/{id}/qr.svg` · `/qr-token` | admin, self |
| POST | `/api/members/{id}/qr/rotate` | admin, self |
| GET / POST | `/api/members/{id}/memberships` | view: as member · add: admin `{plan_id, start_date?}` |
| POST | `/api/memberships/{id}/suspend` · `/resume` · `/cancel` | admin |
| GET / POST / PATCH | `/api/plans` · `/api/plans/{id}` | list: any · write: admin |

Membership `status` in responses is *effective*: `active`, `scheduled`, `expired`, `suspended`, `cancelled`.

## Attendance
| Method | Path | Who |
|---|---|---|
| POST | `/api/attendance/check-in` · `/check-out` | staff — `{qr_token}` or `{member_id}` |
| GET | `/api/attendance/occupancy` | staff |
| POST | `/api/attendance/close-stale` | admin |
| GET | `/api/attendance?member_id=&date_from=&date_to=&open_only=` | scoped by role |
| GET | `/api/attendance/me` | member |

Example: `POST /api/attendance/check-in {"qr_token": "…"}` →
`{"result": "checked_in", "member": {"id": 1, "full_name": "Alex"}, "session": {...}, "closed_stale_session_id": null}`

## Workouts
| Method | Path | Who |
|---|---|---|
| GET / POST | `/api/exercises` | list: any · add: staff |
| GET / POST | `/api/members/{id}/workouts` | admin, assigned trainer, self |
| GET / PUT / DELETE | `/api/workouts/{id}` | same as above |
| GET | `/api/members/{id}/progress?exercise_id=` | same as above |

Workout body: `{performed_on, duration_minutes?, notes?, sets: [{exercise_id, reps?, weight?, weight_unit: kg|lb, duration_seconds?}]}`.
Set numbers are assigned by the server in submission order per exercise.
