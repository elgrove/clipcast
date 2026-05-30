import logging
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.models import (
    AIModel,
    AIModelCreate,
    AIModelRead,
    AIModelUpdate,
    AIProvider,
    AppConfig,
    ConfigRead,
    ConfigUpdate,
    PodcastShow,
    Provider,
)

logger = logging.getLogger("clipcast")
router = APIRouter(prefix="/api", tags=["config"])


def _ai_model_to_read(model: AIModel) -> AIModelRead:
    return AIModelRead(
        id=model.id,
        provider_id=model.provider_id,
        name=model.name,
        provider_kind=model.provider.kind,
        provider_name=model.provider.name,
        input_price=model.input_price,
        output_price=model.output_price,
        supports_transcription=model.supports_transcription,
        supports_analysis=model.supports_analysis,
        context_window=model.context_window,
        display_name=str(model),
    )


@router.get("/config", response_model=ConfigRead)
def get_config(session: Session = Depends(get_session)):
    config = session.get(AppConfig, "config")
    return ConfigRead(
        transcription_model_id=config.transcription_model_id,
        analysis_model_id=config.analysis_model_id,
        boundary_refinement_model_id=config.boundary_refinement_model_id,
        keep_raw_episodes=config.keep_raw_episodes,
        transcription_model=(
            _ai_model_to_read(config.transcription_model) if config.transcription_model else None
        ),
        analysis_model=(
            _ai_model_to_read(config.analysis_model) if config.analysis_model else None
        ),
        boundary_refinement_model=(
            _ai_model_to_read(config.boundary_refinement_model)
            if config.boundary_refinement_model
            else None
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
    if data.boundary_refinement_model_id is not None:
        if data.boundary_refinement_model_id != "":
            model = session.get(AIModel, data.boundary_refinement_model_id)
            if not model:
                raise HTTPException(
                    status_code=422, detail="Boundary refinement model not found"
                )
            if model.provider.kind != Provider.GEMINI.value:
                raise HTTPException(
                    status_code=422,
                    detail="Boundary refinement requires a Gemini model",
                )
        config.boundary_refinement_model_id = data.boundary_refinement_model_id or None
    if data.keep_raw_episodes is not None:
        config.keep_raw_episodes = data.keep_raw_episodes
    session.add(config)
    session.commit()
    session.refresh(config)
    logger.info("Config updated")
    return get_config(session)


@router.get("/models", response_model=list[AIModelRead])
def list_models(session: Session = Depends(get_session)):
    models = session.exec(select(AIModel)).all()
    return [_ai_model_to_read(m) for m in models]


# Provider context-window defaults. OpenRouter is looked up live per model;
# everything else is hardcoded against the vendor's published spec.
DEFAULT_CONTEXT_WINDOWS: dict[str, int] = {
    Provider.GEMINI.value: 1_048_576,
    Provider.OPENAI.value: 262_144,
    Provider.OPENAI_COMPATIBLE.value: 131_072,
    Provider.WHISPER_CPP.value: 0,
}


def _resolve_context_window(provider: str, model_name: str, api_key: str) -> int:
    if provider == Provider.OPENROUTER.value:
        from app.services.openrouter_models import fetch_context_length

        fetched = fetch_context_length(model_name, api_key)
        if fetched > 0:
            return fetched
        # Catalogue miss — fall back to the safe small default so chunking
        # still kicks in on long episodes.
        return DEFAULT_CONTEXT_WINDOWS[Provider.OPENAI_COMPATIBLE.value]
    return DEFAULT_CONTEXT_WINDOWS.get(provider, 0)


@router.post("/models", response_model=AIModelRead, status_code=201)
def create_model(data: AIModelCreate, session: Session = Depends(get_session)):
    provider = session.get(AIProvider, data.provider_id)
    if not provider:
        raise HTTPException(status_code=422, detail="Provider not found")

    name = data.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Model name is required")

    clash = session.exec(
        select(AIModel).where(AIModel.provider_id == provider.id, AIModel.name == name)
    ).first()
    if clash:
        raise HTTPException(
            status_code=422,
            detail=f"Model '{name}' already exists for provider '{provider.name}'",
        )

    context_window = _resolve_context_window(provider.kind, name, provider.api_key)
    model = AIModel(
        provider_id=provider.id,
        name=name,
        supports_transcription=data.supports_transcription,
        supports_analysis=data.supports_analysis,
        context_window=context_window,
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    logger.info(
        "Model created: %s on provider %s (context_window=%d)",
        model.name,
        provider.name,
        model.context_window,
    )
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
