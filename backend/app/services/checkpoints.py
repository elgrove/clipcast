"""Persist successful provider calls for retries of one pipeline."""

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

from app.config import settings
from app.models import AdBreak, AIModel
from app.services.providers import Transcription, TrimResponse


def checkpoint_directory(report_id: str) -> Path:
    return settings.podcasts_path / ".checkpoints" / report_id


def clear_checkpoints(report_id: str) -> None:
    shutil.rmtree(checkpoint_directory(report_id), ignore_errors=True)


class CheckpointProvider:
    def __init__(self, provider, report_id: str):
        self.provider = provider
        self.scope = None
        self.directory = checkpoint_directory(report_id)
        model = getattr(provider, "model_config", None)
        self.identity = (
            model.model_dump(mode="json") if isinstance(model, AIModel) else type(provider).__name__
        )

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def _call(self, kind, inputs, report, call, encode, decode):
        key = hashlib.sha256(
            json.dumps(
                [self.identity, self.scope, kind, inputs], sort_keys=True, default=str
            ).encode()
        ).hexdigest()
        path = self.directory / f"{key}.json"
        try:
            saved = json.loads(path.read_text())
            result = decode(saved["result"])
            if report is not None:
                for field, value in saved["report"].items():
                    setattr(report, field, value)
            return result
        except (FileNotFoundError, ValueError, KeyError):
            pass
        result = call()
        payload = {
            "result": encode(result),
            "report": report.model_dump(mode="json") if report else {},
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(descriptor, "w") as stream:
                json.dump(payload, stream)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return result

    def transcribe(self, audio_path, report=None):
        with open(audio_path, "rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return self._call(
            "transcription",
            digest,
            report,
            lambda: self.provider.transcribe(audio_path, report),
            lambda result: result.model_dump(mode="json"),
            Transcription.model_validate,
        )

    def analyse_ads(
        self, transcription, context, report=None, custom_instructions=None, chunk_range=None
    ):
        return self._call(
            "analysis",
            [transcription.model_dump(), context, custom_instructions, chunk_range],
            report,
            lambda: self.provider.analyse_ads(
                transcription,
                context,
                report=report,
                custom_instructions=custom_instructions,
                chunk_range=chunk_range,
            ),
            lambda result: [item.model_dump(mode="json") for item in result],
            lambda result: [AdBreak.model_validate(item) for item in result],
        )

    def analyse_trim(self, prompt, report=None):
        return self._call(
            "trim",
            prompt,
            report,
            lambda: self.provider.analyse_trim(prompt, report),
            lambda result: result.model_dump(mode="json"),
            TrimResponse.model_validate,
        )
