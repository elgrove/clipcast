import logging
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from pydub import AudioSegment

from app.config import settings
from app.models import AdBreak, PodcastEpisode
from app.services.silence import detect_silences, snap_boundary

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


def snap_breaks_to_silence(source_path: Path, breaks: list[AdBreak]) -> tuple[list[AdBreak], str]:
    """Snap each ad-break edge into the nearest pause so cuts don't leave advert
    fragments or jingle flashes. Runs one ffmpeg silencedetect pass over
    ``source_path``; detection and window parameters come from settings. Returns
    the adjusted breaks and a one-line summary of the per-edge outcomes. A break
    whose snapped edges would collapse (end <= start) keeps its original edges."""
    silences, duration_ms = detect_silences(
        source_path,
        threshold_db=settings.silence_threshold_db,
        min_duration_s=settings.silence_min_duration,
    )

    outcomes = {"edge": 0, "silence": 0, "pad": 0, "kept": 0}
    snapped: list[AdBreak] = []
    for br in breaks:
        start_ms = parse_time_to_ms(br.start_time)
        end_ms = parse_time_to_ms(br.end_time)
        new_start, start_outcome = snap_boundary(
            silences,
            start_ms,
            "ad_start",
            duration_ms=duration_ms,
            search_window_ms=settings.silence_search_window_ms,
            snap_to_edge_ms=settings.silence_snap_to_edge_ms,
            pad_ms=settings.silence_no_match_pad_ms,
        )
        new_end, end_outcome = snap_boundary(
            silences,
            end_ms,
            "ad_end",
            duration_ms=duration_ms,
            search_window_ms=settings.silence_search_window_ms,
            snap_to_edge_ms=settings.silence_snap_to_edge_ms,
            pad_ms=settings.silence_no_match_pad_ms,
        )
        if new_end <= new_start:
            new_start, new_end, start_outcome, end_outcome = start_ms, end_ms, "kept", "kept"
        outcomes[start_outcome] += 1
        outcomes[end_outcome] += 1
        snapped.append(
            AdBreak(
                start_time=format_ms_to_time(new_start),
                end_time=format_ms_to_time(new_end),
                adverts=br.adverts,
                source=br.source,
            )
        )

    summary = (
        f"Silence-snap: {outcomes['silence']} edge(s)→pause, {outcomes['edge']}→episode-edge, "
        f"{outcomes['pad']} padded, {outcomes['kept']} kept ({len(breaks) * 2} edges total)"
    )
    return snapped, summary


def edit_episode(
    episode: PodcastEpisode,
    *,
    keep_raw: bool = True,
    force: bool = False,
    log: Callable[[str], None] | None = None,
) -> None:
    if not episode.mp3_path.exists():
        raise ValueError(f"Episode {episode.title} has no downloaded MP3")

    if not episode.ad_breaks:
        return

    if episode.raw_path.exists() and not force:
        return

    logger.info("Editing episode: %s", episode.title)

    breaks = episode.ad_breaks
    if settings.silence_refinement_enabled:
        breaks, summary = snap_breaks_to_silence(episode.mp3_path, breaks)
        logger.info("%s: %s", episode.title, summary)
        if log is not None:
            log(summary)

    if keep_raw:
        temp_fd, temp_path_str = tempfile.mkstemp(suffix=".mp3")
        temp_path = Path(temp_path_str)
        os.close(temp_fd)

        try:
            shutil.copy(episode.mp3_path, temp_path)

            cuts = apply_cuts_inplace(episode.mp3_path, breaks, label=episode.title)
            if cuts == 0:
                return

            shutil.move(temp_path, episode.raw_path)
            logger.info("Edited episode, removed %d segments", cuts)

        finally:
            if temp_path.exists():
                temp_path.unlink()
    else:
        cuts = apply_cuts_inplace(episode.mp3_path, breaks, label=episode.title)
        if cuts == 0:
            return
        logger.info("Edited episode (no raw backup), removed %d segments", cuts)
