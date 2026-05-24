import json
import logging
import re
from abc import ABC, abstractmethod
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import requests
from google import genai
from google.genai import types
from openai import OpenAI
from pydantic import BaseModel as PydanticBaseModel

from app.models import (
    AdBreak,
    Advert,
    AIModel,
    AIProvider,
    AnalysisReport,
    AppConfig,
    Provider,
    TranscriptionReport,
    TranscriptionSegment,
)
from app.services.prompts import ANALYSE_AD_BREAKS_PROMPT, TRANSCRIBE_AUDIO_PROMPT

logger = logging.getLogger(__name__)

TRANSCRIPTION_TIMEOUT = 14400  # 4 hours — CPU whisper can be very slow
ANALYSIS_TIMEOUT = 300  # 5 minutes


class Transcription(PydanticBaseModel):
    segments: list[TranscriptionSegment] = []


class _AdvertOut(PydanticBaseModel):
    start_time: str
    end_time: str
    advert_for: str


class _AdBreakOut(PydanticBaseModel):
    start_time: str
    end_time: str
    adverts: list[_AdvertOut]


class AdBreaksResponse(PydanticBaseModel):
    """Structured-output schema sent to the model. Kept separate from the
    storage ``AdBreak`` so the model is forced to return per-advert detail
    (which anchors its reasoning to the transcript) even though the rest of
    the system only stores breaks."""

    breaks: list[_AdBreakOut] = []


def _response_to_ad_breaks(response: AdBreaksResponse) -> list[AdBreak]:
    return [
        AdBreak(
            start_time=b.start_time,
            end_time=b.end_time,
            adverts=[
                Advert(start_time=a.start_time, end_time=a.end_time, advert_for=a.advert_for)
                for a in b.adverts
            ],
        )
        for b in response.breaks
    ]


def _format_chunk_range(chunk_range: tuple[float, float]) -> str:
    def hhmm(s: float) -> str:
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        return f"{h:02d}:{m:02d}"

    start, end = chunk_range
    return (
        f"\n\nNote: this transcript is a window from {hhmm(start)} to {hhmm(end)} of a longer "
        "episode. Treat this window in isolation when applying the 10-minute rarity rule."
    )


class AIProviderBase(ABC):
    @abstractmethod
    def transcribe(self, audio_path: Path, report: TranscriptionReport = None) -> Transcription:
        pass

    @abstractmethod
    def analyse_ad_breaks(
        self,
        transcription: Transcription,
        report: AnalysisReport = None,
        custom_instructions: str | None = None,
        chunk_range: tuple[float, float] | None = None,
    ) -> list[AdBreak]:
        pass

    def calculate_cost(self, input_tokens, output_tokens, model_config: AIModel):
        input_cost = (
            Decimal(input_tokens)
            / Decimal(1_000_000)
            * Decimal(str(model_config.input_price))
            / Decimal(100)
        )
        output_cost = (
            Decimal(output_tokens)
            / Decimal(1_000_000)
            * Decimal(str(model_config.output_price))
            / Decimal(100)
        )
        return float(input_cost + output_cost)


class GeminiProvider(AIProviderBase):
    def __init__(self, provider_config: AIProvider, model_config: AIModel):
        if not provider_config.api_key:
            raise ValueError(f"No API key configured for provider {provider_config.name}")
        self.api_key = provider_config.api_key
        self.provider_config = provider_config
        self.model_config = model_config

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        return text

    def transcribe(self, audio_path: Path, report: TranscriptionReport = None) -> Transcription:
        logger.info("Transcribing with Gemini model %s", self.model_config.name)

        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=TRANSCRIPTION_TIMEOUT * 1000),
        )
        audio_file = client.files.upload(file=audio_path)

        response = client.models.generate_content(
            model=self.model_config.name,
            contents=[audio_file, TRANSCRIBE_AUDIO_PROMPT],
        )

        if report and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            total_tokens = getattr(response.usage_metadata, "total_token_count", 0) or 0
            output_tokens = total_tokens - input_tokens
            report.input_tokens = input_tokens
            report.output_tokens = output_tokens
            report.cost_usd = self.calculate_cost(input_tokens, output_tokens, self.model_config)

        text = self._strip_code_fences(response.text)
        data = json.loads(text)
        segments = [
            TranscriptionSegment(
                start_time=seg["start_time"],
                end_time=seg["end_time"],
                text=seg["text"].strip(),
            )
            for seg in data
            if seg.get("text", "").strip()
        ]
        return Transcription(segments=segments)

    def analyse_ad_breaks(
        self,
        transcription: Transcription,
        report: AnalysisReport = None,
        custom_instructions: str | None = None,
        chunk_range: tuple[float, float] | None = None,
    ) -> list[AdBreak]:
        logger.info("Analysing ad breaks with Gemini model %s", self.model_config.name)

        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=ANALYSIS_TIMEOUT * 1000),
        )

        transcript_json = json.dumps(transcription.model_dump(), indent=2)
        prompt = ANALYSE_AD_BREAKS_PROMPT.format(transcript=transcript_json)
        if chunk_range is not None:
            prompt += _format_chunk_range(chunk_range)
        if custom_instructions:
            prompt += f"\n\nAdditional instructions:\n{custom_instructions}"

        response = client.models.generate_content(
            model=self.model_config.name,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AdBreaksResponse,
            ),
        )

        if report and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            total_tokens = getattr(response.usage_metadata, "total_token_count", 0) or 0
            output_tokens = total_tokens - input_tokens
            report.input_tokens = input_tokens
            report.output_tokens = output_tokens
            report.cost_usd = self.calculate_cost(input_tokens, output_tokens, self.model_config)

        text = self._strip_code_fences(response.text)
        parsed = AdBreaksResponse.model_validate(json.loads(text))
        return _response_to_ad_breaks(parsed)


class WhisperProvider(AIProviderBase):
    def __init__(self, provider_config: AIProvider, model_config: AIModel):
        self.provider_config = provider_config
        self.model_config = model_config

    def _check_health(self, base_url: str) -> None:
        try:
            resp = requests.get(f"{base_url}/health", timeout=10)
            if resp.status_code != 200:
                raise ConnectionError(f"Whisper server unhealthy: HTTP {resp.status_code}")
        except requests.ConnectionError as e:
            raise ConnectionError(f"Whisper server unreachable at {base_url}: {e}") from e

    def transcribe(self, audio_path: Path, report: TranscriptionReport = None) -> Transcription:
        base_url = (self.provider_config.base_url or "").rstrip("/")
        if not base_url:
            raise ValueError("No Whisper URL configured for this provider")

        self._check_health(base_url)
        logger.info("Transcribing with Whisper at %s (file: %s)", base_url, audio_path.name)

        with open(audio_path, "rb") as audio_file:
            response = requests.post(
                f"{base_url}/inference",
                files={"file": (audio_path.name, audio_file, "audio/mpeg")},
                data={"response_format": "verbose_json"},
                timeout=TRANSCRIPTION_TIMEOUT,
            )
        response.raise_for_status()
        data = response.json()

        segments = [
            TranscriptionSegment(
                start_time=seg["start"],
                end_time=seg["end"],
                text=seg["text"].strip(),
            )
            for seg in data.get("segments", [])
            if seg.get("text", "").strip()
        ]
        return Transcription(segments=segments)

    def analyse_ad_breaks(
        self,
        transcription: Transcription,
        report: AnalysisReport = None,
        custom_instructions: str | None = None,
        chunk_range: tuple[float, float] | None = None,
    ) -> list[AdBreak]:
        raise NotImplementedError("WhisperProvider only supports transcription, not analysis")


class OpenAICompatibleProvider(AIProviderBase):
    """Shared base for any provider exposing an OpenAI-compatible Chat Completions API
    (OpenAI itself, OpenRouter, vLLM, LM Studio, Together, Groq, DeepSeek, ...).

    Subclasses override class-level config (`base_url`, `default_headers`) and the
    hook methods at the bottom for vendor-specific behaviour. The api_key and any
    custom base_url come from ``provider_config`` (per-provider storage)."""

    base_url: ClassVar[str] = ""
    default_headers: ClassVar[dict[str, str]] = {}

    def __init__(self, provider_config: AIProvider, model_config: AIModel):
        self.provider_config = provider_config
        self.model_config = model_config
        if not provider_config.api_key:
            raise ValueError(f"No API key configured for provider {provider_config.name}")

    def _client(self) -> OpenAI:
        return OpenAI(api_key=self.provider_config.api_key, base_url=self._resolve_base_url())

    def transcribe(self, audio_path: Path, report: TranscriptionReport = None) -> Transcription:
        logger.info(
            "Transcribing with %s model %s",
            type(self).__name__,
            self.model_config.name,
        )
        with open(audio_path, "rb") as audio_file:
            response = self._client().audio.transcriptions.create(
                model=self.model_config.name,
                file=(audio_path.name, audio_file, "audio/mpeg"),
                response_format="verbose_json",
                extra_headers=self.default_headers or None,
                timeout=TRANSCRIPTION_TIMEOUT,
            )
        segments = [
            TranscriptionSegment(
                start_time=seg.start,
                end_time=seg.end,
                text=seg.text.strip(),
            )
            for seg in (response.segments or [])
            if seg.text.strip()
        ]
        return Transcription(segments=segments)

    def analyse_ad_breaks(
        self,
        transcription: Transcription,
        report: AnalysisReport = None,
        custom_instructions: str | None = None,
        chunk_range: tuple[float, float] | None = None,
    ) -> list[AdBreak]:
        logger.info(
            "Analysing ad breaks with %s model %s",
            type(self).__name__,
            self.model_config.name,
        )

        transcript_json = json.dumps(transcription.model_dump(), indent=2)
        prompt = ANALYSE_AD_BREAKS_PROMPT.format(transcript=transcript_json)
        if chunk_range is not None:
            prompt += _format_chunk_range(chunk_range)
        if custom_instructions:
            prompt += f"\n\nAdditional instructions:\n{custom_instructions}"

        completion = self._client().beta.chat.completions.parse(
            model=self.model_config.name,
            messages=[{"role": "user", "content": prompt}],
            response_format=AdBreaksResponse,
            extra_headers=self.default_headers or None,
            timeout=ANALYSIS_TIMEOUT,
            **self._extra_request_kwargs(),
        )

        usage = getattr(completion, "usage", None)
        if report is not None and usage is not None:
            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            output_tokens = getattr(usage, "completion_tokens", 0) or 0
            report.input_tokens = input_tokens
            report.output_tokens = output_tokens
            reported_cost = self._extract_cost(completion)
            report.cost_usd = (
                reported_cost
                if reported_cost is not None
                else self.calculate_cost(input_tokens, output_tokens, self.model_config)
            )

        parsed = completion.choices[0].message.parsed
        if parsed is None:
            content = completion.choices[0].message.content or ""
            parsed = AdBreaksResponse.model_validate_json(content)
        return _response_to_ad_breaks(parsed)

    # ── override points ─────────────────────────────────────────────────────────

    def _resolve_base_url(self) -> str:
        """Default: class-level, falling back to ``provider_config.base_url`` for
        generic OpenAI-compatible endpoints where the user provides a URL."""
        return self.base_url or self.provider_config.base_url

    def _extra_request_kwargs(self) -> dict:
        """Override to inject extra request kwargs — e.g. OpenRouter's
        ``extra_body={"usage": {"include": True}}`` to get cost in the response."""
        return {}

    def _extract_cost(self, completion) -> float | None:
        """Override if the vendor returns cost in the response (e.g. OpenRouter's
        ``usage.cost``). Return ``None`` to fall back to ``calculate_cost()``."""
        return None


class OpenAIProvider(OpenAICompatibleProvider):
    base_url = "https://api.openai.com/v1"


class OpenRouterProvider(OpenAICompatibleProvider):
    base_url = "https://openrouter.ai/api/v1"

    def _extra_request_kwargs(self) -> dict:
        return {"extra_body": {"usage": {"include": True}}}

    def _extract_cost(self, completion) -> float | None:
        usage = getattr(completion, "usage", None)
        if usage is None:
            return None
        return getattr(usage, "cost", None)


def get_ai_provider(task_type: str, config: AppConfig) -> AIProviderBase:
    if task_type not in ("transcription", "analysis"):
        raise ValueError(f"Invalid task_type: {task_type}. Must be 'transcription' or 'analysis'")

    if task_type == "transcription":
        model_config = config.transcription_model
        if not model_config:
            raise ValueError("No transcription model configured")
    else:
        model_config = config.analysis_model
        if not model_config:
            raise ValueError("No analysis model configured")

    provider_config = model_config.provider
    provider_kind = Provider(provider_config.kind)

    if task_type == "analysis" and provider_kind == Provider.WHISPER_CPP:
        raise ValueError("Whisper.cpp does not support analysis, only transcription")

    if provider_kind == Provider.GEMINI:
        return GeminiProvider(provider_config=provider_config, model_config=model_config)

    if provider_kind == Provider.OPENAI:
        return OpenAIProvider(provider_config=provider_config, model_config=model_config)

    if provider_kind == Provider.OPENROUTER:
        return OpenRouterProvider(provider_config=provider_config, model_config=model_config)

    if provider_kind == Provider.OPENAI_COMPATIBLE:
        return OpenAICompatibleProvider(provider_config=provider_config, model_config=model_config)

    if provider_kind == Provider.WHISPER_CPP:
        return WhisperProvider(provider_config=provider_config, model_config=model_config)

    raise ValueError(f"Unsupported provider kind: {provider_kind}")
