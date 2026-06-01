import logging
from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser
import requests
from pydantic import BaseModel as PydanticBaseModel
from sqlmodel import Session, select

from app.models import PodcastEpisode, PodcastShow
from app.services.acast import acast_feed_url_heuristic

logger = logging.getLogger(__name__)

ITUNES_SEARCH_URL = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL = "https://itunes.apple.com/lookup"


class ITunesPodcast(PydanticBaseModel):
    itunes_id: str
    title: str
    artist: str
    feed_url: str
    artwork_url: str
    genre: str
    ads_by_acast: bool = False


class RSSEpisode(PydanticBaseModel):
    guid: str
    title: str
    description: str
    published_at: datetime | None
    duration: int | None
    audio_url: str
    artwork_url: str | None = None


class RSSPodcast(PydanticBaseModel):
    title: str
    description: str
    artwork_url: str | None
    episodes: list[RSSEpisode]


def search_itunes(term: str, limit: int = 25) -> list[ITunesPodcast]:
    response = requests.get(
        ITUNES_SEARCH_URL,
        params={
            "term": term,
            "media": "podcast",
            "entity": "podcast",
            "limit": limit,
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    results = []
    for item in data.get("results", []):
        feed_url = item.get("feedUrl", "")
        results.append(
            ITunesPodcast(
                itunes_id=str(item.get("collectionId", "")),
                title=item.get("collectionName", ""),
                artist=item.get("artistName", ""),
                feed_url=feed_url,
                artwork_url=item.get("artworkUrl600", item.get("artworkUrl100", "")),
                genre=item.get("primaryGenreName", ""),
                ads_by_acast=acast_feed_url_heuristic(feed_url),
            )
        )
    return results


def lookup_itunes(itunes_id: str) -> ITunesPodcast | None:
    response = requests.get(
        ITUNES_LOOKUP_URL,
        params={"id": itunes_id},
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    results = data.get("results", [])
    if not results:
        return None

    item = results[0]
    feed_url = item.get("feedUrl", "")
    return ITunesPodcast(
        itunes_id=str(item.get("collectionId", "")),
        title=item.get("collectionName", ""),
        artist=item.get("artistName", ""),
        feed_url=feed_url,
        artwork_url=item.get("artworkUrl600", item.get("artworkUrl100", "")),
        genre=item.get("primaryGenreName", ""),
        ads_by_acast=acast_feed_url_heuristic(feed_url),
    )


def _parse_duration(duration_str: str | None) -> int | None:
    if not duration_str:
        return None

    try:
        if isinstance(duration_str, int):
            return duration_str

        if ":" in duration_str:
            parts = duration_str.split(":")
            if len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + int(s)
            elif len(parts) == 2:
                m, s = parts
                return int(m) * 60 + int(s)

        return int(duration_str)
    except (ValueError, TypeError):
        return None


def _parse_date(date_str: str | None) -> datetime | None:
    if not date_str:
        return None

    try:
        return parsedate_to_datetime(date_str)
    except (ValueError, TypeError):
        return None


def _get_audio_url(entry: dict) -> str:
    for link in entry.get("links", []):
        if link.get("type", "").startswith("audio/"):
            return link.get("href", "")

    for enclosure in entry.get("enclosures", []):
        if enclosure.get("type", "").startswith("audio/"):
            return enclosure.get("href", "")

    return ""


def _get_entry_artwork_url(entry: dict) -> str | None:
    itunes_image = entry.get("itunes_image")
    if isinstance(itunes_image, str):
        return itunes_image
    if isinstance(itunes_image, dict) and "href" in itunes_image:
        return itunes_image["href"]

    image = entry.get("image")
    if isinstance(image, dict):
        if "href" in image:
            return image["href"]
        if "url" in image:
            return image["url"]

    thumbnails = entry.get("media_thumbnail")
    if isinstance(thumbnails, list) and thumbnails and "url" in thumbnails[0]:
        return thumbnails[0]["url"]

    return None


def _get_artwork_url(feed_data: dict) -> str | None:
    if hasattr(feed_data, "image") and isinstance(feed_data.image, dict):
        if "href" in feed_data.image:
            return feed_data.image["href"]
        if "url" in feed_data.image:
            return feed_data.image["url"]

    if hasattr(feed_data, "itunes_image"):
        if isinstance(feed_data.itunes_image, str):
            return feed_data.itunes_image
        elif isinstance(feed_data.itunes_image, dict) and "href" in feed_data.itunes_image:
            return feed_data.itunes_image["href"]

    return None


def parse_rss_feed(feed_url: str) -> RSSPodcast:
    response = requests.get(feed_url, timeout=30)
    response.raise_for_status()
    feed = feedparser.parse(response.text)

    episodes = []
    for entry in feed.entries:
        duration = entry.get("itunes_duration") or entry.get("duration")

        episodes.append(
            RSSEpisode(
                guid=entry.get("id", entry.get("link", "")),
                title=entry.get("title", ""),
                description=entry.get("summary", entry.get("description", "")),
                published_at=_parse_date(entry.get("published")),
                duration=_parse_duration(duration),
                audio_url=_get_audio_url(entry),
                artwork_url=_get_entry_artwork_url(entry),
            )
        )

    return RSSPodcast(
        title=feed.feed.get("title", ""),
        description=feed.feed.get("description", feed.feed.get("subtitle", "")),
        artwork_url=_get_artwork_url(feed.feed),
        episodes=episodes,
    )


def sync_podcast_from_itunes(session: Session, itunes_id: str) -> PodcastShow:
    podcast_info = lookup_itunes(itunes_id)
    if not podcast_info:
        raise ValueError(f"Podcast not found with iTunes ID: {itunes_id}")

    podcast = session.exec(select(PodcastShow).where(PodcastShow.itunes_id == itunes_id)).first()

    if podcast:
        podcast.title = podcast_info.title
        podcast.source_rss_url = podcast_info.feed_url
    else:
        from app.models import ClipMode

        podcast = PodcastShow(
            itunes_id=itunes_id,
            title=podcast_info.title,
            source_rss_url=podcast_info.feed_url,
            path_directory=PodcastShow.generate_directory_name(podcast_info.title),
            clip_mode=ClipMode.ACAST if podcast_info.ads_by_acast else ClipMode.AI,
        )

    session.add(podcast)
    session.commit()
    session.refresh(podcast)
    return podcast


def sync_podcast_show_from_rss(session: Session, podcast: PodcastShow) -> PodcastShow:
    if not podcast.source_rss_url:
        raise ValueError(f"Podcast {podcast.title} has no RSS feed URL")

    logger.info("Parsing RSS feed for %s from %s", podcast.title, podcast.source_rss_url)
    rss_data = parse_rss_feed(podcast.source_rss_url)
    logger.debug("RSS feed parsed, found %d episodes", len(rss_data.episodes))

    if rss_data.description:
        podcast.description = rss_data.description
        session.add(podcast)
        session.commit()
        session.refresh(podcast)

    if rss_data.artwork_url and not podcast.image_path.exists():
        logger.info("Downloading artwork for %s", podcast.title)
        try:
            response = requests.get(rss_data.artwork_url, timeout=30)
            response.raise_for_status()
            podcast.image_path.parent.mkdir(parents=True, exist_ok=True)
            podcast.image_path.write_bytes(response.content)
            logger.info("Artwork downloaded for %s", podcast.title)
        except Exception as e:
            logger.warning("Failed to download artwork for %s: %s", podcast.title, e)

    return podcast


def sync_podcast_episodes_from_rss(
    session: Session, podcast: PodcastShow, max_episodes: int = None
) -> list[PodcastEpisode]:
    if not podcast.source_rss_url:
        raise ValueError(f"Podcast {podcast.title} has no RSS feed URL")

    rss_data = parse_rss_feed(podcast.source_rss_url)

    episodes_to_sync = rss_data.episodes
    if max_episodes:
        episodes_to_sync = episodes_to_sync[:max_episodes]

    synced = []
    for ep in episodes_to_sync:
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
            episode.image_url = ep.artwork_url
        else:
            episode = PodcastEpisode(
                podcast_id=podcast.id,
                guid=ep.guid,
                title=ep.title,
                description=ep.description,
                published_at=ep.published_at,
                duration=ep.duration,
                source_audio_url=ep.audio_url,
                image_url=ep.artwork_url,
            )

        session.add(episode)
        synced.append(episode)

    session.commit()
    for episode in synced:
        session.refresh(episode)

    return synced
