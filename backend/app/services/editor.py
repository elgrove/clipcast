import logging
import os
import shutil
import tempfile
from pathlib import Path

from pydub import AudioSegment

from app.models import AdBreak, PodcastEpisode

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
    # Open via file handle: pydub treats any .raw filename suffix as raw PCM
    # (including our raw_path backup naming `.mp3.raw`), so passing a path
    # directly would fail. The handle has no recognised extension.
    with open(source_path, "rb") as fh:
        audio = AudioSegment.from_file(fh, format="mp3")

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

    segments_to_keep = []
    current_pos = 0
    for start_ms, end_ms in segments:
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
