from feedgen.feed import FeedGenerator

from core.models import PodcastShow


def generate_podcast_feed(podcast: PodcastShow, request) -> bytes:
    fg = FeedGenerator()

    # Set feed metadata
    fg.id(podcast.itunes_id)
    fg.title(f"{podcast.title} (Ad-Free)")
    fg.description(podcast.description or f"Ad-free version of {podcast.title}")
    fg.link(href=request.build_absolute_uri(f"/podcast/{podcast.id}/"), rel="alternate")

    # Add iTunes-specific metadata
    fg.load_extension("podcast")
    fg.podcast.itunes_author(podcast.title)
    fg.podcast.itunes_category("Technology")

    # Add podcast image if available
    if podcast.image_path.exists():
        image_url = request.build_absolute_uri(f"/podcast/{podcast.id}/image/")
        fg.image(url=image_url, title=podcast.title, link=image_url)
        fg.podcast.itunes_image(image_url)

    # Get only clipped episodes (those that have been edited)
    clipped_episodes = (
        podcast.episodes.filter(clipping_reports__edited_at__isnull=False)
        .order_by("-published_at")
        .distinct()
    )

    for episode in clipped_episodes:
        if not episode.mp3_path.exists():
            continue

        fe = fg.add_entry()
        fe.id(episode.guid)
        fe.title(episode.title)
        fe.description(episode.description or "")

        if episode.published_at:
            fe.published(episode.published_at)
            fe.updated(episode.published_at)

        # Add the audio enclosure - this is the clipped MP3 file
        audio_url = request.build_absolute_uri(f"/podcast/{podcast.id}/episode/{episode.id}/audio/")
        file_size = episode.mp3_path.stat().st_size
        fe.enclosure(url=audio_url, length=str(file_size), type="audio/mpeg")

        # Add iTunes-specific episode metadata
        if episode.duration:
            fe.podcast.itunes_duration(str(episode.duration))

    return fg.rss_str(pretty=True)
