import logging
from io import BytesIO

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.models import (
    AIModel,
    AIModelCreate,
    AIModelRead,
    AppConfig,
    ConfigRead,
    ConfigUpdate,
    PodcastShow,
)

logger = logging.getLogger("clipcast")
router = APIRouter(prefix="/api", tags=["config"])


def _ai_model_to_read(model: AIModel) -> AIModelRead:
    return AIModelRead(
        id=model.id,
        name=model.name,
        provider=model.provider,
        host=model.host,
        is_preset=model.is_preset,
        input_price=model.input_price,
        output_price=model.output_price,
        display_name=str(model),
    )


@router.get("/config", response_model=ConfigRead)
def get_config(session: Session = Depends(get_session)):
    config = session.get(AppConfig, "config")
    return ConfigRead(
        transcription_model_id=config.transcription_model_id,
        analysis_model_id=config.analysis_model_id,
        gemini_api_key=config.gemini_api_key,
        openrouter_api_key=config.openrouter_api_key,
        identify_ads_in_acast_breaks=config.identify_ads_in_acast_breaks,
        transcription_model=(
            _ai_model_to_read(config.transcription_model) if config.transcription_model else None
        ),
        analysis_model=(
            _ai_model_to_read(config.analysis_model) if config.analysis_model else None
        ),
    )


@router.put("/config", response_model=ConfigRead)
def update_config(data: ConfigUpdate, session: Session = Depends(get_session)):
    config = session.get(AppConfig, "config")
    if data.transcription_model_id is not None:
        config.transcription_model_id = data.transcription_model_id
    if data.analysis_model_id is not None:
        config.analysis_model_id = data.analysis_model_id
    if data.gemini_api_key is not None:
        config.gemini_api_key = data.gemini_api_key
    if data.openrouter_api_key is not None:
        config.openrouter_api_key = data.openrouter_api_key
    if data.identify_ads_in_acast_breaks is not None:
        config.identify_ads_in_acast_breaks = data.identify_ads_in_acast_breaks
    session.add(config)
    session.commit()
    session.refresh(config)
    logger.info("Config updated")
    return get_config(session)


@router.get("/models", response_model=list[AIModelRead])
def list_models(session: Session = Depends(get_session)):
    models = session.exec(select(AIModel)).all()
    return [_ai_model_to_read(m) for m in models]


@router.post("/models", response_model=AIModelRead, status_code=201)
def create_model(data: AIModelCreate, session: Session = Depends(get_session)):
    model = AIModel(
        name=data.name,
        provider=data.provider,
        host=data.host,
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    logger.info("Custom model created: %s", model.name)
    return _ai_model_to_read(model)


@router.get("/config/export-opml")
def export_opml(
    request: Request,
    feed_type: str = "clipcast",
    session: Session = Depends(get_session),
):
    podcasts = session.exec(select(PodcastShow)).all()
    base_url = settings.external_url or str(request.base_url).rstrip("/")

    opml = BytesIO()
    opml.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
    opml.write(b'<opml version="2.0">\n')
    opml.write(b"  <head><title>Clipcast Podcasts</title></head>\n")
    opml.write(b"  <body>\n")

    for podcast in podcasts:
        url = (
            f"{base_url}/feed/{podcast.itunes_id}"
            if feed_type == "clipcast"
            else podcast.source_rss_url
        )
        title = podcast.title.replace("&", "&amp;").replace('"', "&quot;")
        opml.write(f'    <outline text="{title}" xmlUrl="{url}" type="rss" />\n'.encode())

    opml.write(b"  </body>\n")
    opml.write(b"</opml>\n")

    return Response(
        content=opml.getvalue(),
        media_type="application/xml",
        headers={"Content-Disposition": "attachment; filename=clipcast.opml"},
    )
