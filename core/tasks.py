import logging

from django.conf import settings
from django.utils import timezone
from django_q.tasks import async_task

from core.models import (
    AnalysisReport,
    ClippingReport,
    Config,
    PodcastEpisode,
    PodcastShow,
    TranscriptionReport,
)
from core.services.analysis import analyse_episode
from core.services.download import download_episode
from core.services.editor import edit_episode
from core.services.rss import (
    parse_rss_feed,
    sync_podcast_episodes_from_rss,
    sync_podcast_show_from_rss,
)
from core.services.transcription import transcribe_episode

logger = logging.getLogger(__name__)


def sync_podcast_show(podcast_id: str) -> PodcastShow:
    podcast = PodcastShow.objects.get(id=podcast_id)
    logger.info(f"Syncing podcast show: {podcast.title}")
    sync_podcast_show_from_rss(podcast)
    logger.info(f"Successfully synced podcast show: {podcast.title}")
    return podcast


def sync_podcast_episodes(podcast_id: str, max_episodes: int = None) -> int:
    podcast = PodcastShow.objects.get(id=podcast_id)
    episodes = sync_podcast_episodes_from_rss(podcast, max_episodes=max_episodes)
    if not podcast.initial_sync_completed:
        podcast.initial_sync_completed = True
        podcast.save(update_fields=["initial_sync_completed"])
        logger.info(f"Initial sync completed for: {podcast.title}")
    return len(episodes)


def sync_all_podcast_episodes() -> dict[str, int]:
    results = {}
    podcasts = PodcastShow.objects.all()

    for podcast in podcasts:
        try:
            episodes = sync_podcast_episodes_from_rss(podcast)
            results[str(podcast.id)] = len(episodes)
        except Exception as e:
            logger.error(f"Failed to sync episodes for {podcast.title}: {e}")
            results[str(podcast.id)] = -1

    return results


def sync_and_process_new_episodes() -> dict[str, int]:
    results = {}
    podcasts = PodcastShow.objects.filter(initial_sync_completed=True)

    for podcast in podcasts:
        try:
            sync_podcast_show_from_rss(podcast)

            rss_data = parse_rss_feed(podcast.source_rss_url)
            new_count = 0
            incomplete_count = 0

            for ep in rss_data.episodes:
                if not ep.guid or not ep.audio_url:
                    continue

                episode, created = PodcastEpisode.objects.update_or_create(
                    podcast=podcast,
                    guid=ep.guid,
                    defaults={
                        "title": ep.title,
                        "description": ep.description,
                        "published_at": ep.published_at,
                        "duration": ep.duration,
                        "source_audio_url": ep.audio_url,
                    },
                )

                if not podcast.has_ads:
                    continue

                if created:
                    new_count += 1
                    queue_episode_for_clipping(
                        episode,
                        task_name_prefix="Clip (Auto)",
                        initial_log=f"Discovered new episode: {episode.title}",
                        run_async=not settings.Q_CLUSTER.get("sync", False),
                    )
                elif episode.mp3_path.exists() and not episode.raw_path.exists():
                    incomplete_count += 1
                    logger.info(f"Re-clipping incomplete episode: {episode.title}")
                    queue_episode_for_clipping(
                        episode,
                        task_name_prefix="Clip (Retry)",
                        initial_log=f"Resuming incomplete clipping for: {episode.title}",
                        run_async=not settings.Q_CLUSTER.get("sync", False),
                    )

            results[str(podcast.id)] = new_count
            log_parts = [f"found {new_count} new episodes"]
            if incomplete_count > 0:
                log_parts.append(f"re-queued {incomplete_count} incomplete episodes")
            logger.info(f"Synced {podcast.title}: {', '.join(log_parts)}")
        except Exception as e:
            logger.error(f"Failed to sync/process episodes for {podcast.title}: {e}")
            results[str(podcast.id)] = -1

    return results


def run_clipping_pipeline_for_episode(
    episode: PodcastEpisode, report: ClippingReport
) -> ClippingReport:
    config = Config.get_instance()

    if not config.transcription_model:
        raise ValueError(
            "Transcription model not configured. Please configure it in the admin panel."
        )
    if not config.analysis_model:
        raise ValueError("Analysis model not configured. Please configure it in the admin panel.")

    report.transcription_model = config.transcription_model
    report.analysis_model = config.analysis_model

    report.append_log(f"Starting clipping pipeline for episode: {episode.title}")
    report.save()

    try:
        # Download step - skip if already downloaded
        if episode.mp3_path.exists():
            report.append_log("Episode already downloaded, skipping download")
        else:
            report.append_log("Downloading episode...")
            download_episode(episode)
            report.downloaded_at = timezone.now()
            report.append_log("Download complete")
        report.save()

        # Transcription step - skip if already transcribed
        if episode.transcription:
            report.append_log("Episode already transcribed, skipping transcription")
        else:
            report.append_log("Transcribing episode...")
            transcription_report = TranscriptionReport(
                started_at=timezone.now().isoformat(),
                provider=config.transcription_model.provider,
                model_name=config.transcription_model.name,
            )
            try:
                transcribe_episode(episode, report=transcription_report)
                transcription_report.completed_at = timezone.now().isoformat()
            except Exception as e:
                transcription_report.error = str(e)
                report.transcription = transcription_report
                report.save()
                raise
            report.transcription = transcription_report
            report.transcribed_at = timezone.now()
            report.append_log("Transcription complete")
        report.save()

        # Analysis step - skip if already analysed
        if episode.ads:
            report.append_log("Episode already analysed, skipping analysis")
        else:
            report.append_log("Analysing episode for adverts...")
            analysis_report = AnalysisReport(
                started_at=timezone.now().isoformat(),
                provider=config.analysis_model.provider,
                model_name=config.analysis_model.name,
            )
            try:
                analyse_episode(episode, report=analysis_report)
                analysis_report.completed_at = timezone.now().isoformat()
                analysis_report.adverts_found = len(episode.ads) if episode.ads else 0
            except Exception as e:
                analysis_report.error = str(e)
                report.analysis = analysis_report
                report.save()
                raise
            report.analysis = analysis_report
            report.analysed_at = timezone.now()
            report.append_log(f"Analysis complete - found {len(episode.ads)} adverts")
        report.save()

        report.append_log("Editing episode...")
        edit_episode(episode)
        report.edited_at = timezone.now()
        report.append_log("Clipping pipeline completed successfully")
        report.save()

    except Exception as e:
        report.add_exception(e)
        report.append_log(f"Pipeline failed: {e}")
        report.save()
        raise

    return report


def queue_episode_for_clipping(
    episode: PodcastEpisode,
    task_name_prefix: str = "Clip",
    initial_log: str = None,
    run_async: bool = True,
) -> ClippingReport:
    report = ClippingReport.objects.create(episode=episode)
    if initial_log:
        report.append_log(initial_log)
    report.append_log(f"Episode queued for clipping: {episode.title}")
    report.save()

    if run_async:
        async_task(
            "core.tasks.run_clipping_pipeline_for_episode",
            episode,
            report,
            task_name=f"{task_name_prefix}: {episode.title[:50]}",
        )
    else:
        run_clipping_pipeline_for_episode(episode, report)

    return report
