# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is Clipcast

Clipcast is a self-hosted podcast server that uses AI (Google Gemini or Whisper.cpp) to detect and remove adverts from podcast episodes, then serves ad-free RSS feeds.

## Commands

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
npm run dev                          # dev server (port 5173, proxies /api, /feed, /podcasts to 8906)
npm run build                        # build static files
npm run check                        # svelte-check type checking

# Docker
docker compose up                    # full stack (app + 3 workers + redis + whisper.cpp server)
```

## Architecture

**Backend** (`backend/app/`): FastAPI JSON API with SQLModel ORM on SQLite (WAL mode). `main.py` is the app entrypoint. `config.py` loads settings from env vars via pydantic-settings (no prefix, supports `.env` file). `database.py` manages the SQLModel engine and session.

**API routers** (`backend/app/routers/`): `podcasts.py`, `episodes.py`, `config.py`, `search.py`, `feed.py`, `reports.py`. All return JSON except the feed (XML) and file endpoints.

**Clipping pipeline** (`backend/app/tasks.py`): `queue_episode_for_clipping()` orchestrates four Celery tasks via `chain()`:
1. `task_download` (`services/download.py`) — fetch MP3 from source RSS → `default` queue
2. `task_transcribe` (`services/transcription.py`) — send audio to Gemini or Whisper.cpp → dynamically routed to `ai` or `whisper` queue based on config
3. `task_analyse` (`services/analysis.py`) — send transcription to Gemini to identify advert segments → `ai` queue
4. `task_edit` (`services/editor.py`) — use pydub to cut advert segments from the audio → `default` queue

Each step is idempotent (skips if already completed). Progress is tracked via `ClippingReport` with timestamps for each stage.

**Worker architecture** (`docker-compose.yml`): Three separate Celery worker containers:
- `worker` — `default` queue + beat scheduler, concurrency=2
- `aiworker` — `ai` queue (Gemini API calls), concurrency=2
- `whisperworker` — `whisper` queue (local whisper.cpp transcription), concurrency=1

Beat schedule: `sync_and_process_new_episodes` hourly, `cleanup_old_episodes` daily at 03:00.

**AI providers** (`services/providers.py`): Abstract `AIProviderBase` with `GeminiProvider` (transcription + analysis) and `WhisperProvider` (transcription only). Providers receive config via constructor parameters, not global state.

**Frontend** (`frontend/`): SvelteKit SPA (`@sveltejs/adapter-static` with `fallback: 'index.html'`) and Tailwind CSS. Compiles to static files served by FastAPI. API client in `lib/api.ts`, types in `lib/types.ts`.

## Key Models (`backend/app/models.py`)

- `AppConfig` — singleton (id="config") holding API keys and model selections
- `PodcastShow` — podcast metadata, `has_ads` flag controls whether episodes get clipped
- `PodcastEpisode` — episode data with file path properties (`mp3_path`, `raw_path`, `srt_path`, `ads_path`). JSON fields for ads and transcription stored as TEXT.
- `ClippingReport` — tracks pipeline progress with timestamps, logs, and report JSON
- `AIModel` — transcription/analysis model config, supports preset and custom models

API request/response schemas are Pydantic models in the same file (e.g. `PodcastShowRead`, `PodcastEpisodeRead`).

## Code Style

Ruff is configured in `backend/pyproject.toml`: line length 100, double quotes, spaces. Pytest uses `asyncio_mode = "auto"`.
