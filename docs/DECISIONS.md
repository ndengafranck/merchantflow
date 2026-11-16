# Technical decisions

Newest last. Each entry: the decision, why, and what it costs.

## D-001 Session cookies, not tokens, for the browser
HttpOnly session cookie plus CSRF token. Credentials are unreachable from
JavaScript and sessions are revocable server-side. **Cost:** the SPA and API
must share an origin; a future native client needs a separate mechanism.

## D-002 Email is the login identifier
Unique, case-insensitive, stored lower-cased. Phone is an optional profile
field. **Cost:** affiliates without email cannot have an account yet; see
OPEN_DECISIONS O-001.

## D-003 Ownership is a membership role, not a column
No `Workspace.owner` field. Partial unique constraint (one `owner` per
workspace) and a check constraint (owner is always `active`). **Cost:** "a
workspace has at least one owner" cannot be a plain constraint; it is
guaranteed by the creation and transfer services and by disabling deletion in
the admin. A direct SQL delete of the owner row would break it.

## D-004 Exactly one owner per workspace
The brief speaks of "the owner". Co-ownership can be added by relaxing one
constraint; removing it later would be much harder.

## D-005 Workspace in the URL, verified on every request
Rather than an implicit "current workspace" in the session. Explicit, works
across tabs, and suits offline replay where each operation names its
workspace. The session-stored selection is UI convenience only.

## D-006 Non-members get 404, not 403
A 403 would confirm that a workspace identifier exists.

## D-007 Capabilities, not role checks
Views and services ask `has_capability`. The role-to-capability map is one
file, so owner-granted manager permissions (O-002) change one place.

## D-008 UUIDv4 primary keys
Required for offline creation. Version 4 because Python 3.13 has no built-in
UUIDv7. **Cost:** random keys fragment indexes on very large tables; revisit
with time-ordered UUIDs if a table grows large enough to matter.

## D-009 Devices are identifiers, not credentials
Sync requests need session + `X-Device-Id`. No device secret is issued,
because a long-lived secret in IndexedDB would be exactly the kind of stored
credential the security rules forbid. **Cost:** revoking a device blocks
synchronisation from it but does not end that browser's login session; see
Known limitations in IMPLEMENTATION_PLAN.

## D-010 No public sign-up, no invitation API yet
Accounts and memberships are created by management commands. Who may create a
workspace, and how staff and affiliates are invited, are product decisions
(O-003). The services (`register_user`, `create_workspace`, `add_member`)
exist and are tested, so the API is a thin addition later.

## D-011 PostgreSQL everywhere, including tests
SQLite is not supported. Constraints and row locking are the product's
integrity mechanism and must be tested on the engine that runs them.

## D-012 One settings module, configured by environment
No `settings/dev.py` and `settings/prod.py` to drift apart. The app refuses to
start in non-debug mode with the placeholder secret key.

## D-013 Money will be Decimal
The first MVP sketch used integer XAF. The approved rule is Decimal, which
also covers percentage commissions and any future currency with minor units.
No money fields exist yet.

## D-014 Service worker deferred
A web manifest is in place. The service worker ships with the offline
milestone, together with its cache-update strategy; a hastily added one
causes stale-application bugs that are hard to recover from in the field.

## D-015 Minimal dependencies
Backend: Django, DRF, drf-spectacular (OpenAPI was required), django-environ
(.env and `DATABASE_URL` parsing), psycopg. Frontend runtime: React and
react-router-dom only. No UI or state-management library.

## D-016 Login rate limit uses the default in-process cache
Enough for a single-process pilot. With several server processes the limit is
per process; move the cache to Redis or the database before scaling out.
