#!/bin/bash
set -e

# Initialise database before starting workers
uv run python -c "from app.database import init_db; init_db()"

# Start uvicorn
exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8906 --workers 2
