import numpy as np
import pytest
from pydub import AudioSegment

from app.models import AdBreak, Advert
from app.services.acast import (
    HOST_READ_WINDOW_S,
    IDENT_PATH,
    LEADING_HOST_READ_WINDOW_S,
    MAX_PAIR_GAP_S,
    MIN_HOST_READ_WINDOW_S,
    MIN_PAIR_GAP_S,
    OPENING_SCAN_S,
    SAMPLE_RATE,
    acast_feed_url_heuristic,
    clamp_ad_break,
    clamp_adverts,
    compute_leading_windows,
    compute_trailing_windows,
    detect_idents,
    expected_acast_breaks,
    idents_to_ad_breaks,
    merge_fallback_breaks,
    merge_scan_windows,
    offset_ad_break,
    offset_adverts,
    opening_scan_end_s,
    pair_idents,
    union_breaks,
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
    # Break ends at 90s, episode is long → full window after it.
    windows = compute_trailing_windows([_break_s(60, 90)], audio_duration_s=3600)
    assert windows == [(90.0, 90.0 + HOST_READ_WINDOW_S)]


def test_trailing_window_clamped_to_audio_end():
    windows = compute_trailing_windows([_break_s(60, 90)], audio_duration_s=200)
    assert windows == [(90.0, 200.0)]


def test_trailing_window_clamped_to_next_break():
    # First window must stop at the next break's opening, not reach into it.
    breaks = [_break_s(60, 90), _break_s(120, 150)]
    windows = compute_trailing_windows(breaks, audio_duration_s=3600)
    assert windows == [(90.0, 120.0), (150.0, 150.0 + HOST_READ_WINDOW_S)]


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


# ── compute_leading_windows ───────────────────────────────────────────────────


def test_leading_window_mid_episode():
    # Break starts at 600s, plenty of lead-in → full window before it.
    windows = compute_leading_windows([_break_s(600, 630)])
    assert windows == [(600.0 - LEADING_HOST_READ_WINDOW_S, 600.0)]


def test_leading_window_clamped_to_episode_start():
    # Break near the top of the episode → window can't precede 0.
    windows = compute_leading_windows([_break_s(60, 90)])
    assert windows == [(0.0, 60.0)]


def test_leading_window_clamped_to_previous_break():
    # The lead-in scan must not reach back into the previous programmatic break.
    breaks = [_break_s(60, 90), _break_s(150, 180)]
    windows = compute_leading_windows(breaks)
    # Break 1: lead-in [0, 60]. Break 2: 150 - 120 = 30 < prev end 90, so it
    # starts at the previous break's end, not 30.
    assert windows == [(0.0, 60.0), (90.0, 150.0)]


def test_leading_window_dropped_when_too_short():
    # Only 10s between the previous break's end and this break's start.
    breaks = [_break_s(60, 90), _break_s(100, 130)]
    windows = compute_leading_windows(breaks)
    assert windows == [(0.0, 60.0)]


def test_leading_window_empty_breaks():
    assert compute_leading_windows([]) == []


# ── merge_scan_windows ────────────────────────────────────────────────────────


def test_merge_scan_windows_disjoint_kept_separate():
    assert merge_scan_windows([(90.0, 210.0), (300.0, 420.0)]) == [
        (90.0, 210.0),
        (300.0, 420.0),
    ]


def test_merge_scan_windows_overlapping_merged():
    # A trailing window and the next break's leading window overlapping (close
    # breaks) collapse into one so the gap is scanned once, not twice.
    assert merge_scan_windows([(90.0, 210.0), (180.0, 300.0)]) == [(90.0, 300.0)]


def test_merge_scan_windows_touching_merged():
    assert merge_scan_windows([(90.0, 150.0), (150.0, 270.0)]) == [(90.0, 270.0)]


def test_merge_scan_windows_unsorted_input():
    assert merge_scan_windows([(300.0, 360.0), (90.0, 120.0)]) == [
        (90.0, 120.0),
        (300.0, 360.0),
    ]


def test_trailing_window_unsorted_breaks_sorted_first():
    breaks = [_break_s(120, 150), _break_s(60, 90)]
    windows = compute_trailing_windows(breaks, audio_duration_s=3600)
    assert windows == [(90.0, 120.0), (150.0, 150.0 + HOST_READ_WINDOW_S)]


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


# ── offset_adverts ────────────────────────────────────────────────────────────


def test_offset_adverts_shifts_each_advert():
    adverts = [
        Advert(
            start_time=format_ms_to_time(2_000),
            end_time=format_ms_to_time(8_000),
            advert_for="Shopify",
        ),
        Advert(
            start_time=format_ms_to_time(10_000),
            end_time=format_ms_to_time(15_000),
            advert_for="Squarespace",
        ),
    ]
    shifted = offset_adverts(adverts, offset_ms=60_000)

    assert [a.advert_for for a in shifted] == ["Shopify", "Squarespace"]
    assert parse_time_to_ms(shifted[0].start_time) == 62_000
    assert parse_time_to_ms(shifted[0].end_time) == 68_000
    assert parse_time_to_ms(shifted[1].start_time) == 70_000
    assert parse_time_to_ms(shifted[1].end_time) == 75_000


def test_offset_adverts_empty_list():
    assert offset_adverts([], offset_ms=1_000) == []


# ── clamp_adverts ─────────────────────────────────────────────────────────────


def test_clamp_adverts_trims_overshoot_and_drops_outside():
    adverts = [
        # Overshoots the upper bound — end gets trimmed to hi.
        Advert(
            start_time=format_ms_to_time(50_000),
            end_time=format_ms_to_time(130_000),
            advert_for="Trimmed",
        ),
        # Entirely past hi — dropped.
        Advert(
            start_time=format_ms_to_time(125_000),
            end_time=format_ms_to_time(140_000),
            advert_for="Dropped",
        ),
        # Starts before lo — start gets raised to lo.
        Advert(
            start_time=format_ms_to_time(55_000),
            end_time=format_ms_to_time(80_000),
            advert_for="Raised",
        ),
    ]
    clamped = clamp_adverts(adverts, lo_ms=60_000, hi_ms=120_000)

    assert [a.advert_for for a in clamped] == ["Trimmed", "Raised"]
    assert parse_time_to_ms(clamped[0].end_time) == 120_000
    assert parse_time_to_ms(clamped[1].start_time) == 60_000


# ── clamp_ad_break ────────────────────────────────────────────────────────────


def test_clamp_ad_break_trims_boundaries_and_adverts():
    br = AdBreak(
        start_time=format_ms_to_time(50_000),
        end_time=format_ms_to_time(130_000),
        adverts=[
            Advert(
                start_time=format_ms_to_time(55_000),
                end_time=format_ms_to_time(140_000),
                advert_for="Brand",
            )
        ],
        source="host_read",
    )
    clamped = clamp_ad_break(br, lo_ms=60_000, hi_ms=120_000)

    assert clamped is not None
    assert parse_time_to_ms(clamped.start_time) == 60_000
    assert parse_time_to_ms(clamped.end_time) == 120_000
    assert clamped.source == "host_read"
    assert parse_time_to_ms(clamped.adverts[0].start_time) == 60_000
    assert parse_time_to_ms(clamped.adverts[0].end_time) == 120_000


def test_clamp_ad_break_drops_break_entirely_outside():
    br = _break_s(200, 260, source="host_read")
    assert clamp_ad_break(br, lo_ms=0, hi_ms=120_000) is None


# ── Low-confidence fallback ──────────────────────────────────────────────────


def test_expected_acast_breaks_bands():
    assert expected_acast_breaks(0) == 0
    assert expected_acast_breaks(14 * 60) == 0
    assert expected_acast_breaks(15 * 60) == 1
    assert expected_acast_breaks(29 * 60) == 1
    assert expected_acast_breaks(30 * 60) == 2
    assert expected_acast_breaks(44 * 60) == 2
    assert expected_acast_breaks(45 * 60) == 3
    assert expected_acast_breaks(50 * 60) == 3  # today's episode: expects 3
    assert expected_acast_breaks(60 * 60) == 4  # no cap — scales for long shows


def test_expected_acast_breaks_over_30_min_is_at_least_two():
    for minutes in range(31, 120):
        assert expected_acast_breaks(minutes * 60) >= 2


def _ai_break(start_s, end_s, advert_name="Brand"):
    return AdBreak(
        start_time=format_ms_to_time(int(start_s * 1000)),
        end_time=format_ms_to_time(int(end_s * 1000)),
        adverts=[
            Advert(
                start_time=format_ms_to_time(int(start_s * 1000)),
                end_time=format_ms_to_time(int(end_s * 1000)),
                advert_for=advert_name,
            )
        ],
        source="ai_fallback",
    )


def test_merge_fallback_adds_non_overlapping_ai_break():
    """A host-read break the jingle detector missed (no overlap) is kept."""
    ident = _break_s(2880, 3010)  # 48:00-50:10, the one detected jingle break
    ai_preroll = _ai_break(30, 150)  # pre-roll with no jingle nearby
    merged = merge_fallback_breaks([ident], [ai_preroll, _ai_break(2890, 3000)])
    # pre-roll added; the AI break overlapping the ident is dropped as a dupe.
    sources = [b.source for b in merged]
    assert sources == ["ai_fallback", "acast_ident"]
    assert parse_time_to_ms(merged[0].start_time) == 30_000


def test_merge_fallback_enriches_ident_adverts_from_overlap():
    """An ident break with no itemised adverts adopts them from an overlapping
    AI break, clamped to the ident's precise boundaries."""
    ident = _break_s(2880, 3010)
    overlapping = _ai_break(2890, 3050, advert_name="Salesforce")
    merged = merge_fallback_breaks([ident], [overlapping])
    assert len(merged) == 1
    enriched = merged[0]
    assert enriched.source == "acast_ident"
    assert enriched.adverts is not None
    assert enriched.adverts[0].advert_for == "Salesforce"
    # advert end clamped to the ident's end (3010), not the AI's 3050.
    assert parse_time_to_ms(enriched.adverts[0].end_time) == 3_010_000


def test_merge_fallback_preserves_existing_ident_adverts():
    ident = AdBreak(
        start_time=format_ms_to_time(2_880_000),
        end_time=format_ms_to_time(3_010_000),
        adverts=[Advert(start_time="00:48:00.000", end_time="00:49:00.000", advert_for="Original")],
        source="acast_ident",
    )
    merged = merge_fallback_breaks([ident], [_ai_break(2890, 3000, advert_name="Other")])
    assert merged[0].adverts[0].advert_for == "Original"


def test_merge_fallback_empty_ai_returns_idents():
    ident = _break_s(2880, 3010)
    merged = merge_fallback_breaks([ident], [])
    assert len(merged) == 1
    assert merged[0].source == "acast_ident"


# ── opening_scan_end_s ───────────────────────────────────────────────────────


def test_opening_scan_end_defaults_to_window():
    """No ident breaks → just the default window, clamped to the audio."""
    assert opening_scan_end_s([], 3600) == OPENING_SCAN_S
    assert opening_scan_end_s([], 120) == 120  # clamped to a short episode


def test_opening_scan_end_extends_for_long_preroll():
    """A pre-roll opening at 0 that runs past the window extends to its end + buffer."""
    preroll = _break_s(0, OPENING_SCAN_S + 40)
    assert opening_scan_end_s([preroll], 3600) == OPENING_SCAN_S + 40 + 30


def test_opening_scan_end_ignores_midroll():
    """A first break that opens past the window is a mid-roll and never extends it."""
    midroll = _break_s(1800, 1950)
    assert opening_scan_end_s([midroll], 3600) == OPENING_SCAN_S


def test_opening_scan_end_short_preroll_keeps_window():
    """A short pre-roll leaves the default window in place (max, not min)."""
    preroll = _break_s(0, 32)
    assert opening_scan_end_s([preroll], 3600) == OPENING_SCAN_S


# ── union_breaks ─────────────────────────────────────────────────────────────


def test_union_breaks_fuses_overlapping_preroll():
    """An opening-pass break overlapping a jingle ident becomes one cut, spanning
    the union and keeping the ident source label."""
    ident = _break_s(0, 32)
    opening = AdBreak(
        start_time=format_ms_to_time(0),
        end_time=format_ms_to_time(113_000),
        adverts=[
            Advert(start_time="00:00:00.000", end_time="00:01:53.000", advert_for="Arnold Clark")
        ],
        source="opening_scan",
    )
    merged = union_breaks([ident, opening])
    assert len(merged) == 1
    assert merged[0].source == "acast_ident"
    assert parse_time_to_ms(merged[0].start_time) == 0
    assert parse_time_to_ms(merged[0].end_time) == 113_000
    assert merged[0].adverts[0].advert_for == "Arnold Clark"


def test_union_breaks_keeps_abutting_breaks_separate():
    """Breaks that merely touch (one ends exactly where the next starts) are not
    fused — only genuine overlaps are."""
    lead = _break_s(380, 500, source="host_read")
    ident = _break_s(500, 530)
    merged = union_breaks([lead, ident])
    assert len(merged) == 2
    assert [parse_time_to_ms(b.end_time) for b in merged] == [500_000, 530_000]


def test_union_breaks_leaves_disjoint_breaks_untouched():
    a = _break_s(20, 80, source="opening_scan")
    b = _break_s(500, 530)
    c = _break_s(540, 570, source="host_read")
    merged = union_breaks([c, a, b])  # unsorted input
    assert [parse_time_to_ms(x.start_time) for x in merged] == [20_000, 500_000, 540_000]


def test_union_breaks_concatenates_adverts_on_overlap():
    first = AdBreak(
        start_time=format_ms_to_time(0),
        end_time=format_ms_to_time(40_000),
        adverts=[Advert(start_time="00:00:00.000", end_time="00:00:40.000", advert_for="A")],
        source="opening_scan",
    )
    second = AdBreak(
        start_time=format_ms_to_time(30_000),
        end_time=format_ms_to_time(70_000),
        adverts=[Advert(start_time="00:00:30.000", end_time="00:01:10.000", advert_for="B")],
        source="opening_scan",
    )
    merged = union_breaks([first, second])
    assert len(merged) == 1
    assert [a.advert_for for a in merged[0].adverts] == ["A", "B"]
    assert parse_time_to_ms(merged[0].end_time) == 70_000


def test_union_breaks_empty():
    assert union_breaks([]) == []
