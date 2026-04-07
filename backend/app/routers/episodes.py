import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, func, select

from app.database import get_session
from app.models import (
    BatchClipRequest,
    ClippingReport,
    ClippingReportRead,
    PodcastEpisode,
    PodcastEpisodeRead,
    PodcastShow,
)
from app.tasks import queue_episode_for_clipping

logger = logging.getLogger("clipcast")
router = APIRouter(tags=["episodes"])


def _episode_to_read(episode: PodcastEpisode, session: Session) -> PodcastEpisodeRead:
    ads = json.loads(episode.ads_json) if episode.ads_json != "[]" else []
    has_transcription = episode.transcription_json != "[]"

    latest_report = session.exec(
        select(ClippingReport)
        .where(ClippingReport.episode_id == episode.id)
        .order_by(ClippingReport.queued_at.desc())
    ).first()

    is_downloaded = bool(
        episode.cleaned_at
        or (latest_report and latest_report.downloaded_at)
        or episode.has_file
    )
    is_clipped = bool(
        episode.cleaned_at
        or (latest_report and latest_report.edited_at)
    )

    return PodcastEpisodeRead(
        id=episode.id,
        created_at=episode.created_at,
        podcast_id=episode.podcast_id,
        guid=episode.guid,
        title=episode.title,
        published_at=episode.published_at,
        description=episode.description,
        duration=episode.duration,
        source_audio_url=episode.source_audio_url,
        is_downloaded=is_downloaded,
        is_clipped=is_clipped,
        is_cleaned=episode.is_cleaned,
        has_transcription=has_transcription,
        ad_count=len(ads),
        clipping_status=latest_report.status.value if latest_report else None,
    )


@router.get(
    "/api/podcasts/{podcast_id}/episodes",
    response_model=dict,
)
def list_episodes(
    podcast_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status: str = Query("all"),
    session: Session = Depends(get_session),
):
    podcast = session.get(PodcastShow, podcast_id)
    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    query = select(PodcastEpisode).where(PodcastEpisode.podcast_id == podcast_id)

    if status == "downloaded":
        query = (
            query.join(ClippingReport, ClippingReport.episode_id == PodcastEpisode.id)
            .where(ClippingReport.downloaded_at.isnot(None))
            .distinct()
        )
    elif status == "clipped":
        query = (
            query.join(ClippingReport, ClippingReport.episode_id == PodcastEpisode.id)
            .where(ClippingReport.edited_at.isnot(None))
            .distinct()
        )

    query = query.order_by(PodcastEpisode.published_at.desc())

    total = session.exec(select(func.count()).select_from(query.subquery())).one()

    episodes = session.exec(query.offset((page - 1) * per_page).limit(per_page)).all()

    return {
        "episodes": [_episode_to_read(ep, session) for ep in episodes],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.post("/api/episodes/{episode_id}/download", status_code=202)
def queue_download(episode_id: str, session: Session = Depends(get_session)):
    episode = session.get(PodcastEpisode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    from app.services.download import download_episode as dl

    # Run download synchronously as it's relatively fast
    dl(episode)
    logger.info("Downloaded episode: %s", episode.title)
    return {"message": f"Downloaded: {episode.title}"}


@router.post("/api/episodes/{episode_id}/clip", status_code=202)
def queue_clip(episode_id: str, session: Session = Depends(get_session)):
    episode = session.get(PodcastEpisode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    report = queue_episode_for_clipping(session, episode)
    logger.info("Queued clipping for episode: %s", episode.title)
    return {"message": f"Clipping queued: {episode.title}", "report_id": report.id}


@router.post("/api/episodes/batch-clip", status_code=202)
def batch_clip(data: BatchClipRequest, session: Session = Depends(get_session)):
    reports = []
    for episode_id in data.episode_ids:
        episode = session.get(PodcastEpisode, episode_id)
        if episode:
            report = queue_episode_for_clipping(session, episode)
            reports.append(report.id)
    return {"message": f"Clipping queued for {len(reports)} episodes", "report_ids": reports}


@router.get("/api/episodes/{episode_id}/status", response_model=ClippingReportRead | None)
def episode_status(episode_id: str, session: Session = Depends(get_session)):
    report = session.exec(
        select(ClippingReport)
        .where(ClippingReport.episode_id == episode_id)
        .order_by(ClippingReport.queued_at.desc())
    ).first()
    if not report:
        return None
    return ClippingReportRead(
        id=report.id,
        episode_id=report.episode_id,
        status=report.status.value,
        queued_at=report.queued_at,
        downloaded_at=report.downloaded_at,
        transcribed_at=report.transcribed_at,
        analysed_at=report.analysed_at,
        edited_at=report.edited_at,
        logs=report.logs,
        exceptions=report.exceptions,
    )


@router.get("/podcasts/{podcast_id}/episode/{episode_id}/audio")
def episode_audio(
    podcast_id: str,
    episode_id: str,
    session: Session = Depends(get_session),
):
    episode = session.get(PodcastEpisode, episode_id)
    if not episode or episode.podcast_id != podcast_id:
        raise HTTPException(status_code=404, detail="Episode not found")
    if not episode.mp3_path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(episode.mp3_path, media_type="audio/mpeg")
