import json
import logging
from datetime import datetime, timedelta

from celery import chain
from pydub import AudioSegment
from sqlmodel import Session, select

from app.database import engine
from app.models import (
    AdBreak,
    AnalysisReport,
    AppConfig,
    ClipMode,
    ClippingReport,
    PodcastEpisode,
    PodcastShow,
    Provider,
    RefinementReport,
    TranscriptionReport,
)
from app.services.download import download_episode
from app.services.editor import edit_episode, format_ms_to_time, parse_time_to_ms
from app.services.providers import get_ai_provider
from app.services.refinement import refine_or_snap_boundary
from app.worker import celery_app

logger = logging.getLogger("clipcast")

STALE_REPORT_THRESHOLD = timedelta(hours=4)


def _update_report(report_id: str, **fields) -> None:
    with Session(engine) as session:
        report = session.get(ClippingReport, report_id)
        for key, value in fields.items():
            setattr(report, key, value)
        session.add(report)
        session.commit()


def _log_report(report_id: str, message: str) -> None:
    with Session(engine) as session:
        report = session.get(ClippingReport, report_id)
        report.append_log(message)
        session.add(report)
        session.commit()


def _fail_report(report_id: str, exception: Exception, message: str) -> None:
    with Session(engine) as session:
        report = session.get(ClippingReport, report_id)
        report.add_exception(exception)
        report.append_log(message)
        session.add(report)
        session.commit()


# ── Pipeline step tasks ──────────────────────────────────────────────────────


@celery_app.task(
    name="app.tasks.task_download",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    soft_time_limit=600,
    time_limit=660,
)
def task_download(self, episode_id: str, report_id: str) -> None:
    with Session(engine) as session:
        episode = session.get(PodcastEpisode, episode_id)
        if not episode:
            raise ValueError(f"Episode not found: {episode_id}")

        # Lock the filename before first download so it never changes
        episode.lock_filename()
        session.add(episode)
        session.commit()

        if episode.mp3_path.exists():
            _log_report(report_id, "Episode already downloaded, skipping")
            return

        _log_report(report_id, "Downloading episode...")
        try:
            download_episode(episode)
        except Exception as e:
            _fail_report(report_id, e, f"Download failed: {e}")
            raise

    _update_report(report_id, downloaded_at=datetime.utcnow())
    _log_report(report_id, "Download complete")


@celery_app.task(
    name="app.tasks.task_transcribe",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    soft_time_limit=14400,
    time_limit=14700,
)
def task_transcribe(self, episode_id: str, report_id: str) -> None:
    from app.services.providers import get_ai_provider
    from app.services.transcription import segments_to_srt, transcribe_audio

    # Brief DB read: get what we need
    with Session(engine) as session:
        episode = session.get(PodcastEpisode, episode_id)
        if not episode:
            raise ValueError(f"Episode not found: {episode_id}")

        if episode.transcription:
            _log_report(report_id, "Episode already transcribed, skipping")
            return

        config = session.get(AppConfig, "config")
        if not config or not config.transcription_model:
            raise ValueError("Transcription model not configured")

        audio_path = episode.mp3_path
        srt_path = episode.srt_path
        provider = get_ai_provider("transcription", config)
        model_provider = config.transcription_model.provider.kind
        model_name = config.transcription_model.name

    # Update report with model info
    _update_report(report_id, transcription_model_id=config.transcription_model_id)
    _log_report(report_id, "Transcribing episode...")

    # Long I/O: no DB session held
    transcription_report = TranscriptionReport(
        started_at=datetime.utcnow().isoformat(),
        provider=model_provider,
        model_name=model_name,
    )
    try:
        segments = transcribe_audio(audio_path, provider, transcription_report)
        transcription_report.completed_at = datetime.utcnow().isoformat()
    except Exception as e:
        transcription_report.error = str(e)
        with Session(engine) as session:
            report = session.get(ClippingReport, report_id)
            report.transcription_report = transcription_report
            report.add_exception(e)
            report.append_log(f"Transcription failed: {e}")
            session.add(report)
            session.commit()
        raise

    # Brief DB write: save results
    with Session(engine) as session:
        episode = session.get(PodcastEpisode, episode_id)
        episode.transcription = segments
        session.add(episode)
        session.commit()

        report = session.get(ClippingReport, report_id)
        report.transcription_report = transcription_report
        report.transcribed_at = datetime.utcnow()
        report.append_log("Transcription complete")
        session.add(report)
        session.commit()

    # Write SRT file (no DB needed)
    srt_path.write_text(segments_to_srt(segments))


@celery_app.task(
    name="app.tasks.task_analyse",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    soft_time_limit=600,
    time_limit=660,
)
def task_analyse(self, episode_id: str, report_id: str) -> None:
    from app.services.analysis import analyse_transcription
    from app.services.providers import get_ai_provider

    # Brief DB read
    with Session(engine) as session:
        episode = session.get(PodcastEpisode, episode_id)
        if not episode:
            raise ValueError(f"Episode not found: {episode_id}")

        if episode.ad_breaks:
            _log_report(report_id, "Episode already analysed, skipping")
            return

        segments = episode.transcription
        ad_breaks_path = episode.ad_breaks_path
        custom_instructions = episode.podcast.custom_prompt or None

        config = session.get(AppConfig, "config")
        if not config or not config.analysis_model:
            raise ValueError("Analysis model not configured")

        provider = get_ai_provider("analysis", config)
        model_provider = config.analysis_model.provider.kind
        model_name = config.analysis_model.name

    _update_report(report_id, analysis_model_id=config.analysis_model_id)
    _log_report(report_id, "Analysing episode for ad breaks...")

    # I/O: no DB session held
    analysis_report = AnalysisReport(
        started_at=datetime.utcnow().isoformat(),
        provider=model_provider,
        model_name=model_name,
    )
    try:
        breaks = analyse_transcription(segments, provider, analysis_report, custom_instructions)
        analysis_report.completed_at = datetime.utcnow().isoformat()
    except Exception as e:
        analysis_report.error = str(e)
        with Session(engine) as session:
            report = session.get(ClippingReport, report_id)
            report.analysis_report = analysis_report
            report.add_exception(e)
            report.append_log(f"Analysis failed: {e}")
            session.add(report)
            session.commit()
        raise

    # Brief DB write
    with Session(engine) as session:
        episode = session.get(PodcastEpisode, episode_id)
        episode.ad_breaks = breaks
        session.add(episode)
        session.commit()

        report = session.get(ClippingReport, report_id)
        report.analysis_report = analysis_report
        report.analysed_at = datetime.utcnow()
        report.append_log(f"Analysis complete — found {len(breaks)} ad breaks")
        session.add(report)
        session.commit()

    # Write JSON file (audit trail)
    ad_breaks_path.write_text(json.dumps({"breaks": [b.model_dump() for b in breaks]}, indent=2))


@celery_app.task(
    name="app.tasks.task_refine_boundaries",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    soft_time_limit=1800,
    time_limit=1860,
)
def task_refine_boundaries(self, episode_id: str, report_id: str) -> None:
    """WIP — not invoked by `queue_episode_for_clipping`. See the module
    docstring on `app.services.refinement` for the rationale.

    Refine the outer edges of each ad break produced by `task_analyse` using
    a Gemini audio model. For each break, sends a 20s window around each edge
    to the model and updates the timestamp with the model's exact offset. Edges
    that fall within SNAP_TO_EDGE_MS of episode start/end are snapped instead.
    Inner advert boundaries within a break are preserved unchanged — only the
    outer cut points matter for editing.

    Opt-in: if no boundary_refinement_model is configured, this task no-ops and
    leaves the analysed timestamps untouched."""
    with Session(engine) as session:
        report = session.get(ClippingReport, report_id)
        if report and report.refined_at:
            _log_report(report_id, "Boundaries already refined, skipping")
            return

        episode = session.get(PodcastEpisode, episode_id)
        if not episode:
            raise ValueError(f"Episode not found: {episode_id}")

        breaks = list(episode.ad_breaks)
        if not breaks:
            _log_report(report_id, "No ad breaks to refine — skipping refinement step")
            _update_report(report_id, refined_at=datetime.utcnow())
            return

        config = session.get(AppConfig, "config")
        if not config or not config.boundary_refinement_model:
            _log_report(
                report_id,
                "Boundary refinement skipped — no refinement model configured",
            )
            _update_report(report_id, refined_at=datetime.utcnow())
            return

        try:
            provider = get_ai_provider("boundary_refinement", config)
        except ValueError as e:
            _log_report(report_id, f"Boundary refinement skipped — {e}")
            _update_report(report_id, refined_at=datetime.utcnow())
            return

        refinement_model_id = config.boundary_refinement_model_id
        refinement_model_name = config.boundary_refinement_model.name
        refinement_provider_name = config.boundary_refinement_model.provider.kind
        audio_path = episode.mp3_path
        ad_breaks_path = episode.ad_breaks_path

    _update_report(report_id, refinement_model_id=refinement_model_id)
    _log_report(report_id, f"Refining outer edges of {len(breaks)} ad break(s)...")

    refinement_report = RefinementReport(
        started_at=datetime.utcnow().isoformat(),
        provider=refinement_provider_name,
        model_name=refinement_model_name,
    )

    refined_breaks: list[AdBreak] = []
    try:
        with open(audio_path, "rb") as fh:
            audio = AudioSegment.from_file(fh, format="mp3")
        episode_duration_ms = len(audio)

        for index, ad_break in enumerate(breaks, start=1):
            break_start_ms = parse_time_to_ms(ad_break.start_time)
            break_end_ms = parse_time_to_ms(ad_break.end_time)

            def log(message: str) -> None:
                _log_report(report_id, message)

            new_start_ms = refine_or_snap_boundary(
                audio=audio,
                episode_duration_ms=episode_duration_ms,
                break_index=index,
                boundary_ms=break_start_ms,
                direction="ad_start",
                provider=provider,
                refinement_report=refinement_report,
                log=log,
            )
            new_end_ms = refine_or_snap_boundary(
                audio=audio,
                episode_duration_ms=episode_duration_ms,
                break_index=index,
                boundary_ms=break_end_ms,
                direction="ad_end",
                provider=provider,
                refinement_report=refinement_report,
                log=log,
            )

            if new_end_ms <= new_start_ms:
                _log_report(
                    report_id,
                    f"Break {index}: refined edges collapsed ({new_start_ms}→{new_end_ms}), "
                    "keeping original timestamps",
                )
                refined_breaks.append(ad_break)
                continue

            refined_breaks.append(
                AdBreak(
                    start_time=format_ms_to_time(new_start_ms),
                    end_time=format_ms_to_time(new_end_ms),
                    adverts=ad_break.adverts,
                )
            )

        refinement_report.completed_at = datetime.utcnow().isoformat()
    except Exception as e:
        refinement_report.error = str(e)
        with Session(engine) as session:
            report = session.get(ClippingReport, report_id)
            report.refinement_report = refinement_report
            report.add_exception(e)
            report.append_log(f"Boundary refinement failed: {e}")
            session.add(report)
            session.commit()
        raise

    with Session(engine) as session:
        episode = session.get(PodcastEpisode, episode_id)
        episode.ad_breaks = refined_breaks
        session.add(episode)
        session.commit()

        report = session.get(ClippingReport, report_id)
        report.refinement_report = refinement_report
        report.refined_at = datetime.utcnow()
        report.append_log(
            f"Refinement complete — refined {refinement_report.boundaries_refined}, "
            f"snapped {refinement_report.boundaries_snapped}, "
            f"kept {refinement_report.boundaries_kept}"
        )
        session.add(report)
        session.commit()

    ad_breaks_path.write_text(
        json.dumps({"breaks": [b.model_dump() for b in refined_breaks]}, indent=2)
    )


@celery_app.task(
    name="app.tasks.task_edit",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    soft_time_limit=1800,
    time_limit=1860,
)
def task_edit(self, episode_id: str, report_id: str) -> None:
    _log_report(report_id, "Editing episode...")

    with Session(engine) as session:
        episode = session.get(PodcastEpisode, episode_id)
        if not episode:
            raise ValueError(f"Episode not found: {episode_id}")
        config = session.get(AppConfig, "config")
        keep_raw = config.keep_raw_episodes if config else True
        try:
            edit_episode(episode, keep_raw=keep_raw)
        except Exception as e:
            _fail_report(report_id, e, f"Editing failed: {e}")
            raise

    _update_report(report_id, edited_at=datetime.utcnow())
    _log_report(report_id, "Clipping pipeline completed successfully")


@celery_app.task(
    name="app.tasks.task_detect_acast_ads",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    soft_time_limit=1800,
    time_limit=1860,
)
def task_detect_acast_ads(self, episode_id: str, report_id: str) -> None:
    from app.services.acast import detect_idents, idents_to_ad_breaks, pair_idents

    with Session(engine) as session:
        episode = session.get(PodcastEpisode, episode_id)
        if not episode:
            raise ValueError(f"Episode not found: {episode_id}")

        if episode.ad_breaks:
            _log_report(report_id, "Acast ads already detected, skipping")
            return

        audio_path = episode.mp3_path
        ad_breaks_path = episode.ad_breaks_path

    _log_report(report_id, "Detecting Acast idents...")

    analysis_report = AnalysisReport(
        started_at=datetime.utcnow().isoformat(),
        provider="acast",
        model_name="ident_match",
    )
    try:
        idents, audio_duration = detect_idents(audio_path)
        pairs, unpaired = pair_idents(idents, audio_duration=audio_duration)
        breaks = idents_to_ad_breaks(pairs)
        analysis_report.completed_at = datetime.utcnow().isoformat()
        analysis_report.ad_breaks_found = len(breaks)
    except Exception as e:
        analysis_report.error = str(e)
        with Session(engine) as session:
            report = session.get(ClippingReport, report_id)
            report.analysis_report = analysis_report
            report.add_exception(e)
            report.append_log(f"Acast detection failed: {e}")
            session.add(report)
            session.commit()
        raise

    with Session(engine) as session:
        episode = session.get(PodcastEpisode, episode_id)
        episode.ad_breaks = breaks
        session.add(episode)
        session.commit()

        report = session.get(ClippingReport, report_id)
        report.analysis_report = analysis_report

        log_msg = f"Acast detection: {len(idents)} idents, {len(pairs)} pairs, {unpaired} unpaired"
        report.append_log(log_msg)

        warnings: list[str] = []
        if unpaired > 0:
            warnings.append(f"WARNING: {unpaired} unpaired idents — possible missed ad break(s)")
        if len(pairs) == 0:
            warnings.append("WARNING: 0 ad breaks detected — episode passed through unchanged")
        if warnings:
            for w in warnings:
                report.append_log(w)
            analysis_report.warnings = "; ".join(warnings)
            report.analysis_report = analysis_report

        report.analysed_at = datetime.utcnow()
        session.add(report)
        session.commit()

    ad_breaks_path.write_text(json.dumps({"breaks": [b.model_dump() for b in breaks]}, indent=2))


# ── Queue orchestration ──────────────────────────────────────────────────────


def _get_transcription_queue(session: Session) -> str:
    config = session.get(AppConfig, "config")
    if (
        config
        and config.transcription_model
        and Provider(config.transcription_model.provider.kind) == Provider.WHISPER_CPP
    ):
        return "whisper"
    return "ai"


def queue_episode_for_clipping(
    session: Session,
    episode: PodcastEpisode,
    task_name_prefix: str = "Clip",
    initial_log: str = None,
) -> ClippingReport:
    report = ClippingReport(episode_id=episode.id)
    if initial_log:
        report.append_log(initial_log)
    report.append_log(f"Episode queued for clipping: {episode.title}")
    session.add(report)
    session.commit()
    session.refresh(report)

    clip_mode = episode.podcast.clip_mode

    if clip_mode == ClipMode.ACAST:
        pipeline = chain(
            task_download.si(episode.id, report.id),
            task_detect_acast_ads.si(episode.id, report.id),
            task_edit.si(episode.id, report.id),
        )
    else:
        assert clip_mode == ClipMode.AI, f"Unexpected clip_mode: {clip_mode}"
        transcription_queue = _get_transcription_queue(session)
        # NOTE: task_refine_boundaries is intentionally NOT wired into this chain
        # — boundary refinement is gated on offline eval results before being
        # enabled in production. The task and its shared helper remain available
        # for the eval pipeline (mode = "ai_refined") and for one-off invocation.
        pipeline = chain(
            task_download.si(episode.id, report.id),
            task_transcribe.si(episode.id, report.id).set(queue=transcription_queue),
            task_analyse.si(episode.id, report.id),
            task_edit.si(episode.id, report.id),
        )

    result = pipeline.apply_async()

    report.celery_task_id = result.id
    session.add(report)
    session.commit()

    return report


# ── Sync tasks ───────────────────────────────────────────────────────────────


@celery_app.task(name="app.tasks.sync_podcast_show")
def sync_podcast_show(podcast_id: str) -> str:
    from app.services.rss import sync_podcast_show_from_rss

    with Session(engine) as session:
        podcast = session.get(PodcastShow, podcast_id)
        if not podcast:
            raise ValueError(f"Podcast not found: {podcast_id}")
        logger.info("Syncing podcast show: %s", podcast.title)
        sync_podcast_show_from_rss(session, podcast)
        logger.info("Successfully synced podcast show: %s", podcast.title)
        return podcast.title


@celery_app.task(name="app.tasks.sync_podcast_episodes")
def sync_podcast_episodes(podcast_id: str, max_episodes: int = None) -> int:
    from app.services.rss import sync_podcast_episodes_from_rss

    with Session(engine) as session:
        podcast = session.get(PodcastShow, podcast_id)
        if not podcast:
            raise ValueError(f"Podcast not found: {podcast_id}")
        episodes = sync_podcast_episodes_from_rss(session, podcast, max_episodes=max_episodes)
        if not podcast.initial_sync_completed:
            podcast.initial_sync_completed = True
            session.add(podcast)
            session.commit()
            logger.info("Initial sync completed for: %s", podcast.title)
        return len(episodes)


def _episode_needs_clipping(session: Session, episode: PodcastEpisode) -> bool:
    # Already completed
    completed = session.exec(
        select(ClippingReport).where(
            ClippingReport.episode_id == episode.id,
            ClippingReport.edited_at.isnot(None),
        )
    ).first()
    if completed:
        return False

    # Never attempted — don't auto-retry
    any_report = session.exec(
        select(ClippingReport).where(ClippingReport.episode_id == episode.id)
    ).first()
    if not any_report:
        return False

    # Active non-failed report within threshold — already in progress
    now = datetime.utcnow()
    active_report = session.exec(
        select(ClippingReport).where(
            ClippingReport.episode_id == episode.id,
            ClippingReport.edited_at.is_(None),
            ClippingReport.exceptions_json == "[]",
            ClippingReport.queued_at > now - STALE_REPORT_THRESHOLD,
        )
    ).first()

    return active_report is None


@celery_app.task(name="app.tasks.sync_and_process_new_episodes")
def sync_and_process_new_episodes() -> dict[str, int]:
    from app.services.rss import parse_rss_feed, sync_podcast_show_from_rss

    results = {}
    with Session(engine) as session:
        podcasts = session.exec(
            select(PodcastShow).where(PodcastShow.initial_sync_completed == True)  # noqa: E712
        ).all()

        for podcast in podcasts:
            try:
                sync_podcast_show_from_rss(session, podcast)

                rss_data = parse_rss_feed(podcast.source_rss_url)
                new_episodes = []
                new_count = 0
                incomplete_count = 0

                for ep in rss_data.episodes:
                    if not ep.guid or not ep.audio_url:
                        continue

                    episode = session.exec(
                        select(PodcastEpisode).where(
                            PodcastEpisode.podcast_id == podcast.id,
                            PodcastEpisode.guid == ep.guid,
                        )
                    ).first()

                    if episode:
                        episode.title = ep.title
                        episode.description = ep.description
                        episode.published_at = ep.published_at
                        episode.duration = ep.duration
                        episode.source_audio_url = ep.audio_url
                        session.add(episode)
                    else:
                        episode = PodcastEpisode(
                            podcast_id=podcast.id,
                            guid=ep.guid,
                            title=ep.title,
                            description=ep.description,
                            published_at=ep.published_at,
                            duration=ep.duration,
                            source_audio_url=ep.audio_url,
                        )
                        session.add(episode)
                        new_episodes.append(episode)

                session.commit()

                if podcast.clip_mode != ClipMode.OFF:
                    for episode in new_episodes:
                        session.refresh(episode)
                        new_count += 1
                        queue_episode_for_clipping(
                            session,
                            episode,
                            task_name_prefix="Clip (Auto)",
                            initial_log=f"Discovered new episode: {episode.title}",
                        )

                    for ep in rss_data.episodes:
                        if not ep.guid or not ep.audio_url:
                            continue
                        episode = session.exec(
                            select(PodcastEpisode).where(
                                PodcastEpisode.podcast_id == podcast.id,
                                PodcastEpisode.guid == ep.guid,
                            )
                        ).first()
                        if episode and _episode_needs_clipping(session, episode):
                            incomplete_count += 1
                            logger.info("Re-clipping incomplete episode: %s", episode.title)
                            queue_episode_for_clipping(
                                session,
                                episode,
                                task_name_prefix="Clip (Retry)",
                                initial_log=f"Resuming incomplete clipping for: {episode.title}",
                            )

                results[str(podcast.id)] = new_count
                log_parts = [f"found {new_count} new episodes"]
                if incomplete_count > 0:
                    log_parts.append(f"re-queued {incomplete_count} incomplete episodes")
                logger.info("Synced %s: %s", podcast.title, ", ".join(log_parts))
            except Exception as e:
                session.rollback()
                logger.error("Failed to sync/process episodes for %s: %s", podcast.id, e)
                results[str(podcast.id)] = -1

    return results


# ── Cleanup tasks ───────────────────────────────────────────────────────────


def _delete_episode_files(episode: PodcastEpisode) -> int:
    count = 0
    for path in [episode.mp3_path, episode.raw_path, episode.srt_path, episode.ad_breaks_path]:
        if path.exists():
            path.unlink()
            count += 1
    return count


@celery_app.task(name="app.tasks.cleanup_old_episodes")
def cleanup_old_episodes() -> dict[str, int]:
    results = {}
    with Session(engine) as session:
        podcasts = session.exec(
            select(PodcastShow).where(
                (PodcastShow.cleanup_keep_days.isnot(None))
                | (PodcastShow.cleanup_keep_count.isnot(None))
            )
        ).all()

        for podcast in podcasts:
            try:
                cleaned = _cleanup_podcast_episodes(session, podcast)
                results[str(podcast.id)] = cleaned
            except Exception as e:
                logger.error("Cleanup failed for %s: %s", podcast.title, e)
                results[str(podcast.id)] = -1

    return results


def _cleanup_podcast_episodes(session: Session, podcast: PodcastShow) -> int:
    # Get all clipped, non-cleaned episodes ordered by publish date
    clipped_episodes = session.exec(
        select(PodcastEpisode)
        .join(ClippingReport, ClippingReport.episode_id == PodcastEpisode.id)
        .where(
            PodcastEpisode.podcast_id == podcast.id,
            PodcastEpisode.cleaned_at.is_(None),
            ClippingReport.edited_at.isnot(None),
        )
        .order_by(PodcastEpisode.published_at.desc())
        .distinct()
    ).all()

    now = datetime.utcnow()
    protected_ids: set[str] = set()

    # Protect the N most recent episodes
    if podcast.cleanup_keep_count is not None:
        for ep in clipped_episodes[: podcast.cleanup_keep_count]:
            protected_ids.add(ep.id)

    # Protect episodes newer than N days
    if podcast.cleanup_keep_days is not None:
        cutoff = now - timedelta(days=podcast.cleanup_keep_days)
        for ep in clipped_episodes:
            if ep.published_at and ep.published_at > cutoff:
                protected_ids.add(ep.id)

    # Skip episodes with active clipping reports
    for ep in clipped_episodes:
        if ep.id in protected_ids:
            continue
        active = session.exec(
            select(ClippingReport).where(
                ClippingReport.episode_id == ep.id,
                ClippingReport.edited_at.is_(None),
                ClippingReport.exceptions_json == "[]",
            )
        ).first()
        if active:
            protected_ids.add(ep.id)

    count = 0
    for ep in clipped_episodes:
        if ep.id in protected_ids:
            continue
        files_deleted = _delete_episode_files(ep)
        if files_deleted > 0:
            logger.info("Cleaned episode files: %s", ep.title)
        ep.cleaned_at = datetime.utcnow()
        session.add(ep)
        count += 1

    session.commit()
    if count:
        logger.info("Cleaned %d episodes for %s", count, podcast.title)
    return count
