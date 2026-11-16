# Deployment requirements

What a production deployment must provide. The application enforces what it
can at start-up (`backend/config/production_checks.py`); the rest is the
operator's responsibility and is listed here. There is no deployment
automation yet (assessment item O-01).

## Settings

Start from `backend/.env.production.example`. With `DJANGO_DEBUG=false` the
application refuses to start unless:

| Setting | Rule |
|---|---|
| `DJANGO_SECRET_KEY` | 50+ random characters, at least 5 distinct, not a placeholder |
| `DJANGO_SECURE_COOKIES` | `true` |
| `DJANGO_ALLOWED_HOSTS` | the real host names; no `*` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://` origins only |
| `DJANGO_TRUSTED_PROXY_COUNT` | set explicitly, at least 1 |
| `DJANGO_SECURE_SSL_REDIRECT` | `true` (default outside debug) |
| `DJANGO_HSTS_SECONDS` | at least 180 days (default one year outside debug) |
| `DJANGO_ADMIN_ENABLED` / `DJANGO_ADMIN_PATH` | admin off, or on at a non-default path |

Set `DJANGO_READ_DOT_ENV=false` so no `.env` file is ever read on a server.
CI runs `manage.py check --deploy --fail-level WARNING` with the example values.

## Reverse proxy

- One origin serves both the built SPA (`frontend/dist`) and `/api/` (and the
  admin path, if enabled). No CORS is configured or needed.
- The **outermost** proxy terminates TLS and must **overwrite** — not append
  to — `X-Forwarded-For` and `X-Forwarded-Proto` received from the internet.
  `DJANGO_TRUSTED_PROXY_COUNT` must equal the number of proxies that append
  to `X-Forwarded-For` before Django. Too high lets clients choose their own
  address (and defeat the sign-in limits); too low makes every client look
  like the proxy (and share one address limit).
- Serve the SPA with its own security headers, for example
  `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'`.
  API responses already carry a stricter policy set by Django.
- If the admin is enabled, allow its path only from the internal network or a
  VPN.

## Database roles

The append-only audit triggers and the ownership triggers can be disabled by
the **owner** of the tables. For them to protect against a compromised
application, use two roles:

| Role | Used by | Privileges |
|---|---|---|
| `merchantflow_owner` | `manage.py migrate` only | owns the schema and tables |
| `merchantflow_app` | the running application | `SELECT, INSERT, UPDATE, DELETE` on tables, `USAGE` on sequences; **not** the owner |

With this split, `apps.audit.maintenance.audit_protection_suspended` fails
with a permission error for the application, as intended. If one role is used
for both, the triggers still stop every ordinary code path (ORM, bulk
operations, raw SQL, `TRUNCATE`), but not someone running SQL as the owner.

## Scheduled jobs

| Command | Frequency | Why |
|---|---|---|
| `manage.py purge_login_attempts` | hourly | removes expired sign-in counters |
| `manage.py clearsessions` | daily | removes expired session rows |

## Health check

`GET /api/health/` is exempt from the HTTPS redirect so a load balancer can
probe it over the internal network. It reveals only whether the database is
reachable.
