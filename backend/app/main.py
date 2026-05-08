import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import config, episodes, feed, podcasts, reports, search

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(levelname)s %(asctime)s %(name)s %(message)s",
)
logger = logging.getLogger("clipcast")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.database import init_db

    settings.podcasts_path.mkdir(parents=True, exist_ok=True)
    init_db()
    logger.info("Clipcast started")
    yield
    logger.info("Clipcast shutting down")


app = FastAPI(
    title="Clipcast",
    description="Self-hosted podcast server with AI-powered advert removal",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(podcasts.router)
app.include_router(episodes.router)
app.include_router(config.router)
app.include_router(search.router)
app.include_router(feed.router)
app.include_router(reports.router)

# Serve SPA frontend if the build directory exists
frontend_dir = Path(settings.frontend_dir)
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
    index_html = frontend_dir / "index.html"

    @app.get("/{full_path:path}")
    async def spa_fallback(request: Request, full_path: str):
        # Serve actual static files if they exist, otherwise fall back to index.html
        file_path = frontend_dir / full_path
        if full_path and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(index_html)
