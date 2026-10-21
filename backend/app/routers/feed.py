import hashlib

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlmodel import Session, select

from app.config import settings
from app.database import get_session
from app.models import PodcastShow
from app.services.feed import cached_podcast_feed

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

    base_url = settings.external_url or str(request.base_url).rstrip("/")
    feed_xml = cached_podcast_feed(session, podcast, base_url)
    etag = '"' + hashlib.sha256(feed_xml).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=30"}
    supplied = request.headers.get("if-none-match", "")
    if any(tag.strip().removeprefix("W/") in (etag, "*") for tag in supplied.split(",")):
        return Response(status_code=304, headers=headers)
    return Response(content=feed_xml, media_type="application/rss+xml", headers=headers)


@router.get("/podcasts/{podcast_id}/image.jpg")
@router.get("/podcasts/{podcast_id}/image")
def podcast_image(podcast_id: str, session: Session = Depends(get_session)):
    podcast = session.get(PodcastShow, podcast_id)
    if not podcast:
        raise HTTPException(status_code=404, detail="Podcast not found")
    if not podcast.image_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(podcast.image_path, media_type="image/jpeg")
