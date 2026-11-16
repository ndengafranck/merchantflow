# Deployment requirements

What a production deployment must provide. The application enforces what it
can at start-up (`backend/config/production_checks.py`) and with checks you
run during deployment; the rest is infrastructure, listed here, which the
application **cannot verify**. There is no deployment automation yet.

## Environment

`DJANGO_ENVIRONMENT` is required: `development`, `test` or `production`.
Security behaviour follows it, not `DJANGO_DEBUG`:

| Environment | Start-up rules |
|---|---|
| `production` | Every rule below; `DJANGO_DEBUG=true` is itself refused |
| `development`, `test` | Only local host names in `DJANGO_ALLOWED_HOSTS` (localhost, private addresses, single-label names, `.localhost/.local/.internal/.test/.example`), unless `DJANGO_ALLOW_NON_LOCAL_HOSTS=true`. A production site mislabelled `development` therefore fails to start |

Start from `backend/.env.production.example`. With `DJANGO_ENVIRONMENT=production`
the application refuses to start unless:

| Setting | Rule |
|---|---|
| `DJANGO_DEBUG` | `false` |
| `DJANGO_READ_DOT_ENV` | `false` (configuration comes from the environment, never a file left on the server) |
| `DJANGO_SECRET_KEY` | 50+ random characters, at least 5 distinct, not a placeholder |
| `DJANGO_SECURE_COOKIES` | `true` |
| `DJANGO_ALLOWED_HOSTS` | the real host names; no `*` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://` origins only |
| `DJANGO_TRUSTED_PROXY_COUNT` | set explicitly, at least 1 |
| `DJANGO_SECURE_SSL_REDIRECT` | `true` (default in production) |
| `DJANGO_HSTS_SECONDS` | at least 180 days (default one year in production) |
| `DJANGO_ADMIN_ENABLED` / `DJANGO_ADMIN_PATH` | admin off (default in production), or on at a non-default path |

CI runs `manage.py check --deploy --fail-level WARNING` with the example values.

## Reverse proxy (infrastructure; not verifiable by the application)

- One origin serves both the built SPA (`frontend/dist`) and `/api/` (and the
  admin path, if enabled). No CORS is configured or needed.
- The **outermost** proxy terminates TLS and must **overwrite**, not append
  to, `X-Forwarded-For` and `X-Forwarded-Proto` received from the internet.
- `DJANGO_TRUSTED_PROXY_COUNT` must equal the number of proxies that append to
  `X-Forwarded-For` before Django. Too high lets clients choose their own
  address (and defeat the sign-in limits); too low makes every client look
  like the proxy.
- **Django must not be reachable except through that proxy** (bind it to a
  private interface or socket; firewall it). A client that reaches Django
  directly can send any forwarded header it likes.
- Serve the SPA with its own security headers, for example
  `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'`.
  API responses already carry a stricter policy set by Django.
- If the admin is enabled, allow its path only from the internal network or a VPN.

## Database roles

Two roles, neither a superuser:

| Role | Used by | Owns | Privileges |
|---|---|---|---|
| owner (e.g. `merchantflow_owner`) | `migrate`, `grant_runtime_privileges`, maintenance | the database, schema, tables, functions, triggers | everything, as owner |
| runtime (e.g. `merchantflow_runtime`) | the running application (`DATABASE_URL`) | **nothing** | read/write ordinary tables; **SELECT and INSERT only** on `audit_auditevent`; no TRUNCATE, TRIGGER, REFERENCES; no writes to `django_migrations`; no CREATE in the schema |

Because the runtime role owns nothing, it cannot disable or drop the audit
and ownership triggers, and it cannot update, delete or truncate audit rows.

### Provisioning (once, by a database administrator)

Set the passwords in the administrator's session or secret store; never commit them.

```sql
CREATE ROLE merchantflow_owner LOGIN PASSWORD :'owner_password';
CREATE ROLE merchantflow_runtime LOGIN PASSWORD :'runtime_password';
CREATE DATABASE merchantflow OWNER merchantflow_owner;
-- PostgreSQL 15+: PUBLIC cannot create in schema public; verify on older servers:
--   \c merchantflow
--   REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

The runtime role must not be granted membership of the owner role.

### Every deployment

```bash
python manage.py check_workspace_owners                                    # owner URL; before migrating
python manage.py migrate                                                   # owner URL
python manage.py grant_runtime_privileges --role merchantflow_runtime      # owner URL
python manage.py verify_database_roles                                     # runtime URL; must succeed
python manage.py check --deploy --database default --fail-level WARNING    # runtime URL
```

Run the first three with `DATABASE_URL` set to the **owner** role, the last
two with the **runtime** role's `DATABASE_URL` (the one the application uses).
`verify_database_roles` and the deploy check fail if the runtime role is a
superuser, may create roles or databases, owns or is a member of the owner of
any table or function, may create in the schema, has more than SELECT/INSERT
on the audit table, or if a protective trigger is missing or disabled. Re-run
`grant_runtime_privileges` after every migration so new tables are covered.

`backend/scripts/verify_runtime_role_boundaries.py`, run with the runtime
URL, attempts every forbidden action (each rolled back) and reports. CI runs
all of this with separate LOGIN roles (`database-roles` job), and runs the
browser tests with the server connected as the runtime role.

### Remaining trust boundary

Database **superusers**, the owner role, and whoever controls the database
server, its backups or its storage can still bypass every database-level
control (disable triggers, edit files, restore old data). Protect those
credentials and that infrastructure separately; the application cannot.

## Sign-in limits and recovery

Failed sign-ins are limited per account + address, per account, and per
address, but a browser that has signed in to the account before is limited
only by its own counter (OWASP device cookie). A person locked out by someone
else's guessing can therefore still sign in from their usual browser. Other
ways back: wait for the window (15 minutes by default), or an operator runs,
after checking the person's identity:

```bash
python manage.py clear_login_limits --email person@example.com --reason "ticket 123, identity checked"
```

It is audited (`auth.login_limits_cleared`). There is no HTTP unlock.

## Scheduled jobs

| Command | Frequency | Why |
|---|---|---|
| `manage.py purge_login_attempts` | hourly | removes expired sign-in counters |
| `manage.py clearsessions` | daily | removes expired session rows |

## Health check

`GET /api/health/` is exempt from the HTTPS redirect so a load balancer can
probe it over the internal network. It reveals only whether the database is
reachable.

## Repairing workspace ownership

The database requires every workspace to have exactly one active owner
membership and, unless the workspace is archived, that owner's account to be
active. Migration `workspaces.0005` checks existing data before installing
that rule and **refuses to run** (changing nothing) if any workspace breaks it.
It lists each offending workspace by id, name and status, with the owner
membership ids it found.

1. List the problems at any time, read-only:

   ```bash
   python manage.py check_workspace_owners
   ```

2. Repair each workspace by deciding who should own it. Nothing is repaired
   automatically, because choosing an owner is a business decision. Before
   `workspaces.0005` is applied the ownership triggers do not exist yet, so
   the repair is plain SQL by the database owner, in one transaction:

   | Problem | Repair |
   |---|---|
   | No active owner membership | Set exactly one chosen, active member to `role = 'owner'` |
   | More than one owner | Keep the rightful owner; set the others to `role = 'manager'` |
   | Owner account inactive (workspace not archived) | Reactivate the account, or make another active member the owner and the old owner a manager, or set the workspace `status = 'archived'` |

3. Run `check_workspace_owners` again until it reports no problems, then
   `python manage.py migrate`.

After `workspaces.0005` is applied, ownership changes go through
`transfer_ownership` and `deactivate_user`; the triggers refuse anything else.
