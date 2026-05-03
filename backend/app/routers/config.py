import logging
import time
from io import BytesIO

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from openai import OpenAI
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.models import (
    AIModel,
    AIModelCreate,
    AIModelRead,
    AIModelUpdate,
    AppConfig,
    ConfigRead,
    ConfigUpdate,
    ModelTestResult,
    PodcastShow,
    Provider,
)

logger = logging.getLogger("clipcast")
router = APIRouter(prefix="/api", tags=["config"])


def _ai_model_to_read(model: AIModel) -> AIModelRead:
    return AIModelRead(
        id=model.id,
        name=model.name,
        provider=model.provider,
        host=model.host,
        api_key=model.api_key,
        base_url=model.base_url,
        is_preset=model.is_preset,
        input_price=model.input_price,
        output_price=model.output_price,
        supports_transcription=model.supports_transcription,
        supports_analysis=model.supports_analysis,
        is_recommended=model.is_recommended,
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
        if data.transcription_model_id != "":
            model = session.get(AIModel, data.transcription_model_id)
            if not model:
                raise HTTPException(status_code=422, detail="Transcription model not found")
            if not model.supports_transcription:
                raise HTTPException(
                    status_code=422,
                    detail=f"Model '{model.name}' does not support transcription",
                )
        config.transcription_model_id = data.transcription_model_id or None
    if data.analysis_model_id is not None:
        if data.analysis_model_id != "":
            model = session.get(AIModel, data.analysis_model_id)
            if not model:
                raise HTTPException(status_code=422, detail="Analysis model not found")
            if not model.supports_analysis:
                raise HTTPException(
                    status_code=422,
                    detail=f"Model '{model.name}' does not support analysis",
                )
        config.analysis_model_id = data.analysis_model_id or None
    # gemini_api_key and openrouter_api_key accepted but ignored (deprecated;
    # api keys are now stored per-model)
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
        api_key=data.api_key,
        base_url=data.base_url or data.host,
        supports_transcription=data.supports_transcription,
        supports_analysis=data.supports_analysis,
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    logger.info("Custom model created: %s", model.name)
    return _ai_model_to_read(model)


@router.put("/models/{model_id}", response_model=AIModelRead)
def update_model(model_id: str, data: AIModelUpdate, session: Session = Depends(get_session)):
    model = session.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(model, field, value)
    session.add(model)
    session.commit()
    session.refresh(model)
    return _ai_model_to_read(model)


@router.delete("/models/{model_id}", status_code=204)
def delete_model(model_id: str, session: Session = Depends(get_session)):
    model = session.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")
    session.delete(model)
    session.commit()


@router.post("/models/{model_id}/test", response_model=ModelTestResult)
def test_model(model_id: str, session: Session = Depends(get_session)):
    model = session.get(AIModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="Model not found")

    provider = Provider(model.provider)
    start = time.monotonic()

    try:
        if provider == Provider.GEMINI:
            from google import genai

            client = genai.Client(api_key=model.api_key)
            list(client.models.list())
        elif provider in (Provider.OPENAI_COMPATIBLE, Provider.OPENROUTER):
            from app.services.providers import OpenRouterProvider

            base_url = (
                OpenRouterProvider.base_url
                if provider == Provider.OPENROUTER
                else model.base_url
            )
            if not base_url:
                raise ValueError("base_url required for this provider")
            client = OpenAI(api_key=model.api_key, base_url=base_url)
            client.models.list()
        elif provider == Provider.WHISPER_CPP:
            base_url = (model.base_url or model.host or "").rstrip("/")
            if not base_url:
                raise ValueError("No Whisper URL configured")
            resp = requests.get(f"{base_url}/health", timeout=10)
            if resp.status_code != 200:
                raise ConnectionError(f"Whisper server unhealthy: HTTP {resp.status_code}")
        else:
            raise ValueError(f"Unknown provider: {provider}")

        latency_ms = int((time.monotonic() - start) * 1000)
        return ModelTestResult(ok=True, message="Connected successfully", latency_ms=latency_ms)

    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return ModelTestResult(ok=False, message=str(e), latency_ms=latency_ms)


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
