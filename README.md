# clipcast

Clipcast is a self-hosted podcast server that uses AI to detect and remove adverts from podcast episodes. It serves ad-free RSS feeds you can subscribe to in your usual podcast player.

## How it works

You add podcasts through the web UI by searching iTunes. Clipcast syncs episodes hourly and runs new ones through a four-step pipeline: download the MP3, transcribe it, send the transcript to Gemini to identify ad segments, then cut those segments out with ffmpeg/pydub. The clipped episode is served via an RSS feed unique to each podcast.

Transcription can use either the Gemini API (fast, requires API key) or a local Whisper.cpp server (slow, free, CPU-bound). Ad detection/analysis always uses Gemini.

## Running it

The whole stack runs with Docker Compose. The `docker-compose.yml` in the repo is a working example.

```
docker compose up -d
```

This starts:

- `clipcast` - the web app (FastAPI, port 8906)
- `worker` - Celery worker for downloads, editing, and the beat scheduler
- `aiworker` - Celery worker for Gemini API calls (transcription + analysis)
- `whisperworker` - Celery worker for local Whisper transcription (concurrency 1)
- `redis` - task queue broker
- `transcription` - Whisper.cpp server for local transcription

On first run, the web UI will walk you through configuring your transcription and analysis models, adding a podcast, and clipping an episode.

## Local transcription

If you don't want to send audio to Gemini for transcription, you can use the included Whisper.cpp container. It uses the [whisper.cpp server](https://github.com/ggml-org/whisper.cpp/tree/master/examples/server) and runs on CPU by default.

You'll need to download a Whisper model and place it in `transcription/models/`. The compose file expects `ggml-base.en.bin`. You can get it from the [Hugging Face ggml repo](https://huggingface.co/ggerganov/whisper.cpp/tree/main).

Performance depends on how many CPU cores you give it. On an i7-8559U with 4 cores allocated, a 33-minute episode takes about 5.5 minutes to transcribe. If you have a large library with frequent releases, you may want GPU acceleration or the Gemini transcription option instead.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `clipcast.db` | Path to the SQLite database |
| `PODCASTS_DIR` | `_podcasts` | Where episode MP3s are stored |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `FRONTEND_DIR` | `static/frontend` | Path to built frontend assets |
| `DEBUG` | `false` | Enable debug mode |
| `ALLOWED_ORIGINS` | `["*"]` | CORS allowed origins |

## Stack

- Python 3.11, FastAPI, SQLModel, SQLite
- Celery + Redis
- SvelteKit (static SPA) + Tailwind CSS v4
- Google Gemini API / Whisper.cpp
- pydub + ffmpeg
- Docker Compose
