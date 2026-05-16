import logging
import os
import shutil
import tempfile
from pathlib import Path

from pydub import AudioSegment

from app.models import CutRegion, PodcastEpisode

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


def clipped_ms_to_raw_ms(clip_ms: int, removed_regions: list[CutRegion]) -> int:
    """Convert a position in clipped audio back to the corresponding position
    in raw audio. Walks already-removed cuts (in raw time order) and shifts
    forward by each cut's duration when the converted point would lie past it."""
    sorted_regions = sorted(removed_regions, key=lambda r: parse_time_to_ms(r.start_time))
    raw_ms = clip_ms
    for region in sorted_regions:
        start = parse_time_to_ms(region.start_time)
        end = parse_time_to_ms(region.end_time)
        if end <= start:
            continue
        if start <= raw_ms:
            raw_ms += end - start
        else:
            break
    return raw_ms


def apply_cuts_inplace(
    source_path: Path,
    regions: list[CutRegion],
    output_path: Path | None = None,
    label: str = "",
) -> int:
    """Apply cuts from `source_path` and write the result to `output_path`
    (defaults to `source_path`). Returns the number of cuts applied. Regions
    with `end <= start` are skipped."""
    target = output_path or source_path
    # Open via file handle: pydub treats any .raw filename suffix as raw PCM
    # (including our raw_path backup naming `.mp3.raw`), so passing a path
    # directly would fail. The handle has no recognised extension.
    with open(source_path, "rb") as fh:
        audio = AudioSegment.from_file(fh, format="mp3")

    segments = []
    for region in regions:
        start_ms = parse_time_to_ms(region.start_time)
        end_ms = parse_time_to_ms(region.end_time)
        if end_ms <= start_ms:
            logger.warning(
                "Skipping invalid cut region%s: start=%s end=%s",
                f" for {label}" if label else "",
                region.start_time,
                region.end_time,
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


def edit_episode(episode: PodcastEpisode, force: bool = False) -> None:
    if not episode.mp3_path.exists():
        raise ValueError(f"Episode {episode.title} has no downloaded MP3")

    if not episode.cut_regions:
        return

    if episode.raw_path.exists() and not force:
        return

    logger.info("Editing episode: %s", episode.title)

    temp_fd, temp_path_str = tempfile.mkstemp(suffix=".mp3")
    temp_path = Path(temp_path_str)
    os.close(temp_fd)

    try:
        shutil.copy(episode.mp3_path, temp_path)

        cuts = apply_cuts_inplace(episode.mp3_path, episode.cut_regions, label=episode.title)
        if cuts == 0:
            return

        shutil.move(temp_path, episode.raw_path)
        logger.info("Edited episode, removed %d segments", cuts)

    finally:
        if temp_path.exists():
            temp_path.unlink()


def re_edit_from_raw(episode: PodcastEpisode) -> int:
    """Re-apply cuts using episode.cut_regions, starting from the preserved raw_path.
    Intended for when regions change after the initial edit (e.g. AI verification
    of an Acast-clipped episode adds host-read ads). Returns the cut count."""
    if not episode.raw_path.exists():
        raise ValueError(f"Raw audio not found for episode {episode.title}")
    return apply_cuts_inplace(
        episode.raw_path, episode.cut_regions, output_path=episode.mp3_path, label=episode.title
    )
