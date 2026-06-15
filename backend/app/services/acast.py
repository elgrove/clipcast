from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import scipy.signal
from pydub import AudioSegment

from app.models import AdBreak, Advert
from app.services.editor import format_ms_to_time, parse_time_to_ms

IDENT_PATH = Path(__file__).parent.parent / "assets/acast_ident.wav"
SAMPLE_RATE = 16_000
THRESHOLD = 0.80
MIN_PAIR_GAP_S = 15
MAX_PAIR_GAP_S = 720  # 12 min

# Host-read scan: a baked-in sponsor segment can sit in the content just after
# a jingle-delineated break (trailing) or lead straight into one (leading) —
# either way it falls outside the jingle bracket. Scan a window of content on
# each side of every break for one; skip windows too short to plausibly contain
# an advert. The windows are kept fairly tight: scanning deep into content
# invites false positives (e.g. a brand-heavy show segment being mistaken for a
# host read), so a host read is only sought close to a break boundary.
HOST_READ_WINDOW_S = 120
LEADING_HOST_READ_WINDOW_S = 120
MIN_HOST_READ_WINDOW_S = 20


def acast_feed_url_heuristic(feed_url: str) -> bool:
    return urlparse(feed_url).hostname == "feeds.acast.com"


def _load_mono_16k(path: Path) -> np.ndarray:
    seg = AudioSegment.from_file(path).set_channels(1).set_frame_rate(SAMPLE_RATE)
    return np.array(seg.get_array_of_samples(), dtype=np.float32) / 32768.0


def _format_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def detect_idents(audio_path: Path) -> tuple[list[tuple[float, float]], float]:
    """Detect Acast ident matches in an audio file.

    Returns a tuple of (idents, audio_duration_seconds). The duration is measured
    from the decoded audio, not from any external metadata — RSS-supplied
    durations can be inaccurate and would lead to malformed end-of-file pairs.
    """
    if not IDENT_PATH.exists() or IDENT_PATH.stat().st_size == 0:
        raise FileNotFoundError(f"Acast ident asset not found: {IDENT_PATH}")

    episode = _load_mono_16k(audio_path)
    ident = _load_mono_16k(IDENT_PATH)

    audio_duration = len(episode) / SAMPLE_RATE
    n = len(ident)

    ident_centred = ident - ident.mean()
    ident_norm = np.linalg.norm(ident_centred)
    if ident_norm < 1e-10:
        return [], audio_duration

    # Normalised cross-correlation using fftconvolve (overlap-add, bounded memory)
    cross_corr = scipy.signal.fftconvolve(episode, ident_centred[::-1], "valid")

    ones = np.ones(n)
    local_sum = scipy.signal.fftconvolve(episode, ones, "valid")
    local_sum_sq = scipy.signal.fftconvolve(episode**2, ones, "valid")
    local_mean = local_sum / n
    local_var = np.maximum(local_sum_sq / n - local_mean**2, 0.0)
    local_std = np.sqrt(local_var)

    # NCC in [-1, 1]: divide by sqrt(N) * local_std * ident_norm
    denominator = np.sqrt(n) * local_std * ident_norm
    normalised = np.clip(cross_corr / np.where(denominator > 1e-10, denominator, 1e-10), -1.0, 1.0)

    peak_indices = np.where(normalised > THRESHOLD)[0]

    # Non-maximum suppression: keep only peaks separated by at least 3x ident
    # length. 2x lets ringing/echo partials (score ~0.9) slip through just
    # outside the window and get mispaired against far-away real idents; 3x
    # absorbs them while staying well under MIN_PAIR_GAP_S so two truly
    # back-to-back real idents are still detected separately.
    kept: list[int] = []
    if len(peak_indices) > 0:
        last = peak_indices[0]
        kept.append(last)
        for idx in peak_indices[1:]:
            if idx - last >= 3 * n:
                kept.append(idx)
                last = idx

    idents = [(int(idx) / SAMPLE_RATE, (int(idx) + n) / SAMPLE_RATE) for idx in kept]
    return idents, audio_duration


def pair_idents(
    idents: list[tuple[float, float]],
    audio_duration: float | None = None,
) -> tuple[list[tuple[tuple[float, float], tuple[float, float]]], int]:
    if not idents:
        return [], 0

    pairs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    used: set[int] = set()
    i = 0

    while i < len(idents):
        if i + 1 < len(idents):
            current = idents[i]
            nxt = idents[i + 1]
            gap = nxt[0] - current[1]
            if MIN_PAIR_GAP_S <= gap <= MAX_PAIR_GAP_S:
                pairs.append((current, nxt))
                used.add(i)
                used.add(i + 1)
                i += 2
            else:
                i += 1
        else:
            i += 1

    # Start-of-file: first ident unpaired and within MAX_PAIR_GAP_S of the start →
    # it's a closing ident; the episode began mid-ad-break with no opening ident.
    if 0 not in used and idents[0][0] < MAX_PAIR_GAP_S:
        pairs.insert(0, ((0.0, 0.0), idents[0]))
        used.add(0)

    # End-of-file: last ident unpaired and within MAX_PAIR_GAP_S of the end →
    # it's an opening ident; the episode ended mid-ad-break with no closing ident.
    # Require audio_duration >= last ident end so the synthetic pair can't produce
    # an inverted (start > end) cut window.
    last_idx = len(idents) - 1
    if (
        last_idx not in used
        and audio_duration is not None
        and idents[last_idx][1] <= audio_duration
        and (audio_duration - idents[last_idx][1]) < MAX_PAIR_GAP_S
    ):
        pairs.append((idents[last_idx], (audio_duration, audio_duration)))
        used.add(last_idx)

    return pairs, len(idents) - len(used)


def idents_to_ad_breaks(
    pairs: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[AdBreak]:
    breaks = []
    for first, second in pairs:
        breaks.append(
            AdBreak(
                start_time=_format_time(first[0]),
                end_time=_format_time(second[1]),
                adverts=None,
                source="acast_ident",
            )
        )
    return breaks


def compute_trailing_windows(
    ident_breaks: list[AdBreak],
    audio_duration_s: float,
    window_s: float = HOST_READ_WINDOW_S,
    min_window_s: float = MIN_HOST_READ_WINDOW_S,
) -> list[tuple[float, float]]:
    """Absolute (start, end) windows, in seconds, of content to scan for a
    host-read advert after each ident break. Each window runs from a break's
    end to ``window_s`` later, clamped to the audio end and to the next break's
    start so it never reaches into the following programmatic break. Windows
    shorter than ``min_window_s`` are dropped."""
    breaks = sorted(ident_breaks, key=lambda b: parse_time_to_ms(b.start_time))
    windows: list[tuple[float, float]] = []
    for i, br in enumerate(breaks):
        start = parse_time_to_ms(br.end_time) / 1000.0
        end = min(start + window_s, audio_duration_s)
        if i + 1 < len(breaks):
            end = min(end, parse_time_to_ms(breaks[i + 1].start_time) / 1000.0)
        if end - start >= min_window_s:
            windows.append((start, end))
    return windows


def compute_leading_windows(
    ident_breaks: list[AdBreak],
    window_s: float = LEADING_HOST_READ_WINDOW_S,
    min_window_s: float = MIN_HOST_READ_WINDOW_S,
) -> list[tuple[float, float]]:
    """Absolute (start, end) windows, in seconds, of content to scan for a
    host-read advert that leads INTO each ident break. Each window runs from
    ``window_s`` before a break's start up to that start, clamped to 0 and to
    the previous break's end so it never reaches back into the preceding
    programmatic break. Windows shorter than ``min_window_s`` are dropped."""
    breaks = sorted(ident_breaks, key=lambda b: parse_time_to_ms(b.start_time))
    windows: list[tuple[float, float]] = []
    for i, br in enumerate(breaks):
        end = parse_time_to_ms(br.start_time) / 1000.0
        start = max(0.0, end - window_s)
        if i > 0:
            start = max(start, parse_time_to_ms(breaks[i - 1].end_time) / 1000.0)
        if end - start >= min_window_s:
            windows.append((start, end))
    return windows


def merge_scan_windows(windows: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Merge overlapping or touching (start, end) windows into a minimal set.
    Leading and trailing windows of adjacent breaks can overlap when the breaks
    are close together; merging avoids transcribing the same content twice and
    keeps each detected advert from being reported from two windows at once."""
    ordered = sorted(windows)
    merged: list[tuple[float, float]] = []
    for start, end in ordered:
        if merged and start <= merged[-1][1]:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def offset_adverts(adverts: list[Advert], offset_ms: int) -> list[Advert]:
    """Shift each advert's window-relative timestamps forward by ``offset_ms`` to
    convert them back to absolute episode time."""

    def shift(t: str) -> str:
        return format_ms_to_time(parse_time_to_ms(t) + offset_ms)

    return [
        Advert(start_time=shift(a.start_time), end_time=shift(a.end_time), advert_for=a.advert_for)
        for a in adverts
    ]


def offset_ad_break(br: AdBreak, offset_ms: int, source: str | None = None) -> AdBreak:
    """Shift a break (and its adverts) forward by ``offset_ms`` to convert
    window-relative timestamps back to absolute episode time, optionally
    overriding the break's ``source`` tag."""

    def shift(t: str) -> str:
        return format_ms_to_time(parse_time_to_ms(t) + offset_ms)

    return AdBreak(
        start_time=shift(br.start_time),
        end_time=shift(br.end_time),
        adverts=offset_adverts(br.adverts, offset_ms) if br.adverts is not None else None,
        source=source if source is not None else br.source,
    )


def clamp_adverts(adverts: list[Advert], lo_ms: int, hi_ms: int) -> list[Advert]:
    """Clamp each advert's (absolute) timestamps to ``[lo_ms, hi_ms]``, dropping
    any advert that falls entirely outside the range. Guards against the analysis
    model returning timestamps beyond the slice it was given."""
    clamped: list[Advert] = []
    for a in adverts:
        start = max(lo_ms, parse_time_to_ms(a.start_time))
        end = min(hi_ms, parse_time_to_ms(a.end_time))
        if end <= start:
            continue
        clamped.append(
            Advert(
                start_time=format_ms_to_time(start),
                end_time=format_ms_to_time(end),
                advert_for=a.advert_for,
            )
        )
    return clamped


def clamp_ad_break(br: AdBreak, lo_ms: int, hi_ms: int) -> AdBreak | None:
    """Clamp a break's (absolute) outer boundaries and its adverts to
    ``[lo_ms, hi_ms]``. Returns None if the break falls entirely outside the
    range. Used so an over-reaching host-read result can't over-cut content."""
    start = max(lo_ms, parse_time_to_ms(br.start_time))
    end = min(hi_ms, parse_time_to_ms(br.end_time))
    if end <= start:
        return None
    return AdBreak(
        start_time=format_ms_to_time(start),
        end_time=format_ms_to_time(end),
        adverts=clamp_adverts(br.adverts, lo_ms, hi_ms) if br.adverts is not None else None,
        source=br.source,
    )
