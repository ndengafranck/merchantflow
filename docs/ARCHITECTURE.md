# Architecture

This document describes what is implemented today (Milestones 0 and 1) and the
rules later milestones must follow.

## Shape of the system

A modular monolith: one Django project, one PostgreSQL database, one React
single-page application.

```
Browser (React SPA) ──same origin──> /api/* ──> Django + DRF ──> PostgreSQL
```

The SPA and the API are always served from **one origin**: in development
through the Vite proxy, in production through a reverse proxy that serves the
built SPA and forwards `/api/` and `/admin/` to Django. This is a deliberate
constraint, because it is what makes cookie authentication simple and safe
(see below). No CORS is configured.

```
merchantflow/
├── backend/
│   ├── config/            settings (environment driven), root URLs
│   ├── apps/
│   │   ├── common/        base models, error format, health check, session auth class
│   │   ├── accounts/      User, login, logout, current user
│   │   ├── workspaces/    Workspace, memberships, policies, tenant isolation
│   │   ├── devices/       Device registration, revocation, sync gate
│   │   └── audit/         append-only audit events
│   └── tests/             pytest suite (runs on PostgreSQL)
├── frontend/
│   └── src/
│       ├── api/           the only code that performs HTTP
│       ├── session/       who is signed in, which workspace
│       ├── components/    shell and shared states
│       └── pages/         login, workspace choice, dashboard placeholder
└── docs/
```

## Domain boundaries

| App | Owns | May depend on |
|---|---|---|
| `common` | Abstract models, API error format, authentication class | nothing |
| `accounts` | Identity: who a person is and how they prove it | `common` |
| `audit` | Record of actions | `common` (references users and workspaces by key) |
| `workspaces` | Tenants, roles, capabilities, access resolution | `accounts`, `audit`, `common` |
| `devices` | Devices and the synchronisation gate | `workspaces`, `audit`, `common` |

Future domain apps (catalogue, orders, payments, commissions, inventory,
sync, import/export) depend on `workspaces` for isolation and never on each
other's internals: they call each other's service functions.

### Layers inside an app

| Layer | File | Responsibility |
|---|---|---|
| HTTP | `views.py` | Parse the request, call a service, shape the response |
| Input | `serializers.py` | Validate and normalise request data |
| Business | `services.py` | The operation: transaction, locking, rules, audit event |
| Policy | `workspaces/policies.py` | Which role holds which capability |
| Data | `models.py` | Structure and database constraints |

Views contain no business rules. Services re-check the actor's authority, so
a rule holds for any caller (HTTP today; sync replay and imports later).

## Authentication

First-party browser authentication with **server-side sessions**:

- Login verifies the password and creates a session. The browser receives the
  session identifier in a cookie that is `HttpOnly` (JavaScript cannot read
  it), `SameSite=Lax`, and `Secure` whenever `DJANGO_SECURE_COOKIES=true`.
- Nothing is stored in `localStorage` or `sessionStorage`; an ESLint rule
  forbids both.
- **CSRF:** every state-changing request must carry an `X-CSRFToken` header
  matching the CSRF cookie. DRF enforces this for authenticated requests; the
  login view enforces it explicitly, because an anonymous login request would
  otherwise be exempt (login CSRF). Django also rejects requests whose
  `Origin` is not trusted.
- Logout deletes the server-side session, so the cookie is immediately worthless.
- Failed logins return one identical 401 for wrong password, unknown email and
  disabled account, and are rate limited per IP address.
- Passwords use Django's default PBKDF2 hashing and validators (minimum 10
  characters, not common, not numeric, not similar to the user's details).
- Users are identified by email, compared case-insensitively.

Alternative considered: bearer tokens (JWT). Rejected for the browser because
a token readable by JavaScript is exposed to any script injection and cannot
be revoked without extra server state. If a native mobile client is ever
built, it should get its own token mechanism instead of weakening this one.

## Workspace isolation

Every business record will carry a `workspace` foreign key. Isolation is
enforced on the server in three steps:

1. **The workspace is named in the URL**: `/api/v1/workspaces/<workspace_id>/…`.
   The identifier is a claim, not a fact.
2. **`resolve_membership`** (`workspaces/access.py`) looks for an *active*
   membership linking the authenticated user to that workspace. No membership,
   or an unknown workspace, gives the same `404`, so identifiers cannot be
   probed. An inactive workspace gives `403`.
3. **The view declares a capability** and the role must hold it, otherwise `403`.

All workspace-scoped endpoints extend `WorkspaceAPIView`, which performs steps
2 and 3 before any handler runs and **fails closed**: an endpoint that declares
no capability raises an error instead of being reachable.

Handlers then query only through `request.workspace`. A record identifier from
another tenant combined with the caller's own workspace identifier therefore
finds nothing (`404`). The test suite covers this case explicitly.

A user's "current workspace" is stored in the session as a convenience for
restoring the UI. It is never used for authorisation.

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
database guarantees at most one owner per workspace and that the owner is
never suspended or removed. Workspaces are only created by
`create_workspace`, which creates the owner membership in the same
transaction. Ownership changes only through `transfer_ownership`.

## Devices

A device is a browser installation registered by one user for one workspace.
Synchronisation endpoints require, in addition to the session, an
`X-Device-Id` header naming an active device that belongs to the same user and
workspace. A revoked device is refused with `device_revoked`. The device
identifier is not a credential: the session authenticates, the device attributes.

Only the gate and a handshake endpoint exist. The operation queue, IndexedDB
storage and the service worker belong to the offline milestone.

## Database design principles

- PostgreSQL only; the application refuses to start on another engine.
- UUID primary keys on business records (offline devices can create them).
- Invariants are database constraints first, service checks second.
- Financial and operational history is never deleted: foreign keys use
  `PROTECT`, records are archived through status fields.
- Operations that reason about existing rows lock them (`select_for_update`)
  inside a transaction.
- Money will be `Decimal` / `NUMERIC`; no floating point.
- Timestamps are stored in UTC.
- Every security-relevant change writes an `AuditEvent` in the same transaction.

## API conventions

- Versioned under `/api/v1/`. OpenAPI schema at `/api/schema/`, Swagger UI at
  `/api/docs/` (enabled by `API_DOCS_ENABLED`, on by default only in debug).
- Errors always have the shape `{"code", "detail", "errors"?}`.
- `401` not signed in, `403` signed in but not allowed, `404` not found or not
  yours, `409` valid request but wrong state, `429` rate limited.
