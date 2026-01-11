from core.models import PodcastEpisode, TranscriptionReport
from core.services.providers import AIProviderBase, get_ai_provider


def transcribe_episode(
    episode: PodcastEpisode,
    report: TranscriptionReport,
    provider: AIProviderBase = None,
) -> None:
    if not episode.mp3_path.exists():
        raise ValueError(f"Episode {episode.title} has no downloaded audio file")

    if provider is None:
        provider = get_ai_provider("transcription")

    transcription_response = provider.transcribe(episode.mp3_path, report=report)

    report.segments_count = len(transcription_response.segments)

    episode.transcription = transcription_response.segments
    episode.save(update_fields=["transcription"])

    episode.srt_path.write_text(episode.transcription_to_srt())
