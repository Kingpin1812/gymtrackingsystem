# ADR 0002 — Opaque, revocable bearer tokens

**Status:** accepted (2026-10-29)

## Decision
Login returns a random token; the server stores only its SHA-256 hash in `auth_sessions` with an
expiry. The browser keeps it in `sessionStorage` and sends `Authorization: Bearer …`.

## Why not JWT / cookies
- Opaque tokens can be revoked instantly (logout, deactivation, password change). JWTs can't without a denylist.
- Header-based auth is not sent automatically by browsers, so there is no CSRF exposure.
- Trade-off: a successful XSS could read `sessionStorage`. Mitigated by a strict CSP
  (`script-src 'self'`, no inline scripts) and a UI that never uses `innerHTML` with data.
