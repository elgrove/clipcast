import numpy as np
import pytest
from pydub import AudioSegment

from app.models import AdBreak, Advert
from app.services.acast import (
    IDENT_PATH,
    MAX_PAIR_GAP_S,
    MIN_HOST_READ_WINDOW_S,
    MIN_PAIR_GAP_S,
    SAMPLE_RATE,
    acast_feed_url_heuristic,
    compute_trailing_windows,
    detect_idents,
    idents_to_ad_breaks,
    offset_ad_break,
    pair_idents,
)
from app.services.editor import format_ms_to_time, parse_time_to_ms


def _break_s(start_s: float, end_s: float, source: str = "acast_ident") -> AdBreak:
    return AdBreak(
        start_time=format_ms_to_time(int(start_s * 1000)),
        end_time=format_ms_to_time(int(end_s * 1000)),
        source=source,
    )


# ── URL heuristic ────────────────────────────────────────────────────────────


def test_acast_heuristic_matches_acast_feed():
    assert acast_feed_url_heuristic("https://feeds.acast.com/public/shows/my-show") is True


def test_acast_heuristic_rejects_other_hosts():
    assert acast_feed_url_heuristic("https://example.com/feed.xml") is False
    assert acast_feed_url_heuristic("https://acast-feeds.example.com/feed") is False
    assert acast_feed_url_heuristic("https://acast.com/feed") is False


def test_acast_heuristic_empty_url():
    assert acast_feed_url_heuristic("") is False


# ── pair_idents ──────────────────────────────────────────────────────────────


def _ident(start: float, duration: float = 3.0) -> tuple[float, float]:
    return (start, start + duration)


def test_pair_idents_valid_pair():
    a = _ident(0)
    b = _ident(60)  # gap = 60 - 3 = 57 s, within [15, 720]
    pairs, unpaired = pair_idents([a, b])
    assert len(pairs) == 1
    assert pairs[0] == (a, b)
    assert unpaired == 0


def test_pair_idents_gap_too_small():
    # Place idents far from t=0 so the start-of-file synthetic pair does not fire
    a = _ident(MAX_PAIR_GAP_S + 100)
    b = _ident(MAX_PAIR_GAP_S + 105)  # gap = 2 s, below MIN_PAIR_GAP_S
    pairs, unpaired = pair_idents([a, b])
    assert len(pairs) == 0
    assert unpaired == 2


def test_pair_idents_gap_too_large():
    a = _ident(MAX_PAIR_GAP_S + 100)
    b = _ident(MAX_PAIR_GAP_S + 100 + MAX_PAIR_GAP_S + 10)
    pairs, unpaired = pair_idents([a, b])
    assert len(pairs) == 0
    assert unpaired == 2


def test_pair_idents_three_idents_partial():
    a = _ident(0)
    b = _ident(60)  # a-b pairs
    c = _ident(200)  # c is alone
    pairs, unpaired = pair_idents([a, b, c])
    assert len(pairs) == 1
    assert pairs[0] == (a, b)
    assert unpaired == 1


def test_pair_idents_empty():
    pairs, unpaired = pair_idents([])
    assert pairs == []
    assert unpaired == 0


def test_pair_idents_boundary_gap():
    # Gap exactly at MIN boundary (inclusive)
    a = _ident(0)
    b = _ident(3 + MIN_PAIR_GAP_S)  # gap = MIN_PAIR_GAP_S exactly
    pairs, unpaired = pair_idents([a, b])
    assert len(pairs) == 1
    assert unpaired == 0

    # Gap exactly at MAX boundary (inclusive)
    c = _ident(0)
    d = _ident(3 + MAX_PAIR_GAP_S)  # gap = MAX_PAIR_GAP_S exactly
    pairs2, unpaired2 = pair_idents([c, d])
    assert len(pairs2) == 1
    assert unpaired2 == 0


def test_pair_idents_end_of_file_with_stale_duration():
    """If audio_duration is shorter than the last ident's end (e.g. RSS metadata
    is stale), the end-of-file synthetic pair must NOT be created — otherwise it
    would produce a cut with start > end, which previously caused the editor to
    duplicate trailing audio."""
    a = _ident(0)  # (0, 3)
    b = _ident(60)  # (60, 63) — pairs with a
    c = _ident(4540)  # (4540, 4543) — last ident
    pairs, unpaired = pair_idents([a, b, c], audio_duration=4500.0)

    # a-b pair, but c must not be paired against a smaller audio_duration
    assert len(pairs) == 1
    assert pairs[0] == (a, b)
    assert unpaired == 1


def test_pair_idents_end_of_file_with_exact_duration():
    """audio_duration equal to last_ident end is allowed (edge case)."""
    a = _ident(0)
    b = _ident(60)
    c = _ident(200)
    pairs, unpaired = pair_idents([a, b, c], audio_duration=203.0)

    # c[1] == audio_duration → synthetic pair created (gap = 0)
    assert len(pairs) == 2
    assert pairs[1] == (c, (203.0, 203.0))
    assert unpaired == 0


# ── idents_to_ad_breaks ──────────────────────────────────────────────────────


def test_idents_to_ad_breaks_cut_span():
    first = (10.0, 13.0)
    second = (90.0, 93.0)
    breaks = idents_to_ad_breaks([(first, second)])
    assert len(breaks) == 1
    br = breaks[0]
    assert br.adverts is None
    assert br.source == "acast_ident"
    # Cut spans start-of-opening-ident to end-of-closing-ident so no jingle audio survives.
    assert br.start_time == "00:00:10.000"
    assert br.end_time == "00:01:33.000"


def test_idents_to_ad_breaks_empty():
    assert idents_to_ad_breaks([]) == []


def test_idents_to_ad_breaks_multiple():
    pairs = [
        ((10.0, 13.0), (90.0, 93.0)),
        ((200.0, 203.0), (350.0, 353.0)),
    ]
    breaks = idents_to_ad_breaks(pairs)
    assert len(breaks) == 2
    assert all(b.adverts is None for b in breaks)


# ── synthetic-audio integration ───────────────────────────────────────────────


@pytest.mark.skipif(
    not IDENT_PATH.exists() or IDENT_PATH.stat().st_size == 0,
    reason="Acast ident asset not available",
)
def test_detect_idents_synthetic(tmp_path):
    """Splice real ident into white noise at known offsets and verify detection."""
    ident_seg = AudioSegment.from_file(IDENT_PATH).set_channels(1).set_frame_rate(SAMPLE_RATE)

    # 60 s of white noise
    rng = np.random.default_rng(42)
    noise_samples = rng.uniform(-0.1, 0.1, int(SAMPLE_RATE * 60)).astype(np.float32)
    noise_pcm = (noise_samples * 32768).clip(-32768, 32767).astype(np.int16)
    noise_seg = AudioSegment(
        noise_pcm.tobytes(),
        frame_rate=SAMPLE_RATE,
        sample_width=2,
        channels=1,
    )

    # Insert ident at 10 s and 40 s
    target_offsets_s = [10.0, 40.0]
    audio = noise_seg
    for offset_s in target_offsets_s:
        offset_ms = int(offset_s * 1000)
        audio = audio[:offset_ms] + ident_seg + audio[offset_ms + len(ident_seg) :]

    audio_path = tmp_path / "test_episode.wav"
    audio.export(audio_path, format="wav")

    hits, audio_duration = detect_idents(audio_path)

    assert audio_duration == pytest.approx(60.0, abs=0.05)
    assert len(hits) == len(target_offsets_s), (
        f"Expected {len(target_offsets_s)} hits, got {len(hits)}: {hits}"
    )
    for (start_s, _), target_s in zip(hits, target_offsets_s, strict=True):
        assert abs(start_s - target_s) <= 0.25, (
            f"Detected ident at {start_s:.3f}s, expected ~{target_s}s"
        )


# ── compute_trailing_windows ──────────────────────────────────────────────────


def test_trailing_window_mid_episode():
    # Break ends at 90s, episode is long → full 300s window after it.
    windows = compute_trailing_windows([_break_s(60, 90)], audio_duration_s=3600)
    assert windows == [(90.0, 390.0)]


def test_trailing_window_clamped_to_audio_end():
    windows = compute_trailing_windows([_break_s(60, 90)], audio_duration_s=200)
    assert windows == [(90.0, 200.0)]


def test_trailing_window_clamped_to_next_break():
    # First window must stop at the next break's opening, not reach into it.
    breaks = [_break_s(60, 90), _break_s(120, 150)]
    windows = compute_trailing_windows(breaks, audio_duration_s=3600)
    assert windows == [(90.0, 120.0), (150.0, 450.0)]


def test_trailing_window_dropped_when_too_short():
    # Only 10s of content after the break → below MIN_HOST_READ_WINDOW_S.
    windows = compute_trailing_windows([_break_s(60, 90)], audio_duration_s=100)
    assert windows == []


def test_trailing_window_kept_at_exact_minimum():
    windows = compute_trailing_windows(
        [_break_s(60, 90)], audio_duration_s=90 + MIN_HOST_READ_WINDOW_S
    )
    assert windows == [(90.0, 90.0 + MIN_HOST_READ_WINDOW_S)]


def test_trailing_window_empty_breaks():
    assert compute_trailing_windows([], audio_duration_s=3600) == []


def test_trailing_window_unsorted_breaks_sorted_first():
    breaks = [_break_s(120, 150), _break_s(60, 90)]
    windows = compute_trailing_windows(breaks, audio_duration_s=3600)
    assert windows == [(90.0, 120.0), (150.0, 450.0)]


# ── offset_ad_break ───────────────────────────────────────────────────────────


def test_offset_ad_break_shifts_break_and_adverts():
    window_relative = AdBreak(
        start_time=format_ms_to_time(10_000),
        end_time=format_ms_to_time(40_000),
        adverts=[
            Advert(
                start_time=format_ms_to_time(12_000),
                end_time=format_ms_to_time(38_000),
                advert_for="Brand",
            )
        ],
        source=None,
    )
    shifted = offset_ad_break(window_relative, offset_ms=90_000, source="host_read")

    assert parse_time_to_ms(shifted.start_time) == 100_000
    assert parse_time_to_ms(shifted.end_time) == 130_000
    assert shifted.source == "host_read"
    assert shifted.adverts is not None
    assert parse_time_to_ms(shifted.adverts[0].start_time) == 102_000
    assert parse_time_to_ms(shifted.adverts[0].end_time) == 128_000
    assert shifted.adverts[0].advert_for == "Brand"


def test_offset_ad_break_preserves_source_when_not_overridden():
    br = _break_s(10, 20, source="acast_ident")
    shifted = offset_ad_break(br, offset_ms=5_000)
    assert shifted.source == "acast_ident"
    assert parse_time_to_ms(shifted.start_time) == 15_000
