# Attendance, QR and Occupancy Policy

## Session lifecycle

A visit is an `attendance_sessions` row. It is **open** while `closed_reason` is NULL.
The database enforces **at most one open session per member** (partial unique index).

| Close reason | When | `check_out_at` |
|---|---|---|
| `checked_out` | Staff checks the member out | real time |
| `stale` | Member never checked out; closed on next check-in or by admin "close stale" | NULL (unknown) |
| `member_deactivated` | Member deactivated while inside | NULL |

## Check-in rules

1. Identify the member by QR token (method `qr`) or member ID (method `manual`) — staff only.
2. Member must be `active`.
3. A membership must be valid **today in the gym's time zone**: stored status `active` and
   `start_date ≤ today ≤ end_date` (both ends inclusive). Suspended, cancelled, expired or
   not-yet-started memberships are rejected (`409 membership_invalid`).
4. If an open session exists and is newer than `STALE_SESSION_HOURS`: return it as
   `already_checked_in` (duplicate scans and network retries are safe).
5. If the open session is older: close it as `stale`, open a new one, and report the stale ID.
6. Concurrent duplicate requests: the unique index rejects the second insert; the API returns the
   first session as `already_checked_in`.

## Check-out rules

- Closes the open session. Membership validity is not required to leave.
- No open session, but the last visit was checked out within `CHECKOUT_DEDUPE_SECONDS`:
  returns it as `already_checked_out` (retry-safe). Otherwise `409 not_checked_in`.

## QR codes

- Encode only a random 24-byte URL-safe token (`members.qr_token`) — no name, ID or email.
- Visible to the member and admins only (not trainers, to prevent impersonated check-ins).
- Rotating issues a new token; the old one immediately returns `404 unknown_qr`.

## Occupancy (an estimate)

`estimated_count` = open sessions with `check_in_at` within the last `STALE_SESSION_HOURS`.
People who leave without checking out are over-counted until their session becomes stale;
people who enter without checking in are not counted. The API always returns `is_estimate: true`
and the UI labels the number "Estimated".
