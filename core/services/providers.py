import json
import re
from abc import ABC, abstractmethod
from decimal import Decimal
from pathlib import Path

import requests
from google import genai
from google.genai import types

from core.models import (
    AnalysisReport,
    Config,
    PodcastEpisodeAdverts,
    Provider,
    Transcription,
    TranscriptionReport,
    TranscriptionSegment,
)
from core.services.prompts import ANALYSE_ADVERTS_PROMPT, TRANSCRIBE_AUDIO_PROMPT

TRANSCRIPTION_TIMEOUT = 1200  # 20 minutes
ANALYSIS_TIMEOUT = 300  # 5 minutes


class AIProviderBase(ABC):
    @abstractmethod
    def transcribe(self, audio_path: Path, report: TranscriptionReport = None) -> Transcription:
        pass

    @abstractmethod
    def analyse_adverts(
        self, transcription: Transcription, report: AnalysisReport = None
    ) -> PodcastEpisodeAdverts:
        pass

    def calculate_cost(self, input_tokens, output_tokens, model_config):
        input_cost = (
            Decimal(input_tokens) / Decimal(1_000_000) * model_config.input_price / Decimal(100)
        )
        output_cost = (
            Decimal(output_tokens) / Decimal(1_000_000) * model_config.output_price / Decimal(100)
        )
        return float(input_cost + output_cost)


class GeminiProvider(AIProviderBase):
    @staticmethod
    def _strip_code_fences(text: str) -> str:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
        return text

    def transcribe(self, audio_path: Path, report: TranscriptionReport = None) -> Transcription:
        config = Config.get_instance()
        model_config = config.transcription_model

        if not model_config:
            raise ValueError("No transcription model configured")

        if not config.gemini_api_key:
            raise ValueError("No Gemini API key configured")

        client = genai.Client(
            api_key=config.gemini_api_key,
            http_options=types.HttpOptions(timeout=TRANSCRIPTION_TIMEOUT * 1000),
        )
        audio_file = client.files.upload(file=audio_path)

        prompt = TRANSCRIBE_AUDIO_PROMPT

        response = client.models.generate_content(
            model=model_config.name,
            contents=[audio_file, prompt],
        )

        if report and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            total_tokens = getattr(response.usage_metadata, "total_token_count", 0) or 0
            output_tokens = total_tokens - input_tokens
            report.input_tokens = input_tokens
            report.output_tokens = output_tokens
            report.cost_usd = self.calculate_cost(input_tokens, output_tokens, model_config)

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
        self, transcription: Transcription, report: AnalysisReport = None
    ) -> PodcastEpisodeAdverts:
        config = Config.get_instance()
        model_config = config.analysis_model

        if not model_config:
            raise ValueError("No analysis model configured")

        if not config.gemini_api_key:
            raise ValueError("No Gemini API key configured")

        client = genai.Client(
            api_key=config.gemini_api_key,
            http_options=types.HttpOptions(timeout=ANALYSIS_TIMEOUT * 1000),
        )

        transcript_json = json.dumps(transcription.model_dump(), indent=2)
        prompt = ANALYSE_ADVERTS_PROMPT.format(transcript=transcript_json)

        response = client.models.generate_content(
            model=model_config.name,
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
            report.cost_usd = self.calculate_cost(input_tokens, output_tokens, model_config)

        text = self._strip_code_fences(response.text)
        data = PodcastEpisodeAdverts.model_validate(json.loads(text))
        return data


class WhisperProvider(AIProviderBase):
    def transcribe(self, audio_path: Path, report: TranscriptionReport = None) -> Transcription:
        config = Config.get_instance()
        model_config = config.transcription_model

        if not model_config:
            raise ValueError("No transcription model configured")

        if not model_config.host:
            raise ValueError("No Whisper host configured for this model")

        base_url = model_config.host.rstrip("/")

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
        self, transcription: Transcription, report: AnalysisReport = None
    ) -> PodcastEpisodeAdverts:
        raise NotImplementedError("WhisperProvider only supports transcription, not analysis")


def get_ai_provider(task_type: str) -> AIProviderBase:
    if task_type not in ("transcription", "analysis"):
        raise ValueError(f"Invalid task_type: {task_type}. Must be 'transcription' or 'analysis'")

    config = Config.get_instance()

    if task_type == "transcription":
        model_config = config.transcription_model
        if not model_config:
            raise ValueError("No transcription model configured")
    else:
        model_config = config.analysis_model
        if not model_config:
            raise ValueError("No analysis model configured")

    provider_type = Provider(model_config.provider)

    if task_type == "analysis" and provider_type == Provider.WHISPER:
        raise ValueError("Whisper does not support analysis, only transcription")

    provider_map = {
        Provider.WHISPER: WhisperProvider,
        Provider.GEMINI: GeminiProvider,
    }

    if provider_type not in provider_map:
        raise ValueError(f"Unsupported provider: {provider_type}")

    return provider_map[provider_type]()
