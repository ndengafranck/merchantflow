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
workspace. This holds for the API (`/api/v1/workspaces/<id>/…`) and, since
D-021, for the SPA (`/w/<id>/…`). The session stores only the workspace used
last, as a landing-page hint.

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
*Superseded in its mechanism by D-017; the principle stands.* Originally sync
requests carried an `X-Device-Id` header and revocation did not end sessions,
which the Milestone 1 review showed to be ineffective (finding H-01).

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

## D-017 Sessions are bound to browser installations (review R5)
Approved model, implemented as follows.

- **`accounts.DeviceInstallation`**: one browser installation of one user.
  The server recognises it by an HttpOnly identifier cookie (`mf_device`)
  that is read **only at login, after the password check**. It is honoured
  only if it names an active installation of the same user; otherwise a new
  installation is created. It never authenticates a request.
- **`accounts.UserSession`**: replaces Django's session table and adds `user`
  and `installation` columns, so sessions can be found and ended by device.
- The API accepts a session only if it is bound to an active installation
  (`accounts.authentication.SessionAuthentication`). A session created any
  other way, for example by the Django admin login, cannot call the API.
- **`workspaces.WorkspaceDevice`**: authorisation of one installation in one
  workspace, unique on the pair. Checked by the workspace guard on every
  request, so revoking it closes the whole workspace to that browser, not
  only synchronisation.
- Revoking an installation deletes its sessions in the same transaction.
- A revoked workspace device is never recreated for that installation.

**Why an identifier cookie and not a stored secret or fingerprint:** a secret
in IndexedDB would be a long-lived credential in script-readable storage;
fingerprinting is unreliable and invasive. An HttpOnly cookie is unreadable to
scripts and survives sign-out.
**Cost:** clearing cookies makes a browser look new. See D-019 for what that
does and does not weaken.

## D-018 Workspace devices are authorised on first entry
No owner approval was requested for now. The first request an installation
makes to a workspace through an active membership creates its
`WorkspaceDevice`. The explicit "register device" endpoint is gone, and the
client no longer names its device: the server takes it from the session,
which removes the spoofing in review finding V-01.

## D-019 What revocation does and does not protect against
Revocation defeats **possession of a browser without the password**: a lost
or stolen phone, or a copied session. It does not defeat a person who knows
the password; they can sign in again, and after clearing cookies their
browser is a new installation that is authorised on first entry (D-018).
Removing a *person* from a workspace is done by suspending or removing their
membership, which no device or cookie can get around. Closing the remaining
gap needs owner approval of new devices (O-020).

## D-020 An installation belongs to its user, not to any workspace
A workspace owner can revoke a member's **workspace device** but not the
member's **installation**, because the installation also carries the user's
access to other workspaces. Users revoke their own installations. This keeps
one tenant from affecting a user's standing in another.

## D-021 The SPA carries the workspace in its URL (review R3)
Screens live under `/w/<workspace-id>/…`. The URL alone decides which
workspace a tab shows; the shell is keyed by workspace so a switch discards
all loaded state. Tabs are independent, links can be shared, and history
works across a switch. The server-side "current workspace" is now only "last
used", for redirecting `/`.

## D-022 The workspace guard is structural (review R1)
- `WorkspaceAPIView.get_permissions()` always returns `IsAuthenticated` and
  `WorkspaceAccess` first; a subclass's `permission_classes` are appended.
- A subclass that defines any of the guard's methods fails at import time.
- A Django system check refuses to start if a route with a `workspace_id` is
  not a `WorkspaceAPIView` or a handler declares no capability.
- Tenant queries start from `self.workspace_queryset(Model)`; workspace-owned
  models extend `WorkspaceOwnedModel`.
- `tests/isolation.py` is a registry of every workspace endpoint. A test
  fails if a route is missing from it, and every entry is run through the
  isolation contract.

## D-023 Services authorise on a re-read, locked actor (review R2)
Every service that acts on behalf of a member calls `authorize_actor`, which
re-reads the membership `FOR UPDATE` and checks membership status, workspace
status, user status and capability. The membership object supplied by the
caller is used only as an identifier. Domain errors live in
`common/exceptions.py` with no framework imports and are mapped to HTTP only
in `common/api_errors.py`; a test enforces that domain modules do not import
the HTTP layer. **Cost:** one extra locked read per write, and operations by
the same actor in one workspace run one at a time.

## D-024 The `devices` app keeps no models
Installations and sessions are identity (`accounts`); workspace device
authorisation is tenant access control (`workspaces`), next to the guard that
enforces it. This keeps dependencies one-directional. `apps.devices` retains
its migration history and serves the device and sync endpoints. It can be
folded away when migrations are squashed.

## D-025 Sign-in limits count failures in PostgreSQL (M2.1, F-01/F-02)
Three counters of failed attempts per 15-minute window: account + address
(5), account (20), address (100). An attempt reserves a failure in each before
the password is checked; correct sign-ins and refused attempts are refunded,
and a success clears that account + address counter. Stored in a table
(`accounts.LoginAttemptBucket`) with atomic upserts rather than Django's cache
because the cache's increment is not atomic across processes and the
database is already shared; no new dependency. Keys are HMACs, so the table
holds no identifiers. **Cost:** someone guessing from 4+ addresses can lock an
account for one window (O-023). One write per sign-in attempt.

## D-026 One trusted-proxy setting decides client addresses
`DJANGO_TRUSTED_PROXY_COUNT` drives `apps.common.net.client_ip`, DRF's
`NUM_PROXIES` and `SECURE_PROXY_SSL_HEADER`. With 0, `X-Forwarded-For` is
ignored entirely. IPv6 clients are limited per /64.

## D-027 The admin is off unless enabled, and cannot change memberships
`DJANGO_ADMIN_ENABLED` (default: debug only) and `DJANGO_ADMIN_PATH`. The
admin sign-in shares the API's failure counters. Memberships are view-only;
roles, statuses and ownership change only through services. Admin edits to
users and workspaces, and passwords set by operators, are audited. An admin
session is not bound to a browser installation and so cannot call the API.

## D-028 Device actions follow role rank (F-04)
Rank: owner 3, manager 2, attendant and affiliate 1. A member may act on their
own devices; acting on another member's device needs `devices.manage` and a
strictly higher rank. Refusals are reported as not found.

## D-029 Removal revokes devices; only explicit re-authorisation restores (F-05)
Removing a member revokes their devices in that workspace with
`revocation_reason = membership_removed`, in the same transaction. Suspension
does not (assessment Q9 default). Reinstatement leaves them revoked; the new
`POST …/devices/{id}/reauthorize/` (rank-checked, audited, refused while the
member is not active or the browser was signed out everywhere) is the only
way back. First-entry authorisation locks the membership so it cannot race a
removal. Supersedes the "a revoked row is final" part of D-017.

## D-030 Audit rows are append-only in PostgreSQL (F-07)
Row triggers refuse `UPDATE`/`DELETE`; a statement trigger refuses
`TRUNCATE`, including cascades. Only the table owner can suspend them; tests
and the e2e seed do so explicitly to wipe throwaway databases. See
DEPLOYMENT.md for the role split that makes this hold against the application.

## D-031 Ownership is checked by the database at commit (F-10/F-11)
Deferred constraint triggers require every workspace to have exactly one
active owner membership whose account is active (archived workspaces are
exempt from the account rule). A trigger refuses deactivating an account
that owns a non-archived workspace. `transfer_ownership` locks the
successor's account row so it serialises with `deactivate_user`.

## D-032 Unsafe production settings stop start-up (F-06)
`config/production_checks.py` lists every violated rule and the settings
module raises `ImproperlyConfigured`. HTTPS redirect and HSTS default on
outside debug; `security.W021` (HSTS preload) is silenced because submitting
to the preload list is an operator decision. `DJANGO_READ_DOT_ENV=false`
stops servers reading stray `.env` files.
