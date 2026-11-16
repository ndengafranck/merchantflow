# MerchantFlow

Social commerce and affiliate sales management for merchants who sell through
WhatsApp, Facebook and independent sellers. MerchantFlow tells a merchant who
brought each customer, what was ordered, whether the sale was completed and
paid, and what commission is owed. Initial market: Cameroon (XAF).

**Status:** Milestone 0 (foundation) and Milestone 1 (identity and
workspaces) are implemented, together with the corrections from the
Milestone 1 review. There are no product, order or commission features yet. See [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

| Document | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Structure, domain boundaries, authentication, tenant isolation |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Technical decisions and why |
| [docs/OPEN_DECISIONS.md](docs/OPEN_DECISIONS.md) | Unresolved business rules |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Milestones and acceptance criteria |
| [docs/MILESTONE_1_REVIEW.md](docs/MILESTONE_1_REVIEW.md) | Architecture review and the status of each finding |
| [docs/MILESTONE_2_ASSESSMENT.md](docs/MILESTONE_2_ASSESSMENT.md) | Milestone 2 assessment, security findings and their status |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | What a production deployment must provide |

## Prerequisites

- Python 3.12 or newer (developed on 3.13)
- Node.js 20 or newer (developed on 22)
- PostgreSQL 16, either through Docker Compose or installed locally

## Installation

```bash
git clone <repository-url> merchantflow && cd merchantflow
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements-dev.txt
(cd frontend && npm ci)
```

`make install` does the same.

## Environment configuration

```bash
cp backend/.env.example backend/.env
```

`backend/.env` is ignored by Git. The example values work for local
development as they are. Every variable is described in
[backend/.env.example](backend/.env.example); for anything other than local
development you must set a real `DJANGO_SECRET_KEY` (the application refuses
to start with the placeholder when `DJANGO_DEBUG=false`), `DJANGO_ALLOWED_HOSTS`,
`DJANGO_CSRF_TRUSTED_ORIGINS` and `DJANGO_SECURE_COOKIES=true`.

The frontend needs no environment file and holds no secrets.

## Database setup

**Option A: Docker Compose**

```bash
docker compose up -d db
```

If port 5432 is already in use, choose another: `POSTGRES_PORT=5433 docker compose up -d db`
and use the same port in `DATABASE_URL`.

**Option B: an existing PostgreSQL**

```bash
sudo -u postgres psql -c "CREATE ROLE merchantflow LOGIN CREATEDB PASSWORD 'merchantflow_dev'"
sudo -u postgres psql -c "CREATE DATABASE merchantflow OWNER merchantflow"
```

`CREATEDB` lets the test runner create its throwaway `test_merchantflow` database.

Then apply migrations and create a first workspace with its owner:

```bash
cd backend
.venv/bin/python manage.py migrate
.venv/bin/python manage.py create_workspace --name "My Shop" --owner-email you@example.com --owner-name "Your Name"
```

The command prompts for the owner's password (minimum 10 characters). Until
the invitation flow exists, add further members with:

```bash
.venv/bin/python manage.py add_member --workspace my-shop --email seller@example.com --name "Seller Name" --role affiliate
```

Roles: `manager`, `attendant`, `affiliate`. Use only fictional people in
development data.

## Running the backend

```bash
cd backend && .venv/bin/python manage.py runserver 127.0.0.1:8000
```

- Health check: http://127.0.0.1:8000/api/health/
- API documentation (when `DJANGO_DEBUG=true`): http://127.0.0.1:8000/api/docs/
- Internal admin: http://127.0.0.1:8000/admin/ (needs `manage.py createsuperuser`;
  routed only when `DJANGO_ADMIN_ENABLED` is true, which defaults to the value of `DJANGO_DEBUG`)

## Running the frontend

```bash
cd frontend && npm run dev
```

Open http://localhost:5173. Workspace screens live under `/w/<workspace-id>/`,
so each browser tab keeps its own workspace. The dev server proxies `/api` to the backend, so
the browser sees a single origin. Always use the application through port
5173 in development.

## Running tests

```bash
cd backend && .venv/bin/pytest          # needs PostgreSQL running
cd frontend && npm test
```

Browser tests (Playwright) run the real stack on ports 8100 and 5183 against a
separate database, `merchantflow_e2e`, which they create, wipe and fill with
fictional accounts on every run:

```bash
cd frontend && npx playwright install chromium   # once
cd frontend && npm run e2e
```

Lint, format and type checks (`make lint` runs all of them):

```bash
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
cd frontend && npm run lint && npm run format:check && npm run typecheck
```

The same checks run in GitHub Actions ([.github/workflows/ci.yml](.github/workflows/ci.yml)).
