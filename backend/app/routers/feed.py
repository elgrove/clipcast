from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlmodel import Session, select

from app.database import get_session
from app.models import PodcastShow
from app.services.feed import generate_podcast_feed

router = APIRouter(tags=["feed"])


@router.get("/feed/{itunes_id}")
def podcast_feed(
    itunes_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    podcast = session.exec(select(PodcastShow).where(PodcastShow.itunes_id == itunes_id)).first()
    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")

    base_url = str(request.base_url).rstrip("/")
    feed_xml = generate_podcast_feed(session, podcast, base_url)
    return Response(content=feed_xml, media_type="application/rss+xml")


@router.get("/podcasts/{podcast_id}/image")
def podcast_image(podcast_id: str, session: Session = Depends(get_session)):
    podcast = session.get(PodcastShow, podcast_id)
    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")
    if not podcast.image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(podcast.image_path, media_type="image/jpeg")
