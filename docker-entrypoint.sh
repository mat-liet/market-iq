#!/usr/bin/env bash
# Bring the database to a usable state before serving: apply migrations and
# seed the (idempotent) taxonomy, then exec the given command (uvicorn).
# Without this a fresh `docker compose up` starts the API against an empty
# database — no tables, and no themes to classify or report against.
set -euo pipefail

echo "Running database migrations..."
alembic upgrade head

echo "Seeding taxonomy..."
python -m scripts.seed_taxonomy

echo "Starting: $*"
exec "$@"
