# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Clipcast

Clipcast is a self-hosted podcast server that uses AI (Google Gemini or Whisper.cpp) to detect and remove adverts from podcast episodes, then serves ad-free RSS feeds.

## Project Layout

There are two versions of the app in this repo:

- **v1 (legacy)**: Django + Django-Q2 + HTMX. Root-level `core/`, `project/`, `manage.py`, `Dockerfile`, `docker-compose.yml`.
- **v2 (active)**: FastAPI + Celery/Redis + SvelteKit SPA. In `backend/` and `frontend/` directories, with `docker-compose.v2.yml`.

## Commands (v2)

```bash
# Backend (run from backend/)
cd backend
uv run pytest tests/ -v             # run all backend tests
uv run pytest tests/test_api_config.py  # run a single test file
uv run pytest -k test_name          # run a single test by name
uv run ruff check app/ tests/       # lint
uv run ruff format --check app/ tests/  # check formatting
uv run ruff check --fix app/ tests/ && uv run ruff format app/ tests/  # auto-fix
uv run uvicorn app.main:app --reload --port 8906  # dev server

# Frontend (run from frontend/)
cd frontend
npm run dev                          # dev server (port 5173, proxies API to 8906)
npm run build                        # build static files
npm run check                        # svelte-check type checking

# Docker
docker compose -f docker-compose.v2.yml up  # full stack
```

## Architecture (v2)

**Backend** (`backend/app/`): FastAPI JSON API with SQLModel ORM on SQLite. `main.py` is the app entrypoint. `config.py` loads settings from env vars via pydantic-settings. `database.py` manages the SQLModel engine and session.

**API routers** (`backend/app/routers/`): `podcasts.py`, `episodes.py`, `config.py`, `search.py`, `feed.py`. All return JSON except the feed (XML) and file endpoints.

**Clipping pipeline** (`backend/app/tasks.py`): `run_clipping_pipeline` is a Celery task running four sequential steps:
1. **Download** (`services/download.py`) - fetch MP3 from source RSS
2. **Transcribe** (`services/transcription.py`) - send audio to Gemini or Whisper.cpp
3. **Analyse** (`services/analysis.py`) - send transcription to Gemini to identify advert segments
4. **Edit** (`services/editor.py`) - use pydub to cut advert segments from the audio

Each step is idempotent (skips if already completed). Progress is tracked via `ClippingReport` with timestamps for each stage.

**Task queue** (`backend/app/worker.py`): Celery with Redis broker. Beat schedule runs `sync_and_process_new_episodes` hourly. Tests use `task_always_eager=True`.

**AI providers** (`services/providers.py`): Abstract `AIProviderBase` with `GeminiProvider` (transcription + analysis) and `WhisperProvider` (transcription only). Providers receive config via constructor parameters, not global state.

**Frontend** (`frontend/`): SvelteKit SPA (static adapter) with Tailwind CSS. Compiles to static files served by FastAPI. API client in `lib/api.ts`, types in `lib/types.ts`.

## Key Models (`backend/app/models.py`)

- `AppConfig` - singleton (id="config") holding API keys and model selections
- `PodcastShow` - podcast metadata, `has_ads` flag controls whether episodes get clipped
- `PodcastEpisode` - episode data with file path properties (`mp3_path`, `raw_path`, `srt_path`, `ads_path`). JSON fields for ads and transcription stored as TEXT.
- `ClippingReport` - tracks pipeline progress with timestamps, logs, and report JSON
- `AIModel` - transcription/analysis model config, supports preset and custom models

API request/response schemas are Pydantic models in the same file (e.g. `PodcastShowRead`, `PodcastEpisodeRead`).

## Tech Stack (v2)

- Python 3.11, FastAPI, SQLModel, SQLite with WAL mode
- Celery + Redis for async tasks
- Google Gemini API / Whisper.cpp for AI
- pydub + ffmpeg for audio editing, feedgen for RSS generation
- SvelteKit 5 (SPA mode) + Tailwind CSS v4
- Docker Compose (app + worker + redis)
- uv for Python package management, ruff for linting

## Data Migration

`scripts/migrate_from_django.py` migrates from the Django v1 database to the new schema. Backs up the old database first, reads it in read-only mode. Existing podcast files on disk are compatible — mount the same `/podcasts` volume.
