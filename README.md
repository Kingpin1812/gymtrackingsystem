# GymTrack AI

Gym management and fitness tracking: members, membership plans, QR check-in/check-out,
occupancy estimates, and workout/progress logging, with admin / trainer / member roles.

Built as a **modular monolith**: one FastAPI app, one SQLite database, plain HTML/JS front end.
No Docker, Redis, queues or external services are needed to run it.

> Status: core MVP (roadmap phases 1–7). Not production-ready — see *Limitations*.

## Quick start (Windows, from this `gymtrack` folder)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
copy .env.example .env                       # then edit GYMTRACK_TIMEZONE if needed
.venv\Scripts\python -m alembic upgrade head # create / upgrade the database
.venv\Scripts\python -m app.cli seed-exercises
.venv\Scripts\python -m app.cli create-admin --email you@example.com --name "Your Name"
.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000 and sign in. API docs: http://127.0.0.1:8000/docs

If `pip install` fails with `CERTIFICATE_VERIFY_FAILED` (common behind antivirus/proxy HTTPS
inspection), add `--use-feature=truststore` so pip uses the Windows certificate store.

**Demo data instead of a real admin** (synthetic accounts, only on an empty database):

```powershell
.venv\Scripts\python -m app.cli seed-demo
```

Logins `admin@example.com`, `trainer@example.com`, `member@example.com`, password
`demo-password-123`. Never use the demo data in a real gym.

## Everyday commands

| Task | Command |
|---|---|
| Run tests | `.venv\Scripts\python -m pytest` |
| Lint | `.venv\Scripts\python -m ruff check .` |
| Back up the database | `.venv\Scripts\python -m app.cli backup-db` (writes `data/backups/`) |
| Apply new migrations | back up first, then `.venv\Scripts\python -m alembic upgrade head` |
| Roll back one migration | `.venv\Scripts\python -m alembic downgrade -1` (restore a backup if data was removed) |

## Who can do what

| | Admin | Trainer | Member |
|---|---|---|---|
| Manage staff, plans, members, memberships | ✅ | — | — |
| View members | all | assigned to them | self only |
| Check members in/out, see occupancy | ✅ | ✅ (front desk) | — |
| View/log workouts & progress | all | assigned members | own |
| See / replace a member's QR code | ✅ | — | own |

All rules are enforced by the API. Records a user may not see return **404**, so IDs can't be probed.

## Configuration

See `.env.example`. Key settings: `GYMTRACK_TIMEZONE` (membership dates and "today"),
`GYMTRACK_STALE_SESSION_HOURS` (forgotten check-outs), `GYMTRACK_SESSION_HOURS` (login lifetime).

## Project layout

```
app/
  core/          config, database, errors, security, clock, pagination
  modules/
    auth/        users, login sessions, roles
    members/     members, plans, memberships, access rules
    attendance/  check-in/out, occupancy
    workouts/    exercises, workouts, sets, progress
  static/        web UI (index.html, app.js, styles.css)
  cli.py         admin commands
migrations/      Alembic versioned schema migrations
tests/           pytest suite (disposable SQLite per test)
docs/            architecture, decisions (ADRs), API, policies
```

## Limitations (honest list)

- Single gym only (no multi-tenant isolation). Adding gyms needs a schema change — see ADR 0001.
- Login rate limiting is in-memory: correct for one server process, not for several.
- No payments, notifications, AI coach, MCP tools, trainer scheduling, equipment or analytics yet.
- QR scanning relies on a USB/Bluetooth scanner (which "types" the code) or manual entry; there is
  no in-browser camera scanner.
- No HTTPS by itself — put it behind a TLS-terminating reverse proxy before exposing it.
- The web UI was checked for syntax and served successfully, and the API was exercised end-to-end,
  but the UI has no automated browser tests yet.
