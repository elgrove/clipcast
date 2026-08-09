"""ffmpeg-backed audio helpers.

Everything here streams audio through an ffmpeg subprocess instead of decoding
a whole episode into the worker's address space. One hour of 44.1kHz stereo is
~635 MB of PCM, and a long-lived Celery pool child never hands that back to the
OS once glibc has grown its heap for it."""

import json
import logging
import subprocess
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True)
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace").strip().splitlines()
        raise RuntimeError(f"{args[0]} failed: {stderr[-1] if stderr else result.returncode}")
    return result


def probe(path: Path) -> tuple[int, int | None]:
    """Return (duration_ms, bitrate_bps) for the first audio stream. Bitrate is
    None when the container does not report one."""
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "format=duration:stream=bit_rate",
            "-of",
            "json",
            str(path),
        ]
    )
    parsed = json.loads(result.stdout)
    duration = parsed.get("format", {}).get("duration")
    if duration is None:
        raise RuntimeError(f"ffprobe reported no duration for {path}")
    streams = parsed.get("streams") or [{}]
    bit_rate = streams[0].get("bit_rate")
    return int(float(duration) * 1000), int(bit_rate) if bit_rate else None


def duration_ms(path: Path) -> int:
    return probe(path)[0]


def decode_mono(path: Path, sample_rate: int) -> np.ndarray:
    """Decode to a normalised float32 mono array at `sample_rate`. ffmpeg does
    the downmix and resample, so only the final array is ever in memory."""
    result = _run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            str(path),
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            str(sample_rate),
            "-",
        ]
    )
    samples = np.frombuffer(result.stdout, dtype=np.int16)
    return samples.astype(np.float32) / 32768.0


def extract_window(source: Path, start_ms: int, end_ms: int, dest: Path) -> None:
    """Copy the [start_ms, end_ms) slice into `dest` without re-encoding. Cuts
    land on frame boundaries (~26ms for mp3), which is well inside the tolerance
    of everything that consumes these windows."""
    _run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{start_ms / 1000:.3f}",
            "-to",
            f"{end_ms / 1000:.3f}",
            "-i",
            str(source),
            "-c",
            "copy",
            str(dest),
        ]
    )


def keep_ranges(source: Path, ranges: list[tuple[int, int]], dest: Path) -> None:
    """Write only `ranges` (millisecond [start, end) pairs, in order) of
    `source` to `dest`, concatenated. Re-encodes at the source bitrate."""
    if not ranges:
        raise ValueError("keep_ranges requires at least one range")

    _, bitrate = probe(source)
    splits = "".join(f"[s{i}]" for i in range(len(ranges)))
    graph = [f"[0:a]asplit={len(ranges)}{splits}"]
    for i, (start_ms, end_ms) in enumerate(ranges):
        graph.append(
            f"[s{i}]atrim=start={start_ms / 1000:.3f}:end={end_ms / 1000:.3f},asetpts=N/SR/TB[k{i}]"
        )
    keeps = "".join(f"[k{i}]" for i in range(len(ranges)))
    graph.append(f"{keeps}concat=n={len(ranges)}:v=0:a=1[out]")

    args = [
        "ffmpeg",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        str(source),
        "-filter_complex",
        ";".join(graph),
        "-map",
        "[out]",
    ]
    if bitrate:
        args += ["-b:a", str(bitrate)]
    args.append(str(dest))
    _run(args)
