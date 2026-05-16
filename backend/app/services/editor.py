import logging
import os
import shutil
import tempfile
from pathlib import Path

from pydub import AudioSegment

from app.models import PodcastEpisode, PodcastEpisodeAdvert

logger = logging.getLogger(__name__)


def parse_time_to_ms(time_str: str) -> int:
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
        seconds = int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        seconds = int(m) * 60 + float(s)
    else:
        seconds = float(time_str)
    return int(seconds * 1000)


def format_ms_to_time(ms: int) -> str:
    seconds = max(ms, 0) / 1000
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def clipped_ms_to_raw_ms(clip_ms: int, removed_ads: list[PodcastEpisodeAdvert]) -> int:
    """Convert a position in clipped audio back to the corresponding position
    in raw audio. Walks already-removed cuts (in raw time order) and shifts
    forward by each cut's duration when the converted point would lie past it."""
    sorted_ads = sorted(removed_ads, key=lambda a: parse_time_to_ms(a.start_time))
    raw_ms = clip_ms
    for ad in sorted_ads:
        ad_start = parse_time_to_ms(ad.start_time)
        ad_end = parse_time_to_ms(ad.end_time)
        if ad_end <= ad_start:
            continue
        if ad_start <= raw_ms:
            raw_ms += ad_end - ad_start
        else:
            break
    return raw_ms


def apply_cuts_inplace(
    source_path: Path,
    ads: list[PodcastEpisodeAdvert],
    output_path: Path | None = None,
    label: str = "",
) -> int:
    """Apply ad cuts from `source_path` and write the result to `output_path`
    (defaults to `source_path`). Returns the number of cuts applied. Ads with
    `end <= start` are skipped."""
    target = output_path or source_path
    # Open via file handle: pydub treats any .raw filename suffix as raw PCM
    # (including our raw_path backup naming `.mp3.raw`), so passing a path
    # directly would fail. The handle has no recognised extension.
    with open(source_path, "rb") as fh:
        audio = AudioSegment.from_file(fh, format="mp3")

    ad_segments = []
    for ad in ads:
        start_ms = parse_time_to_ms(ad.start_time)
        end_ms = parse_time_to_ms(ad.end_time)
        if end_ms <= start_ms:
            logger.warning(
                "Skipping invalid ad segment%s: start=%s end=%s",
                f" for {label}" if label else "",
                ad.start_time,
                ad.end_time,
            )
            continue
        ad_segments.append((start_ms, end_ms))

    ad_segments.sort(key=lambda x: x[0])

    segments_to_keep = []
    current_pos = 0
    for start_ms, end_ms in ad_segments:
        if start_ms > current_pos:
            segments_to_keep.append(audio[current_pos:start_ms])
        current_pos = max(current_pos, end_ms)
    if current_pos < len(audio):
        segments_to_keep.append(audio[current_pos:])

    if not segments_to_keep:
        return 0

    result = segments_to_keep[0]
    for segment in segments_to_keep[1:]:
        result += segment

    result.export(target, format="mp3")
    return len(ad_segments)


def edit_episode(episode: PodcastEpisode, force: bool = False) -> None:
    if not episode.mp3_path.exists():
        raise ValueError(f"Episode {episode.title} has no downloaded MP3")

    if not episode.ads:
        return

    if episode.raw_path.exists() and not force:
        return

    logger.info("Editing episode: %s", episode.title)

    temp_fd, temp_path_str = tempfile.mkstemp(suffix=".mp3")
    temp_path = Path(temp_path_str)
    os.close(temp_fd)

    try:
        shutil.copy(episode.mp3_path, temp_path)

        cuts = apply_cuts_inplace(episode.mp3_path, episode.ads, label=episode.title)
        if cuts == 0:
            return

        shutil.move(temp_path, episode.raw_path)
        logger.info("Edited episode, removed %d ad segments", cuts)

    finally:
        if temp_path.exists():
            temp_path.unlink()


def re_edit_from_raw(episode: PodcastEpisode) -> int:
    """Re-apply cuts using episode.ads, starting from the preserved raw_path.
    Intended for when ads are added after the initial edit (e.g. AI verification
    of an Acast-clipped episode). Returns the number of cuts applied."""
    if not episode.raw_path.exists():
        raise ValueError(f"Raw audio not found for episode {episode.title}")
    return apply_cuts_inplace(
        episode.raw_path, episode.ads, output_path=episode.mp3_path, label=episode.title
    )
