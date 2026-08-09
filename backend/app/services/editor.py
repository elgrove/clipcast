import logging
import os
import shutil
import tempfile
from pathlib import Path

from app.models import AdBreak, PodcastEpisode
from app.services import audio

logger = logging.getLogger(__name__)


def parse_time_to_ms(time_str: str) -> int:
    # Accept SRT-style timestamps where the fractional second uses a comma
    # separator (HH:MM:SS,mmm) as well as the dotted form.
    time_str = time_str.strip().replace(",", ".")
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


def clipped_ms_to_raw_ms(clip_ms: int, removed_breaks: list[AdBreak]) -> int:
    """Convert a position in clipped audio back to the corresponding position
    in raw audio. Walks already-removed cuts (in raw time order) and shifts
    forward by each cut's duration when the converted point would lie past it."""
    sorted_breaks = sorted(removed_breaks, key=lambda b: parse_time_to_ms(b.start_time))
    raw_ms = clip_ms
    for br in sorted_breaks:
        start = parse_time_to_ms(br.start_time)
        end = parse_time_to_ms(br.end_time)
        if end <= start:
            continue
        if start <= raw_ms:
            raw_ms += end - start
        else:
            break
    return raw_ms


def apply_cuts_inplace(
    source_path: Path,
    breaks: list[AdBreak],
    output_path: Path | None = None,
    label: str = "",
) -> int:
    """Apply cuts from `source_path` and write the result to `output_path`
    (defaults to `source_path`). Returns the number of cuts applied. Breaks
    with `end <= start` are skipped."""
    target = output_path or source_path

    segments = []
    for br in breaks:
        start_ms = parse_time_to_ms(br.start_time)
        end_ms = parse_time_to_ms(br.end_time)
        if end_ms <= start_ms:
            logger.warning(
                "Skipping invalid ad break%s: start=%s end=%s",
                f" for {label}" if label else "",
                br.start_time,
                br.end_time,
            )
            continue
        segments.append((start_ms, end_ms))

    segments.sort(key=lambda x: x[0])

    total_ms = audio.duration_ms(source_path)
    ranges_to_keep = []
    current_pos = 0
    for start_ms, end_ms in segments:
        keep_end = min(start_ms, total_ms)
        if keep_end > current_pos:
            ranges_to_keep.append((current_pos, keep_end))
        current_pos = max(current_pos, end_ms)
    if current_pos < total_ms:
        ranges_to_keep.append((current_pos, total_ms))

    if not ranges_to_keep:
        return 0

    # ffmpeg cannot read and write the same file, so build alongside the target
    # and swap in — the rename keeps the write atomic for a target being served.
    temp_fd, temp_path_str = tempfile.mkstemp(suffix=".mp3", dir=target.parent)
    temp_path = Path(temp_path_str)
    os.close(temp_fd)
    try:
        audio.keep_ranges(source_path, ranges_to_keep, temp_path)
        os.replace(temp_path, target)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    return len(segments)


def edit_episode(episode: PodcastEpisode, *, keep_raw: bool = True, force: bool = False) -> None:
    if not episode.mp3_path.exists():
        raise ValueError(f"Episode {episode.title} has no downloaded MP3")

    if not episode.ad_breaks:
        return

    if episode.raw_path.exists() and not force:
        return

    logger.info("Editing episode: %s", episode.title)

    if keep_raw:
        temp_fd, temp_path_str = tempfile.mkstemp(suffix=".mp3")
        temp_path = Path(temp_path_str)
        os.close(temp_fd)

        try:
            shutil.copy(episode.mp3_path, temp_path)

            cuts = apply_cuts_inplace(episode.mp3_path, episode.ad_breaks, label=episode.title)
            if cuts == 0:
                return

            shutil.move(temp_path, episode.raw_path)
            logger.info("Edited episode, removed %d segments", cuts)

        finally:
            if temp_path.exists():
                temp_path.unlink()
    else:
        cuts = apply_cuts_inplace(episode.mp3_path, episode.ad_breaks, label=episode.title)
        if cuts == 0:
            return
        logger.info("Edited episode (no raw backup), removed %d segments", cuts)
