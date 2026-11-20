# mandy-backend

Mandy API — FastAPI, PostgreSQL, Redis, passkeys and a Gemini-powered assistant.

- API contract shared with the frontend: [`docs/api-contract.md`](docs/api-contract.md)
- Conventions (errors, pagination, auth, ownership): [`docs/api-conventions.md`](docs/api-conventions.md)
- Architecture and data model: [`docs/architecture.md`](docs/architecture.md)

## Requirements

- [uv](https://docs.astral.sh/uv/) (Python 3.12 is pinned in `.python-version`; uv uses or downloads it)
- Docker with `docker compose`

## Setup

```bash
cp .env.example .env          # then edit if needed (see below)
docker compose up -d          # Postgres 17 on host port 5433, Redis 7 on 6379 (both with health checks)
uv sync                       # install dependencies
uv run alembic upgrade head   # create the schema
uv run python -m app.scripts.seed --reset   # demo data (owner "Mathan", demo@mandy.dev)
uv run fastapi dev app/main.py --port 8000
```

- Swagger UI: http://localhost:8000/docs · ReDoc: http://localhost:8000/redoc
- Health: `curl localhost:8000/api/v1/health` → `{"status":"ok","db":"ok","redis":"ok"}`

The `mandy_test` database used by the tests is created by `docker/postgres-init` on first start
(and by the test suite itself if it's missing).

> **Port 5433 already taken?** Set `POSTGRES_HOST_PORT=5435` (or any free port) in `.env` and use the same port in
> `DATABASE_URL`/`TEST_DATABASE_URL`. Compose reads `.env` for the port mapping.

### Signing in locally

Mandy has a single owner who signs in with a passkey. The seed creates the owner **without** a passkey, so the
frontend shows the setup screen; `/auth/setup/*` attaches the first passkey to the seeded owner.

For scripts, Swagger and e2e tests there's a dev-only shortcut (only registered when `ENV=dev` **and**
`DEV_LOGIN_ENABLED=true`):

```bash
curl -s -c /tmp/mandy.jar -X POST localhost:8000/api/v1/auth/dev-login
curl -s -b /tmp/mandy.jar "localhost:8000/api/v1/dashboard/summary?tz=Asia/Kolkata"
```

## Environment variables

| Variable | Default | Notes |
| --- | --- | --- |
| `ENV` | `dev` | `dev`, `test` or `prod`. `prod` enforces a strong `JWT_SECRET`, Secure cookies, HSTS. |
| `DATABASE_URL` | `postgresql+asyncpg://mandy:mandy@localhost:5433/mandy` | asyncpg URL |
| `TEST_DATABASE_URL` | same server, database `mandy_test` | used by pytest |
| `REDIS_URL` | `redis://localhost:6379/0` | tests use db 15 on the same server |
| `POSTGRES_HOST_PORT` | `5433` | docker compose host port for Postgres |
| `JWT_SECRET` | dev placeholder | ≥ 32 random chars in prod: `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `CORS_ORIGINS` | `["http://localhost:3001"]` | JSON list |
| `RP_ID` / `RP_NAME` / `ORIGIN` | `localhost` / `Mandy` / `http://localhost:3001` | WebAuthn relying party = the frontend |
| `DEV_LOGIN_ENABLED` | `false` | **dev only**; `.env.example` turns it on for local work |
| `GEMINI_API_KEY` | empty | empty → AI endpoints return 503 `AI_UNAVAILABLE` |
| `GEMINI_MODEL` | `gemini-2.5-flash` | |
| `NEWS_FEEDS_ENABLED` | `true` | `POST /news/refresh` pulls RSS feeds when true |
| `LOG_LEVEL` / `LOG_JSON` | `INFO` / JSON outside dev | |

### Free Gemini key

1. Open https://aistudio.google.com/apikey and sign in with a Google account.
2. *Create API key* → copy it.
3. Put it in `.env` as `GEMINI_API_KEY=...` and restart the API. `GET /api/v1/assistant/status` then reports
   `"enabled": true`. The free tier is rate-limited; when the quota is hit the API answers 429 `AI_RATE_LIMITED`.

## Common commands

```bash
make up | down           # docker compose
make dev                 # API with reload on :8000
make migrate             # alembic upgrade head
make downgrade           # alembic downgrade -1
make makemigration m="add something"   # autogenerate — always review the generated file before committing
make seed                # seed --reset
make test                # pytest with coverage
make lint typecheck fmt  # ruff / mypy
```

Seeding is idempotent: `python -m app.scripts.seed` does nothing if demo data exists (it only refreshes news),
`--reset` wipes the owner's data (keeping passkeys and recovery codes) and recreates it with dates relative to today.

## Tests

```bash
docker compose up -d
uv run pytest --cov
```

The suite uses the separate `mandy_test` database (migrations applied once per session), wraps each test in a
transaction that is rolled back, flushes Redis db 15, and calls the app through `httpx.AsyncClient` +
`ASGITransport`. WebAuthn verification and the Gemini client are faked. CI (`.github/workflows/ci.yml`) runs ruff,
mypy, a migration round-trip and pytest against Postgres/Redis service containers.

Install the git hooks with `uv run pre-commit install`.

## Production image

```bash
docker build -t mandy-api .
docker run -p 8000:8000 --env-file .env.prod mandy-api   # runs `alembic upgrade head`, then uvicorn
```

Or locally with compose: `docker compose --profile api up -d --build`.
