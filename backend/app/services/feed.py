import logging
from collections import OrderedDict
from datetime import UTC
from threading import Lock
from time import monotonic

from feedgen.feed import FeedGenerator
from sqlalchemy.orm import defer
from sqlmodel import Session, select

from app.models import ClippingReport, PodcastEpisode, PodcastShow

logger = logging.getLogger(__name__)


FEED_CACHE_SECONDS = 30
_feed_cache: OrderedDict[tuple, tuple[float, bytes]] = OrderedDict()
_feed_cache_lock = Lock()


def cached_podcast_feed(session: Session, podcast: PodcastShow, base_url: str) -> bytes:
    key = (str(session.get_bind().url), podcast.id, base_url)
    with _feed_cache_lock:
        cached = _feed_cache.get(key)
        if cached and monotonic() - cached[0] < FEED_CACHE_SECONDS:
            _feed_cache.move_to_end(key)
            return cached[1]
    content = generate_podcast_feed(session, podcast, base_url)
    with _feed_cache_lock:
        _feed_cache[key] = (monotonic(), content)
        _feed_cache.move_to_end(key)
        while len(_feed_cache) > 128:
            _feed_cache.popitem(last=False)
    return content


def generate_podcast_feed(session: Session, podcast: PodcastShow, base_url: str) -> bytes:
    fg = FeedGenerator()

    fg.id(podcast.itunes_id)
    fg.title(f"{podcast.title} (Ad-Free)")
    fg.description(podcast.description or f"Ad-free version of {podcast.title}")
    fg.link(href=f"{base_url}/podcast/{podcast.id}/", rel="alternate")

    fg.load_extension("podcast")
    fg.podcast.itunes_author(podcast.title)
    fg.podcast.itunes_category("Technology")

    if podcast.image_path.exists():
        image_url = f"{base_url}/podcasts/{podcast.id}/image.jpg"
        fg.image(url=image_url, title=podcast.title, link=image_url)
        fg.podcast.itunes_image(image_url)

    clipped_episodes = session.exec(
        select(PodcastEpisode)
        .options(defer(PodcastEpisode.transcription_json), defer(PodcastEpisode.ad_breaks_json))
        .where(
            PodcastEpisode.podcast_id == podcast.id,
            select(ClippingReport.id)
            .where(
                ClippingReport.episode_id == PodcastEpisode.id,
                ClippingReport.edited_at.isnot(None),
            )
            .exists(),
            PodcastEpisode.cleaned_at.is_(None),
        )
        .order_by(PodcastEpisode.published_at.desc())
    ).all()

    for episode in clipped_episodes:
        if not episode.mp3_path.exists():
            continue

        fe = fg.add_entry()
        fe.id(episode.guid)
        fe.title(episode.title)
        fe.description(episode.description or "")

        if episode.published_at:
            pub = (
                episode.published_at.replace(tzinfo=UTC)
                if episode.published_at.tzinfo is None
                else episode.published_at
            )
            fe.published(pub)
            fe.updated(pub)

        audio_url = f"{base_url}/podcasts/{podcast.id}/episode/{episode.id}/audio"
        file_size = episode.mp3_path.stat().st_size
        fe.enclosure(url=audio_url, length=str(file_size), type="audio/mpeg")

        if episode.duration:
            fe.podcast.itunes_duration(str(episode.duration))

    return fg.rss_str(pretty=True)
