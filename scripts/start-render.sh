#!/bin/sh
set -eu

# Render's free web services do not support pre-deploy commands or one-off
# jobs. Alembic upgrades are idempotent, so applying them here keeps every
# deploy (and cold start) aligned with the checked-in schema.
alembic upgrade head

exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}"
