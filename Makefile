.PHONY: db-up db-down install migrate backend frontend test lint format

PY := backend/.venv/bin/python

db-up:
	docker compose up -d db

db-down:
	docker compose down

install:
	python3 -m venv backend/.venv
	backend/.venv/bin/pip install -r backend/requirements-dev.txt
	cd frontend && npm ci

migrate:
	cd backend && .venv/bin/python manage.py migrate

backend:
	cd backend && .venv/bin/python manage.py runserver 127.0.0.1:8000

frontend:
	cd frontend && npm run dev

test:
	cd backend && .venv/bin/pytest
	cd frontend && npm test

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd frontend && npm run lint && npm run format:check && npm run typecheck

format:
	cd backend && .venv/bin/ruff check --fix . && .venv/bin/ruff format .
	cd frontend && npm run format
