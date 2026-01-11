# syntax=docker/dockerfile:1

FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    supervisor \
    ffmpeg \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_CACHE_DIR=/app/.cache

WORKDIR /app

COPY uv.lock pyproject.toml ./
RUN uv sync --frozen --no-cache

COPY . .

RUN uv run python manage.py collectstatic --no-input

RUN chmod +x /app/entrypoint.sh

EXPOSE 8906

ENTRYPOINT ["/app/entrypoint.sh"]
