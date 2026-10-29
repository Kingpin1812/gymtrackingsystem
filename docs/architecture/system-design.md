# GymTrack AI — System Design

## Context

The instruction set assumed an existing `openGym` repository. None was present in the
workspace and no URL was provided, so the owner chose to **build fresh**. Stack (owner-approved):
Python 3.11, FastAPI, SQLAlchemy 2, Alembic, SQLite, vanilla HTML/JS.

## Shape

```
Browser (static HTML/JS)  ──HTTP/JSON, Bearer token──▶  FastAPI app
                                                          │
                                   routers (transport: parse, auth deps, shape responses)
                                                          │
                                   services (business rules, transactions)
                                                          │
                                   SQLAlchemy models  ──▶  SQLite (file)
```

- **One process, one database.** No queues, caches or background workers: nothing measured needs them.
- **Routers stay thin.** Validation of request shape happens in Pydantic schemas; business rules
  (membership validity, duplicate scans, overlap checks) live in `service.py` modules.
- **Authorization** is a FastAPI dependency (`require_admin`, `require_staff`) plus record-level
  checks in `members/access.py`, reused by every module that touches member data.

## Cross-cutting decisions

| Concern | Decision |
|---|---|
| Auth | Opaque random bearer tokens; only SHA-256 hashes stored; revocable; 12 h expiry. Bearer header (not cookies) means no CSRF surface. |
| Passwords | `hashlib.scrypt` (stdlib), per-user salt, constant-time compare, dummy hash for unknown emails. |
| Errors | Always `{"error": {"code", "message", "details"}}`. 500s are logged server-side, generic to client. |
| Time | Timestamps stored UTC. Calendar concepts (membership dates, "today", report day ranges) use `GYMTRACK_TIMEZONE`. `app/core/clock.py` is the single source of now. |
| Pagination | `limit` (≤200) / `offset`, response `{items, total, limit, offset}`. |
| Headers | CSP `default-src 'self'` (no inline scripts), `nosniff`, `X-Frame-Options: DENY`, `no-store` on API. |
| Migrations | Alembic, batch mode for SQLite. A test asserts migrations == models and downgrade is clean. |
| Logging | stdlib logging; never logs passwords, tokens or request bodies. |

## Deferred (and why)

- **Multi-gym tenancy** — not required for one gym; would add a `gym_id` to every table and query.
- **Docker/NGINX** — not needed to run locally; add with deployment (roadmap phase 14).
- **PostgreSQL** — SQLite handles a single gym comfortably. Models avoid SQLite-only features
  (the partial unique index also declares `postgresql_where`), so a later move is a migration, not a rewrite.
- **Notifications, AI coach, MCP** — optional phases needing provider/privacy decisions.
