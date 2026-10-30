.PHONY: install lint format test migrate up down logs

install:
	python3.12 -m venv .venv
	.venv/bin/pip install -r requirements-dev.lock

lint:
	.venv/bin/ruff check .
	.venv/bin/mypy app

format:
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .

test:
	.venv/bin/pytest

migrate:
	.venv/bin/alembic upgrade head

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f semyzbay-api semyzbay-worker
