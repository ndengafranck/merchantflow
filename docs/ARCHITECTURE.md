# Architecture

This document describes what is implemented today (Milestones 0 and 1, the
corrections from the Milestone 1 review, and M2.1 security hardening) and the rules later milestones
must follow.

## Shape of the system

A modular monolith: one Django project, one PostgreSQL database, one React
single-page application.

```
Browser (React SPA) ──same origin──> /api/* ──> Django + DRF ──> PostgreSQL
```

The SPA and the API are always served from **one origin**: in development
through the Vite proxy, in production through a reverse proxy that serves the
built SPA and forwards `/api/` and `/admin/` to Django. This is a deliberate
constraint, because it is what makes cookie authentication simple and safe.
No CORS is configured.

```
merchantflow/
├── backend/
│   ├── config/            settings (environment driven), root URLs
│   ├── apps/
│   │   ├── common/        base models, domain errors, API error format, health check
│   │   ├── accounts/      User, browser installations, sessions, login, logout
│   │   ├── workspaces/    Workspace, memberships, workspace devices, policies, the guard
│   │   ├── devices/       HTTP endpoints for workspace devices and the sync handshake
│   │   └── audit/         append-only audit events
│   ├── scripts/           e2e_seed.py (throwaway database for browser tests)
│   └── tests/             pytest suite (runs on PostgreSQL)
├── frontend/
│   ├── src/
│   │   ├── api/           the only code that performs HTTP
│   │   ├── session/       who is signed in and what they may enter
│   │   ├── components/    shell, workspace route, shared states
│   │   └── pages/         login, workspace choice, dashboard placeholder
│   └── e2e/               Playwright browser tests against the real stack
└── docs/
```

## Domain boundaries

Dependencies point one way only.

| App | Owns | May depend on |
|---|---|---|
| `common` | Abstract models, domain errors, API error format | nothing |
| `audit` | Record of actions | `common` |
| `accounts` | Identity: users, browser installations, sessions | `common`, `audit` |
| `workspaces` | Tenants, roles, capabilities, workspace devices, the access guard | `accounts`, `audit`, `common` |
| `devices` | HTTP surface for workspace devices and sync (no models) | `workspaces`, `accounts` |

Future domain apps (catalogue, orders, payments, commissions, inventory,
sync, import/export) depend on `workspaces` for isolation and never on each
other's internals: they call each other's service functions.

### Layers inside an app

| Layer | Files | Responsibility |
|---|---|---|
| HTTP | `views.py`, `access.py`, `authentication.py` | Parse the request, call a service, shape the response |
| Input | `serializers.py` | Validate and normalise request data |
| Business | `services.py`, `device_services.py`, `installations.py` | The operation: transaction, locking, rules, audit event |
| Policy | `workspaces/policies.py` | Which role holds which capability |
| Read side | `selectors.py`, `context.py` | Shared lookups |
| Data | `models.py` | Structure and database constraints |

Rules, each enforced by a test in `tests/test_architecture.py`:

- Business, policy, read-side and data modules **do not import the HTTP
  layer** (`rest_framework`, `django.http`). They raise the `DomainError`
  family from `common/exceptions.py`. `common/api_errors.py` is the only place
  that turns those into HTTP responses.
- Views contain no business rules.

### How services authorise

A service that acts for a member receives the acting membership and treats it
only as an identifier. Inside its transaction it calls `authorize_actor`,
which re-reads that membership `FOR UPDATE` and refuses unless the membership
is active, the workspace is active, the user is active and the role holds the
capability. The lock is held to commit, so the actor cannot be demoted or
removed while the operation runs. A membership object loaded before a role
change therefore confers nothing.

## Authentication

First-party browser authentication with **server-side sessions bound to a
browser installation**.

- Login verifies the password, creates a session and binds it to this
  browser's `DeviceInstallation`. The browser receives the session identifier
  in a cookie that is `HttpOnly`, `SameSite=Lax`, and `Secure` whenever
  `DJANGO_SECURE_COOKIES=true`.
- Nothing is stored in `localStorage` or `sessionStorage`; an ESLint rule
  forbids both.
- **CSRF:** every state-changing request must carry an `X-CSRFToken` header
  matching the CSRF cookie. DRF enforces this for authenticated requests; the
  login view enforces it explicitly, because an anonymous login request would
  otherwise be exempt. Django also rejects requests whose `Origin` is not trusted.
- Logout deletes the server-side session.
- Failed logins return one identical 401 for wrong password, unknown email and
  disabled account.
- **Guessing limits** (`accounts/login_protection.py`): failed attempts are
  counted in PostgreSQL per account + address, per account, and per address,
  shared by every process. A browser that has already signed in to the
  account (device cookie) is limited only by its own counter, so strangers
  cannot lock the real user out of their usual browser. An attempt reserves
  its failures in one SQL statement before the password is checked, so
  concurrent requests cannot exceed a limit; successes never count. Over a limit the password is not checked and the answer is 429. The
  client address comes from `common/net.py`, which trusts `X-Forwarded-For`
  only for `DJANGO_TRUSTED_PROXY_COUNT` proxies.
- The Django admin (off unless `DJANGO_ADMIN_ENABLED`) signs in through the
  same limits; its sessions are not bound to an installation and cannot call
  the API.
- Passwords use Django's default PBKDF2 hashing and validators.
- Users are identified by email, compared case-insensitively.

### Browser installations and sessions

| Record | Meaning |
|---|---|
| `DeviceInstallation` | One browser installation of one user |
| `UserSession` | A login session; knows its user and its installation |
| `WorkspaceDevice` | That installation's authorisation in one workspace |

- The server recognises a returning browser by the `mf_device` cookie: an
  HttpOnly **identifier, not a credential**. It is read only at login, after
  the password check, and is honoured only if it names an active installation
  of the same user. Anything else yields a new installation. It never
  authenticates a request.
- The API accepts a session only if it is bound to an **active** installation,
  which becomes `request.auth`. A session with no installation (for example
  one from the Django admin login) or a revoked one gets 401.
- One installation serves all of a user's workspaces. Belonging to several
  workspaces does not create several installations.
- **Revoking an installation** (by its user) deletes its sessions in the same
  transaction. That browser is signed out everywhere.
- **Revoking a workspace device** closes that one workspace to that browser.
  The session and the user's other workspaces are unaffected. A member may
  revoke their own devices; revoking someone else's needs `devices.manage`
  and a strictly higher role rank (owner > manager > attendant/affiliate).
- **Removing a member** revokes their devices in that workspace in the same
  transaction. Reinstatement does not restore them.
- A revoked workspace device is never recreated by use. Only an explicit,
  rank-checked, audited **re-authorisation** reactivates it.
- An owner cannot revoke a member's installation, because it also carries the
  member's access to other workspaces.
- What this does not cover is stated in DECISIONS D-019.

## Workspace isolation

Every business record carries a `workspace` foreign key (models extend
`WorkspaceOwnedModel`). Isolation is enforced on the server:

1. **The workspace is named in the URL**: `/api/v1/workspaces/<workspace_id>/…`.
   The identifier is a claim, not a fact.
2. **Membership.** The guard looks for an *active* membership linking the
   authenticated user to that workspace. No membership, or an unknown
   workspace, gives the same `404`. An inactive workspace gives `403`.
3. **Device.** The session's installation must hold an unrevoked
   `WorkspaceDevice` for this workspace (created on first entry), else `403
   device_not_authorized`.
4. **Capability.** The view declares a capability and the role must hold it,
   otherwise `403`.

Handlers then query through `self.workspace_queryset(Model)`. A record
identifier from another tenant combined with the caller's own workspace
identifier finds nothing (`404`).

### The guard cannot be skipped by accident

| Mechanism | What it prevents |
|---|---|
| `WorkspaceAPIView.get_permissions()` always puts `IsAuthenticated` and `WorkspaceAccess` first; a subclass's `permission_classes` only add checks | A subclass replacing the guard by setting `permission_classes` |
| `__init_subclass__` raises if a subclass defines `get_permissions`, `check_permissions`, `initial`, `authentication_classes` and related hooks | A subclass overriding the machinery |
| System check `workspaces.E001` | A route with `workspace_id` served by anything other than a `WorkspaceAPIView` |
| System check `workspaces.E002` | A handler with no declared capability |
| `tests/isolation.py` registry plus `test_architecture.py` | A new workspace endpoint that has not been put through the isolation contract |
| `test_isolation.py` | Each endpoint: anonymous 401, unbound session 401, non-member 404, another tenant's owner 404, suspended member 404, foreign record id 404, revoked device 403, and no data changed |

The system checks run at server start, in `manage.py check` and in CI.

### Roles and capabilities

Code asks about capabilities, not role names. The map lives in one file.

| Capability | Owner | Manager | Attendant | Affiliate |
|---|:-:|:-:|:-:|:-:|
| `workspace.view` | ✓ | ✓ | ✓ | ✓ |
| `devices.use` (own devices) | ✓ | ✓ | ✓ | ✓ |
| `devices.manage` (any device) | ✓ | ✓ | | |
| `members.view` | ✓ | ✓ | | |
| `members.manage` | ✓ | | | |

### Ownership

Ownership has one source of truth: the membership with role `owner`. The
database guarantees, at every commit, that each workspace has exactly one
active owner membership and (unless the workspace is archived) that the
owner's account is active; an owner's account cannot be deactivated. These are
PostgreSQL triggers, so they hold for the admin, raw SQL and future code alike. Workspaces are only created by
`create_workspace`, which creates the owner membership in the same
transaction. Ownership changes only through `transfer_ownership`.

## Frontend routing

| Path | Screen |
|---|---|
| `/login` | Login. After signing in, returns to the page that was asked for |
| `/` | Redirects to the workspace used last, the only workspace, or the chooser |
| `/workspaces` | Workspace chooser (plain links to `/w/<id>`) |
| `/w/<workspace-id>/…` | Everything inside a workspace |

The URL is the single source of truth for which workspace a tab shows. The
shell is keyed by workspace id, so moving between workspaces discards all
state loaded for the previous one. Tabs do not affect each other. The server
only remembers the workspace used last, to choose where `/` leads.

## Database design principles

- PostgreSQL only; the application refuses to start on another engine.
- UUID primary keys on business records (offline devices can create them).
- Invariants are database constraints first, service checks second.
- Financial and operational history is never deleted: foreign keys use
  `PROTECT`, records are archived through status fields.
- Operations that reason about existing rows lock them inside a transaction,
  in one fixed order for membership and device changes: workspace, then
  memberships by primary key, then devices, then accounts
  (`workspaces/locking.py`). Authorisation is decided on the locked rows.
- The application connects as a **runtime role that owns nothing** (only
  SELECT/INSERT on the audit table); migrations run as a separate owner role
  (DEPLOYMENT.md, "Database roles"). `verify_database_roles` checks it.
- Every write goes through a transactional service function
  (`ATOMIC_REQUESTS` is off on purpose).
- Money will be `Decimal` / `NUMERIC`; no floating point.
- Timestamps are stored in UTC.
- Membership, device, installation and workspace changes made through the
  services write an `AuditEvent` in the same transaction, as do sign-in,
  sign-out, account lock-outs and edits made in the Django admin.
- Audit rows are append-only: PostgreSQL triggers refuse `UPDATE`, `DELETE`
  and `TRUNCATE`. Only the table owner can suspend them (see DEPLOYMENT.md).
- `DJANGO_ENVIRONMENT` (required) selects the start-up rules: with
  `production` the application refuses to start on unsafe settings, including
  `DEBUG=true` (`config/production_checks.py`).

## API conventions

- Versioned under `/api/v1/`. OpenAPI schema at `/api/schema/`, Swagger UI at
  `/api/docs/` (enabled by `API_DOCS_ENABLED`, on by default only in debug).
- Errors always have the shape `{"code", "detail", "errors"?}`.
- `401` not signed in or session not bound to an active device, `403` signed
  in but not allowed, `404` not found or not yours, `409` valid request but
  wrong state, `429` rate limited.
