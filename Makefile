.PHONY: up down dev migrate makemigration downgrade seed test lint fmt typecheck

up:            ## start Postgres + Redis
	docker compose up -d

down:
	docker compose down

dev:           ## run the API with reload on :8000
	uv run fastapi dev app/main.py --port 8000

migrate:       ## apply all migrations
	uv run alembic upgrade head

downgrade:     ## roll back one migration
	uv run alembic downgrade -1

makemigration: ## autogenerate a migration: make makemigration m="add jobs"
	uv run alembic revision --autogenerate -m "$(m)"

seed:          ## (re)create demo data
	uv run python -m app.scripts.seed --reset

test:
	uv run pytest --cov

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

typecheck:
	uv run mypy app
