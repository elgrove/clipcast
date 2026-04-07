import logging
import shutil

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, func, select

from app.database import get_session
from app.models import (
    PodcastEpisode,
    PodcastShow,
    PodcastShowCreate,
    PodcastShowRead,
    PodcastShowUpdate,
)
from app.services.rss import lookup_itunes
from app.tasks import sync_and_process_new_episodes, sync_podcast_episodes, sync_podcast_show

logger = logging.getLogger("clipcast")
router = APIRouter(prefix="/api/podcasts", tags=["podcasts"])


def _podcast_to_read(podcast: PodcastShow, episode_count: int = 0) -> PodcastShowRead:
    image_url = f"/podcasts/{podcast.id}/image" if podcast.image_path.exists() else None
    return PodcastShowRead(
        id=podcast.id,
        created_at=podcast.created_at,
        title=podcast.title,
        description=podcast.description,
        itunes_id=podcast.itunes_id,
        source_rss_url=podcast.source_rss_url,
        has_ads=podcast.has_ads,
        initial_sync_completed=podcast.initial_sync_completed,
        episode_count=episode_count,
        image_url=image_url,
        cleanup_keep_days=podcast.cleanup_keep_days,
        cleanup_keep_count=podcast.cleanup_keep_count,
    )


@router.get("", response_model=list[PodcastShowRead])
def list_podcasts(session: Session = Depends(get_session)):
    results = session.exec(
        select(PodcastShow, func.count(PodcastEpisode.id))
        .outerjoin(PodcastEpisode, PodcastEpisode.podcast_id == PodcastShow.id)
        .group_by(PodcastShow.id)
        .order_by(PodcastShow.created_at.desc())
    ).all()
    return [_podcast_to_read(podcast, count) for podcast, count in results]


@router.post("", response_model=PodcastShowRead, status_code=201)
def add_podcast(data: PodcastShowCreate, session: Session = Depends(get_session)):
    existing = session.exec(
        select(PodcastShow).where(PodcastShow.itunes_id == data.itunes_id)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Podcast already in library")

    podcast_info = lookup_itunes(data.itunes_id)
    if not podcast_info:
        raise HTTPException(status_code=404, detail="Podcast not found on iTunes")

    podcast = PodcastShow(
        itunes_id=data.itunes_id,
        title=podcast_info.title,
        source_rss_url=podcast_info.feed_url,
        path_directory=PodcastShow.generate_directory_name(podcast_info.title),
        has_ads=data.has_ads,
    )
    podcast.directory.mkdir(parents=True, exist_ok=True)

    # Download artwork before DB write to avoid holding a lock
    if podcast_info.artwork_url:
        try:
            resp = requests.get(podcast_info.artwork_url, timeout=10)
            resp.raise_for_status()
            podcast.image_path.write_bytes(resp.content)
        except Exception as e:
            logger.warning("Failed to download artwork: %s", e)

    session.add(podcast)
    session.commit()
    session.refresh(podcast)

    sync_podcast_show.delay(podcast.id)
    sync_podcast_episodes.delay(podcast.id)

    logger.info("Added podcast: %s", podcast.title)
    return _podcast_to_read(podcast)


@router.get("/{podcast_id}", response_model=PodcastShowRead)
def get_podcast(podcast_id: str, session: Session = Depends(get_session)):
    podcast = session.get(PodcastShow, podcast_id)
    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")
    count = session.exec(
        select(func.count(PodcastEpisode.id)).where(PodcastEpisode.podcast_id == podcast_id)
    ).one()
    return _podcast_to_read(podcast, count)


@router.patch("/{podcast_id}", response_model=PodcastShowRead)
def update_podcast(
    podcast_id: str,
    data: PodcastShowUpdate,
    session: Session = Depends(get_session),
):
    podcast = session.get(PodcastShow, podcast_id)
    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")
    if data.has_ads is not None:
        podcast.has_ads = data.has_ads
    if data.cleanup_keep_days is not None:
        podcast.cleanup_keep_days = data.cleanup_keep_days if data.cleanup_keep_days > 0 else None
    if data.cleanup_keep_count is not None:
        podcast.cleanup_keep_count = data.cleanup_keep_count if data.cleanup_keep_count > 0 else None
    session.add(podcast)
    session.commit()
    session.refresh(podcast)
    return get_podcast(podcast_id, session)


@router.delete("/{podcast_id}", status_code=204)
def delete_podcast(
    podcast_id: str,
    delete_files: bool = Query(False),
    session: Session = Depends(get_session),
):
    podcast = session.get(PodcastShow, podcast_id)
    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    directory = podcast.directory
    title = podcast.title

    session.delete(podcast)
    session.commit()
    logger.info("Deleted podcast: %s", title)

    if delete_files and directory.exists():
        shutil.rmtree(directory)
        logger.info("Deleted files for podcast: %s", title)


@router.post("/{podcast_id}/sync", status_code=202)
def sync_podcast(podcast_id: str, session: Session = Depends(get_session)):
    podcast = session.get(PodcastShow, podcast_id)
    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")
    sync_podcast_show.delay(podcast.id)
    sync_podcast_episodes.delay(podcast.id)
    return {"message": f"Sync queued for {podcast.title}"}


@router.post("/sync-all", status_code=202)
def sync_all_podcasts():
    sync_and_process_new_episodes.delay()
    return {"message": "Sync queued for all podcasts"}
