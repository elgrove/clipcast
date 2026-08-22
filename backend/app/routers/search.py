from fastapi import APIRouter, Query

from app.models import ITunesSearchResult
from app.services.rss import podcast_from_feed_url, search_itunes

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("/itunes", response_model=list[ITunesSearchResult])
def itunes_search(q: str = Query(..., min_length=1)):
    term = q.strip()
    if term.startswith(("http://", "https://")):
        feed_podcast = podcast_from_feed_url(term)
        results = [feed_podcast] if feed_podcast else []
    else:
        results = search_itunes(term)

    return [
        ITunesSearchResult(
            itunes_id=r.itunes_id,
            title=r.title,
            artist=r.artist,
            feed_url=r.feed_url,
            artwork_url=r.artwork_url,
            genre=r.genre,
            ads_by_acast=r.ads_by_acast,
            is_bbc=r.is_bbc,
        )
        for r in results
    ]
