#!/bin/bash
set -e

sqlite3 db.sqlite3 "PRAGMA journal_mode=WAL;"
uv run python manage.py migrate --noinput
uv run python manage.py schedule_tasks

exec supervisord -c /app/supervisord.conf
