.PHONY: install lint format test eval reindex migrate seed-users seed-safety up down logs
 
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
 
eval:
	.venv/bin/python scripts/evaluate_rag.py --dataset evaluation/datasets/tb_starter.jsonl $(EVAL_ARGS)
 

reindex:
	.venv/bin/python scripts/reindex_documents.py $(REINDEX_ARGS)
 
migrate:
	.venv/bin/alembic upgrade head
 
seed-users:
	docker compose exec semyzbay-api python scripts/seed_users.py
 
seed-safety:
	docker compose exec semyzbay-api python scripts/seed_safety_demo.py
 
up:
	docker compose up -d --build
 
down:
	docker compose down
 
logs:
	docker compose logs -f semyzbay-api semyzbay-worke