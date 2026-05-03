import logging
from datetime import timezone

from feedgen.feed import FeedGenerator
from sqlmodel import Session, select

from app.models import ClippingReport, PodcastEpisode, PodcastShow

logger = logging.getLogger(__name__)


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
        .join(ClippingReport, ClippingReport.episode_id == PodcastEpisode.id)
        .where(
            PodcastEpisode.podcast_id == podcast.id,
            ClippingReport.edited_at.isnot(None),
            PodcastEpisode.cleaned_at.is_(None),
        )
        .order_by(PodcastEpisode.published_at.desc())
        .distinct()
    ).all()

    for episode in clipped_episodes:
        if not episode.mp3_path.exists():
            continue

        fe = fg.add_entry()
        fe.id(episode.guid)
        fe.title(episode.title)
        fe.description(episode.description or "")

        if episode.published_at:
            pub = episode.published_at.replace(tzinfo=timezone.utc) if episode.published_at.tzinfo is None else episode.published_at
            fe.published(pub)
            fe.updated(pub)

        audio_url = f"{base_url}/podcasts/{podcast.id}/episode/{episode.id}/audio"
        file_size = episode.mp3_path.stat().st_size
        fe.enclosure(url=audio_url, length=str(file_size), type="audio/mpeg")

        if episode.duration:
            fe.podcast.itunes_duration(str(episode.duration))

    return fg.rss_str(pretty=True)
