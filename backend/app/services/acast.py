from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import scipy.signal
from pydub import AudioSegment

from app.models import ACAST_ADVERT_LABEL, PodcastEpisodeAdvert

IDENT_PATH = Path(__file__).parent.parent / "assets/acast_ident.wav"
SAMPLE_RATE = 16_000
THRESHOLD = 0.80
MIN_PAIR_GAP_S = 15
MAX_PAIR_GAP_S = 720  # 12 min


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

    # Non-maximum suppression: keep only peaks separated by at least 2x ident length
    # (1x would allow a spurious secondary peak immediately after a real ident ends)
    kept: list[int] = []
    if len(peak_indices) > 0:
        last = peak_indices[0]
        kept.append(last)
        for idx in peak_indices[1:]:
            if idx - last >= 2 * n:
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


def idents_to_adverts(
    pairs: list[tuple[tuple[float, float], tuple[float, float]]],
) -> list[PodcastEpisodeAdvert]:
    adverts = []
    for first, second in pairs:
        # For start-of-file pairs the sentinel first=(0,0) means no opening ident exists.
        # Cut to the start of the closing ident so it is kept as the transition sound.
        # For all other pairs, cut to the end of the closing ident (opening ident is kept).
        end_time = second[0] if first == (0.0, 0.0) else second[1]
        adverts.append(
            PodcastEpisodeAdvert(
                start_time=_format_time(first[1]),
                end_time=_format_time(end_time),
                advert_for=ACAST_ADVERT_LABEL,
                front_text="",
                tail_text="",
            )
        )
    return adverts
