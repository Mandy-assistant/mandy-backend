#!/bin/sh
# Apply migrations, then serve. Runs as the non-root `mandy` user.
set -e
alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}" --workers "${WEB_CONCURRENCY:-2}"
