import json

from core.models import AnalysisReport, PodcastEpisode, Transcription
from core.services.providers import AIProviderBase, get_ai_provider


def analyse_episode(
    episode: PodcastEpisode,
    report: AnalysisReport,
    provider: AIProviderBase = None,
) -> None:
    if not episode.transcription:
        raise ValueError(f"Episode {episode.title} has no transcription")

    if provider is None:
        provider = get_ai_provider("analysis")

    adverts_response = provider.analyse_adverts(
        Transcription(segments=episode.transcription),
        report=report,
    )

    report.adverts_found = len(adverts_response.adverts)

    episode.ads = adverts_response.adverts
    episode.save(update_fields=["ads"])

    episode.ads_path.write_text(json.dumps(adverts_response.model_dump(), indent=2))
