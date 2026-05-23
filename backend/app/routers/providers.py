import logging
import time

import requests
from fastapi import APIRouter, Depends, HTTPException
from google import genai
from openai import OpenAI
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    AIModel,
    AIProvider,
    AIProviderCreate,
    AIProviderRead,
    AIProviderUpdate,
    AppConfig,
    Provider,
    ProviderTestResult,
)
from app.services.providers import OpenRouterProvider
from app.services.recommendations import recommended_models

logger = logging.getLogger("clipcast")
router = APIRouter(prefix="/api/providers", tags=["providers"])


SINGLE_INSTANCE_KINDS = {
    Provider.GEMINI,
    Provider.OPENAI,
    Provider.OPENROUTER,
    Provider.WHISPER_CPP,
}


def _to_read(p: AIProvider) -> AIProviderRead:
    return AIProviderRead(
        id=p.id,
        kind=p.kind,
        name=p.name,
        base_url=p.base_url,
        has_api_key=bool(p.api_key),
    )


def _default_name(kind: Provider) -> str:
    return kind.label


@router.get("", response_model=list[AIProviderRead])
def list_providers(session: Session = Depends(get_session)):
    providers = session.exec(select(AIProvider)).all()
    return [_to_read(p) for p in providers]


@router.post("", response_model=AIProviderRead, status_code=201)
def create_provider(data: AIProviderCreate, session: Session = Depends(get_session)):
    try:
        kind = Provider(data.kind)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Unknown provider kind: {data.kind}") from e

    if kind in SINGLE_INSTANCE_KINDS:
        existing = session.exec(select(AIProvider).where(AIProvider.kind == kind.value)).first()
        if existing:
            raise HTTPException(
                status_code=422,
                detail=f"{kind.label} already added — only one allowed.",
            )
        name = _default_name(kind)
    else:
        if not data.name or not data.name.strip():
            raise HTTPException(
                status_code=422,
                detail="Name is required for OpenAI-compatible providers (e.g. 'Groq').",
            )
        name = data.name.strip()

    name_clash = session.exec(select(AIProvider).where(AIProvider.name == name)).first()
    if name_clash:
        raise HTTPException(status_code=422, detail=f"A provider named '{name}' already exists.")

    if kind == Provider.OPENAI_COMPATIBLE and not data.base_url:
        raise HTTPException(
            status_code=422,
            detail="Base URL is required for OpenAI-compatible providers.",
        )
    if kind == Provider.WHISPER_CPP and not data.base_url:
        raise HTTPException(
            status_code=422,
            detail="Host URL is required for Whisper.cpp providers.",
        )

    provider = AIProvider(
        kind=kind.value,
        name=name,
        api_key=data.api_key,
        base_url=data.base_url,
    )
    session.add(provider)
    session.flush()

    if data.auto_create_recommended:
        config = session.get(AppConfig, "config")
        for spec in recommended_models(kind):
            model = AIModel(
                provider_id=provider.id,
                name=spec["name"],
                supports_transcription=spec["supports_transcription"],
                supports_analysis=spec["supports_analysis"],
            )
            session.add(model)
            session.flush()
            if spec["supports_transcription"]:
                config.transcription_model_id = model.id
            if spec["supports_analysis"]:
                config.analysis_model_id = model.id
        session.add(config)

    session.commit()
    session.refresh(provider)
    logger.info("Provider created: %s (%s)", provider.name, provider.kind)
    return _to_read(provider)


@router.patch("/{provider_id}", response_model=AIProviderRead)
def update_provider(
    provider_id: str,
    data: AIProviderUpdate,
    session: Session = Depends(get_session),
):
    provider = session.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if data.name is not None:
        new_name = data.name.strip()
        if not new_name:
            raise HTTPException(status_code=422, detail="Name cannot be empty.")
        if new_name != provider.name:
            clash = session.exec(select(AIProvider).where(AIProvider.name == new_name)).first()
            if clash:
                raise HTTPException(
                    status_code=422,
                    detail=f"A provider named '{new_name}' already exists.",
                )
            provider.name = new_name
    if data.api_key is not None:
        provider.api_key = data.api_key
    if data.base_url is not None:
        provider.base_url = data.base_url

    session.add(provider)
    session.commit()
    session.refresh(provider)
    return _to_read(provider)


@router.delete("/{provider_id}", status_code=204)
def delete_provider(provider_id: str, session: Session = Depends(get_session)):
    provider = session.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if provider.models:
        names = ", ".join(m.name for m in provider.models)
        raise HTTPException(
            status_code=422,
            detail=f"Cannot delete provider while models reference it: {names}",
        )

    session.delete(provider)
    session.commit()


@router.post("/{provider_id}/test", response_model=ProviderTestResult)
def test_provider(provider_id: str, session: Session = Depends(get_session)):
    provider = session.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    kind = Provider(provider.kind)
    start = time.monotonic()
    try:
        if kind == Provider.GEMINI:
            if not provider.api_key:
                raise ValueError("API key required")
            client = genai.Client(api_key=provider.api_key)
            list(client.models.list())
        elif kind == Provider.OPENAI:
            if not provider.api_key:
                raise ValueError("API key required")
            client = OpenAI(api_key=provider.api_key, base_url="https://api.openai.com/v1")
            client.models.list()
        elif kind == Provider.OPENROUTER:
            if not provider.api_key:
                raise ValueError("API key required")
            client = OpenAI(api_key=provider.api_key, base_url=OpenRouterProvider.base_url)
            client.models.list()
        elif kind == Provider.OPENAI_COMPATIBLE:
            if not provider.base_url:
                raise ValueError("Base URL required")
            if not provider.api_key:
                raise ValueError("API key required")
            client = OpenAI(api_key=provider.api_key, base_url=provider.base_url)
            client.models.list()
        elif kind == Provider.WHISPER_CPP:
            base_url = (provider.base_url or "").rstrip("/")
            if not base_url:
                raise ValueError("Host URL required")
            resp = requests.get(f"{base_url}/health", timeout=10)
            if resp.status_code != 200:
                raise ConnectionError(f"Whisper server unhealthy: HTTP {resp.status_code}")
        else:
            raise ValueError(f"Unknown provider kind: {kind}")

        latency_ms = int((time.monotonic() - start) * 1000)
        return ProviderTestResult(ok=True, message="Connected successfully", latency_ms=latency_ms)
    except Exception as e:
        latency_ms = int((time.monotonic() - start) * 1000)
        return ProviderTestResult(ok=False, message=str(e), latency_ms=latency_ms)
