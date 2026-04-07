import logging

import requests

from app.models import PodcastEpisode

logger = logging.getLogger(__name__)


def download_episode(episode: PodcastEpisode) -> None:
    if not episode.source_audio_url:
        raise ValueError(f"Episode {episode.title} has no source audio URL")

    filepath = episode.mp3_path

    headers = {
        "User-Agent": "AppleCoreMedia/1.0.0.20H307 (iPhone; U; CPU OS 16_2 like Mac OS X; en_us)",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
    }

    logger.info("Downloading episode: %s", episode.title)
    response = requests.get(episode.source_audio_url, headers=headers, stream=True, timeout=60)
    response.raise_for_status()

    temp_filepath = filepath.with_suffix(".tmp")
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(temp_filepath, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        temp_filepath.rename(filepath)
        logger.info("Downloaded episode to %s", filepath)
    except Exception:
        if temp_filepath.exists():
            temp_filepath.unlink()
        raise
