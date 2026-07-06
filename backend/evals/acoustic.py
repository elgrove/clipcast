"""Acoustic kept-seam metric.

The boundary-distance metric scores how close a predicted cut edge is to the
transcription-aligned gold timestamp. It is blind to the *acoustic* fragment
problem: a cut that lands mid-word leaves an advert-word fragment or a jingle
flash even when its timestamp matches the gold (the gold is derived from the
same transcription). This metric measures that directly — the loudness (dBFS)
of the short slice on the KEPT side of each cut. A loud slice means an audible
fragment; a quiet slice means a clean cut. Lower is better.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pydub import AudioSegment

from .metrics import Interval

SEAM_SLICE_MS = 120
QUIET_DBFS = -40.0
_SILENCE_DBFS = -90.0  # pydub reports -inf for pure silence; clamp for averaging

_audio_cache: dict[str, AudioSegment] = {}


@dataclass
class AcousticMetrics:
    """Kept-seam loudness for a set of matched predicted cuts. Each cut has two
    seams (the kept audio just before ad_start and just after ad_end). Means are
    in dBFS; lower = quieter = cleaner. `quiet_seams` counts seams below
    `QUIET_DBFS`."""

    count: int
    start_dbfs_mean: float
    end_dbfs_mean: float
    overall_dbfs_mean: float
    quiet_seams: int
    total_seams: int
    start_dbfs: list[float] = field(default_factory=list)
    end_dbfs: list[float] = field(default_factory=list)


def _load_audio(path: Path) -> AudioSegment:
    key = str(path)
    if key not in _audio_cache:
        with open(path, "rb") as fh:
            _audio_cache[key] = AudioSegment.from_file(fh, format=path.suffix.lstrip(".") or "mp3")
    return _audio_cache[key]


def _kept_dbfs(audio: AudioSegment, boundary_s: float, side: str) -> float:
    b = int(boundary_s * 1000)
    sl = audio[max(0, b - SEAM_SLICE_MS) : b] if side == "start" else audio[b : b + SEAM_SLICE_MS]
    v = sl.dBFS
    return _SILENCE_DBFS if v == float("-inf") else v


def acoustic_from_values(start_dbfs: list[float], end_dbfs: list[float]) -> AcousticMetrics:
    """Aggregate raw per-seam dBFS values. Used both per-case and when
    concatenating across cases for a model-level rollup."""
    both = start_dbfs + end_dbfs
    if not both:
        return AcousticMetrics(0, 0.0, 0.0, 0.0, 0, 0)
    return AcousticMetrics(
        count=len(start_dbfs),
        start_dbfs_mean=sum(start_dbfs) / len(start_dbfs) if start_dbfs else 0.0,
        end_dbfs_mean=sum(end_dbfs) / len(end_dbfs) if end_dbfs else 0.0,
        overall_dbfs_mean=sum(both) / len(both),
        quiet_seams=sum(1 for v in both if v < QUIET_DBFS),
        total_seams=len(both),
        start_dbfs=list(start_dbfs),
        end_dbfs=list(end_dbfs),
    )


def acoustic_metrics(audio_path: Path | None, predicted: list[Interval]) -> AcousticMetrics | None:
    """Kept-seam loudness for each matched predicted cut. Returns None when there
    is no audio to measure or no matched cut."""
    if not audio_path or not predicted:
        return None
    audio = _load_audio(audio_path)
    starts = [_kept_dbfs(audio, iv.start, "start") for iv in predicted]
    ends = [_kept_dbfs(audio, iv.end, "end") for iv in predicted]
    return acoustic_from_values(starts, ends)
