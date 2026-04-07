import logging
from datetime import timedelta
from pathlib import Path

import srt

from app.models import TranscriptionReport, TranscriptionSegment
from app.services.providers import AIProviderBase

logger = logging.getLogger(__name__)


def segments_to_srt(segments: list[TranscriptionSegment]) -> str:
    subtitles = [
        srt.Subtitle(
            index=i,
            start=timedelta(seconds=seg.start_time),
            end=timedelta(seconds=seg.end_time),
            content=seg.text,
        )
        for i, seg in enumerate(segments, 1)
    ]
    return srt.compose(subtitles)


def transcribe_audio(
    audio_path: Path,
    provider: AIProviderBase,
    report: TranscriptionReport,
) -> list[TranscriptionSegment]:
    if not audio_path.exists():
        raise ValueError(f"Audio file not found: {audio_path}")

    logger.info("Transcribing: %s", audio_path.name)
    transcription_response = provider.transcribe(audio_path, report=report)
    report.segments_count = len(transcription_response.segments)
    logger.info("Transcription complete: %d segments", report.segments_count)
    return transcription_response.segments
