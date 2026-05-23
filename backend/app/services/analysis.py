import logging

from app.models import AnalysisReport, PodcastEpisodeAdvert, TranscriptionSegment
from app.services.chunking import Chunk, chunk_segments, merge_adverts, should_chunk
from app.services.editor import parse_time_to_ms
from app.services.providers import AIProviderBase, Transcription

logger = logging.getLogger(__name__)


def _advert_centre_seconds(advert: PodcastEpisodeAdvert) -> float:
    start_ms = parse_time_to_ms(advert.start_time)
    end_ms = parse_time_to_ms(advert.end_time)
    return (start_ms + end_ms) / 2000.0


def _filter_to_primary(
    adverts: list[PodcastEpisodeAdvert], chunk: Chunk
) -> list[PodcastEpisodeAdvert]:
    """Drop adverts whose centre lies outside this chunk's primary range — the
    neighbouring chunk that owns that range will return them. Centre rather
    than start avoids losing ads that begin just before a boundary."""
    kept: list[PodcastEpisodeAdvert] = []
    for ad in adverts:
        centre = _advert_centre_seconds(ad)
        if chunk.primary_start <= centre <= chunk.primary_end:
            kept.append(ad)
    return kept


def analyse_transcription(
    segments: list[TranscriptionSegment],
    provider: AIProviderBase,
    report: AnalysisReport,
    custom_instructions: str | None = None,
) -> list[PodcastEpisodeAdvert]:
    context_window = getattr(provider.model_config, "context_window", 0)

    if not should_chunk(segments, context_window):
        logger.info("Analysing adverts (single call)")
        adverts_response = provider.analyse_adverts(
            Transcription(segments=segments),
            report=report,
            custom_instructions=custom_instructions,
        )
        report.adverts_found = len(adverts_response.adverts)
        logger.info("Analysis complete: %d adverts found", report.adverts_found)
        return adverts_response.adverts

    chunks = chunk_segments(segments, context_window)
    duration_h = segments[-1].end_time / 3600.0
    logger.info(
        "Analysing adverts in %d chunks (episode %.1fh, model ctx %d tokens)",
        len(chunks),
        duration_h,
        context_window,
    )

    per_chunk: list[list[PodcastEpisodeAdvert]] = []
    total_input = 0
    total_output = 0
    total_cost = 0.0
    for i, chunk in enumerate(chunks):
        sub_report = AnalysisReport(
            provider=report.provider,
            model_name=report.model_name,
        )
        response = provider.analyse_adverts(
            Transcription(segments=chunk.segments),
            report=sub_report,
            custom_instructions=custom_instructions,
            chunk_range=(chunk.primary_start, chunk.primary_end),
        )
        filtered = _filter_to_primary(response.adverts, chunk)
        per_chunk.append(filtered)
        total_input += sub_report.input_tokens or 0
        total_output += sub_report.output_tokens or 0
        total_cost += sub_report.cost_usd or 0.0
        logger.info(
            "Chunk %d/%d (%.0f-%.0fs): %d adverts (%d after primary-range filter)",
            i + 1,
            len(chunks),
            chunk.primary_start,
            chunk.primary_end,
            len(response.adverts),
            len(filtered),
        )

    merged = merge_adverts(per_chunk)

    report.input_tokens = total_input
    report.output_tokens = total_output
    report.cost_usd = total_cost
    report.adverts_found = len(merged)
    logger.info(
        "Chunked analysis complete: %d adverts (from %d across chunks)",
        len(merged),
        sum(len(c) for c in per_chunk),
    )
    return merged
