# Mandy API

Minimal FastAPI service with async SQLAlchemy and PostgreSQL.

## Run with Docker Compose

```bash
docker compose up --build
```

Compose starts PostgreSQL and waits for its health check before starting the API. The API is
available at <http://localhost:8000>, its docs at <http://localhost:8000/docs>, and its database
health check at <http://localhost:8000/health>.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=postgresql+asyncpg://app:app@localhost:5432/app
uvicorn app.main:app --reload
```

For a local FastAPI process, start PostgreSQL with `docker compose up -d postgres` first.
Mandy API — FastAPI, PostgreSQL, Redis
