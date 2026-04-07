import logging

from app.models import AnalysisReport, PodcastEpisodeAdvert, TranscriptionSegment
from app.services.providers import AIProviderBase, Transcription

logger = logging.getLogger(__name__)


def analyse_transcription(
    segments: list[TranscriptionSegment],
    provider: AIProviderBase,
    report: AnalysisReport,
) -> list[PodcastEpisodeAdvert]:
    logger.info("Analysing adverts...")
    adverts_response = provider.analyse_adverts(
        Transcription(segments=segments),
        report=report,
    )
    report.adverts_found = len(adverts_response.adverts)
    logger.info("Analysis complete: %d adverts found", report.adverts_found)
    return adverts_response.adverts
