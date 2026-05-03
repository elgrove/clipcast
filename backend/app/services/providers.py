import json
import logging
import re
from abc import ABC, abstractmethod
from decimal import Decimal
from pathlib import Path

import requests
from google import genai
from google.genai import types
from openai import OpenAI
from pydantic import BaseModel as PydanticBaseModel

from app.models import (
    AIModel,
    AnalysisReport,
    AppConfig,
    PodcastEpisodeAdvert,
    Provider,
    TranscriptionReport,
    TranscriptionSegment,
)
from app.services.prompts import ANALYSE_ADVERTS_PROMPT, TRANSCRIBE_AUDIO_PROMPT

logger = logging.getLogger(__name__)

TRANSCRIPTION_TIMEOUT = 14400  # 4 hours — CPU whisper can be very slow
ANALYSIS_TIMEOUT = 300  # 5 minutes


class Transcription(PydanticBaseModel):
    segments: list[TranscriptionSegment] = []


class PodcastEpisodeAdverts(PydanticBaseModel):
    adverts: list[PodcastEpisodeAdvert] = []


class AIProviderBase(ABC):
    @abstractmethod
    def transcribe(self, audio_path: Path, report: TranscriptionReport = None) -> Transcription:
        pass

    @abstractmethod
    def analyse_adverts(
        self,
        transcription: Transcription,
        report: AnalysisReport = None,
        custom_instructions: str | None = None,
    ) -> PodcastEpisodeAdverts:
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
    def __init__(self, api_key: str, model_config: AIModel):
        self.api_key = api_key
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

    def analyse_adverts(
        self,
        transcription: Transcription,
        report: AnalysisReport = None,
        custom_instructions: str | None = None,
    ) -> PodcastEpisodeAdverts:
        logger.info("Analysing adverts with Gemini model %s", self.model_config.name)

        client = genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=ANALYSIS_TIMEOUT * 1000),
        )

        transcript_json = json.dumps(transcription.model_dump(), indent=2)
        prompt = ANALYSE_ADVERTS_PROMPT.format(transcript=transcript_json)
        if custom_instructions:
            prompt += f"\n\nAdditional instructions:\n{custom_instructions}"

        response = client.models.generate_content(
            model=self.model_config.name,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=PodcastEpisodeAdverts,
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
        return PodcastEpisodeAdverts.model_validate(json.loads(text))


class WhisperProvider(AIProviderBase):
    def __init__(self, model_config: AIModel):
        self.model_config = model_config

    def _check_health(self, base_url: str) -> None:
        try:
            resp = requests.get(f"{base_url}/health", timeout=10)
            if resp.status_code != 200:
                raise ConnectionError(f"Whisper server unhealthy: HTTP {resp.status_code}")
        except requests.ConnectionError as e:
            raise ConnectionError(f"Whisper server unreachable at {base_url}: {e}") from e

    def transcribe(self, audio_path: Path, report: TranscriptionReport = None) -> Transcription:
        base_url = (self.model_config.base_url or self.model_config.host or "").rstrip("/")
        if not base_url:
            raise ValueError("No Whisper URL configured for this model")

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

    def analyse_adverts(
        self,
        transcription: Transcription,
        report: AnalysisReport = None,
        custom_instructions: str | None = None,
    ) -> PodcastEpisodeAdverts:
        raise NotImplementedError("WhisperProvider only supports transcription, not analysis")


class OpenAICompatibleProvider(AIProviderBase):
    DEFAULT_BASE_URLS = {
        Provider.OPENROUTER: "https://openrouter.ai/api/v1",
    }

    def __init__(self, model_config: AIModel):
        self.model_config = model_config
        provider = Provider(model_config.provider)
        base_url = model_config.base_url or self.DEFAULT_BASE_URLS.get(provider)
        if not base_url:
            raise ValueError(f"base_url required for provider {provider}")
        self.client = OpenAI(api_key=model_config.api_key, base_url=base_url)

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        return text

    def transcribe(self, audio_path: Path, report: TranscriptionReport = None) -> Transcription:
        if Provider(self.model_config.provider) == Provider.OPENROUTER:
            raise NotImplementedError("OpenRouter does not support audio transcription")
        logger.info("Transcribing with OpenAI-compatible model %s", self.model_config.name)
        with open(audio_path, "rb") as audio_file:
            response = self.client.audio.transcriptions.create(
                model=self.model_config.name,
                file=(audio_path.name, audio_file, "audio/mpeg"),
                response_format="verbose_json",
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

    def analyse_adverts(
        self,
        transcription: Transcription,
        report: AnalysisReport = None,
        custom_instructions: str | None = None,
    ) -> PodcastEpisodeAdverts:
        logger.info("Analysing adverts with OpenAI-compatible model %s", self.model_config.name)
        transcript_json = json.dumps(transcription.model_dump(), indent=2)
        prompt = ANALYSE_ADVERTS_PROMPT.format(transcript=transcript_json)
        if custom_instructions:
            prompt += f"\n\nAdditional instructions:\n{custom_instructions}"
        response = self.client.chat.completions.create(
            model=self.model_config.name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            timeout=ANALYSIS_TIMEOUT,
        )
        if report and response.usage:
            report.input_tokens = response.usage.prompt_tokens
            report.output_tokens = response.usage.completion_tokens
            report.cost_usd = self.calculate_cost(
                response.usage.prompt_tokens, response.usage.completion_tokens, self.model_config
            )
        text = self._strip_code_fences(response.choices[0].message.content)
        return PodcastEpisodeAdverts.model_validate(json.loads(text))


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

    provider_type = Provider(model_config.provider)

    if task_type == "analysis" and provider_type == Provider.WHISPER_CPP:
        raise ValueError("Whisper.cpp does not support analysis, only transcription")
    if task_type == "transcription" and provider_type == Provider.OPENROUTER:
        raise ValueError("OpenRouter does not support transcription")

    if provider_type == Provider.GEMINI:
        api_key = model_config.api_key or config.gemini_api_key
        if not api_key:
            raise ValueError("No Gemini API key configured")
        return GeminiProvider(api_key=api_key, model_config=model_config)

    if provider_type in (Provider.OPENAI_COMPATIBLE, Provider.OPENROUTER):
        return OpenAICompatibleProvider(model_config=model_config)

    if provider_type == Provider.WHISPER_CPP:
        return WhisperProvider(model_config=model_config)

    raise ValueError(f"Unsupported provider: {provider_type}")
