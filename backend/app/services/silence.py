"""Deterministic silence-based boundary snapping.

Ad-break edges predicted from a transcript land a few hundred milliseconds off
the audible cut point, so a plain cut leaves a fragment of an advert word or a
flash of jingle in the output. This module nudges each cut edge into the nearest
pause so the kept side of the seam lands in silence:

  ad_start -> snap to the END of the bracketing silence (kept content is to the
              left of the cut, so the last audio before the cut sits in the pause)
  ad_end   -> snap to the START of the bracketing silence (kept content is to the
              right of the cut)

It is ffmpeg-only (one `silencedetect` pass over the file) and operates purely on
integer milliseconds so it carries no dependency on the editor or the ORM — the
AdBreak <-> ms plumbing lives in the editor. Boundaries with no pause within the
search window are left untouched (or nudged outward by a fixed pad, if one is
configured)."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger("clipcast")

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?[\d.]+)")

Direction = Literal["ad_start", "ad_end"]


@dataclass(frozen=True)
class Silence:
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


def _to_ms(seconds: str) -> int:
    return round(float(seconds) * 1000)


def detect_silences(
    audio_path: Path | str,
    *,
    threshold_db: float = -35.0,
    min_duration_s: float = 0.10,
) -> tuple[list[Silence], int]:
    """Run ffmpeg `silencedetect` over the whole file. Returns the detected
    silences and the file's total duration in ms (0 if ffmpeg did not report a
    duration). ffmpeg writes both the duration banner and the silence markers to
    stderr."""
    cmd = [
        "ffmpeg",
        "-v",
        "info",
        "-nostdin",
        "-i",
        str(audio_path),
        "-af",
        f"silencedetect=noise={threshold_db}dB:duration={min_duration_s}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    stderr = proc.stderr

    duration_ms = 0
    dm = _DURATION_RE.search(stderr)
    if dm:
        h, m, s = dm.groups()
        duration_ms = round((int(h) * 3600 + int(m) * 60 + float(s)) * 1000)

    silences: list[Silence] = []
    open_start: int | None = None
    for line in stderr.splitlines():
        sm = _SILENCE_START_RE.search(line)
        if sm:
            open_start = max(0, _to_ms(sm.group(1)))
            continue
        em = _SILENCE_END_RE.search(line)
        if em:
            end_ms = _to_ms(em.group(1))
            start_ms = open_start if open_start is not None else 0
            if end_ms > start_ms:
                silences.append(Silence(start_ms, end_ms))
            open_start = None
    # File ended mid-silence: close the trailing silence at EOF.
    if open_start is not None and duration_ms > open_start:
        silences.append(Silence(open_start, duration_ms))

    return silences, duration_ms


def snap_boundary(
    silences: list[Silence],
    boundary_ms: int,
    direction: Direction,
    *,
    duration_ms: int,
    search_window_ms: int = 1500,
    snap_to_edge_ms: int = 5000,
    pad_ms: int = 0,
) -> tuple[int, str]:
    """Snap a single cut edge. Returns (new_boundary_ms, outcome) where outcome
    is one of: ``edge`` (snapped to episode start/end), ``silence`` (snapped into
    a pause), ``pad`` (no pause; nudged outward by ``pad_ms``) or ``kept``.

    Precedence: an outer edge within ``snap_to_edge_ms`` of the episode start/end
    snaps to it first; otherwise the nearest silence within ``search_window_ms``
    of the relevant edge wins (ties broken towards the longer pause); otherwise
    the boundary is padded outward, or kept if ``pad_ms`` is 0."""
    if snap_to_edge_ms:
        if direction == "ad_start" and boundary_ms <= snap_to_edge_ms:
            return 0, "edge"
        if direction == "ad_end" and duration_ms and (duration_ms - boundary_ms) <= snap_to_edge_ms:
            return duration_ms, "edge"

    best: Silence | None = None
    best_dist = search_window_ms
    for s in silences:
        edge = s.end_ms if direction == "ad_start" else s.start_ms
        dist = abs(edge - boundary_ms)
        if dist > search_window_ms:
            continue
        if (
            best is None
            or dist < best_dist
            or (dist == best_dist and s.duration_ms > best.duration_ms)
        ):
            best, best_dist = s, dist
    if best is not None:
        return (best.end_ms if direction == "ad_start" else best.start_ms), "silence"

    if pad_ms:
        if direction == "ad_start":
            return max(0, boundary_ms - pad_ms), "pad"
        return min(duration_ms or boundary_ms + pad_ms, boundary_ms + pad_ms), "pad"

    return boundary_ms, "kept"
