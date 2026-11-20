# syntax=docker/dockerfile:1

# ---- build: resolve dependencies into a virtualenv ----------------------------------------
FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

# ---- runtime: slim image, non-root user ---------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime
RUN groupadd --system mandy && useradd --system --gid mandy --home /app mandy
WORKDIR /app
COPY --from=builder --chown=mandy:mandy /app /app
COPY --chown=mandy:mandy docker/entrypoint.sh /app/entrypoint.sh
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 ENV=prod PORT=8000
USER mandy
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8000\")}/api/v1/health', timeout=4)"
ENTRYPOINT ["/app/entrypoint.sh"]
