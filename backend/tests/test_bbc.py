from app.services.bbc import (
    bbc_feed_url_heuristic,
    snap_head_cut,
    snap_tail_cut,
    trim_to_breaks,
    validate_trim,
)
from app.services.editor import parse_time_to_ms
from app.services.rss import ITunesPodcast, default_clip_mode


def _itunes(**overrides) -> ITunesPodcast:
    defaults = {
        "itunes_id": "1",
        "title": "Show",
        "artist": "Artist",
        "feed_url": "https://example.com/feed.rss",
        "artwork_url": "",
        "genre": "",
    }
    defaults.update(overrides)
    return ITunesPodcast(**defaults)


# ── feed heuristic ───────────────────────────────────────────────────────────


def test_bbc_heuristic_matches_bbci_hosts():
    assert bbc_feed_url_heuristic("https://podcasts.files.bbci.co.uk/b006qykl.rss")
    assert bbc_feed_url_heuristic("https://www.bbc.co.uk/podcasts/feed.rss")
    assert bbc_feed_url_heuristic("https://bbc.co.uk/feed.rss")


def test_bbc_heuristic_rejects_non_bbc_hosts():
    assert not bbc_feed_url_heuristic("https://feeds.acast.com/public/shows/xyz")
    assert not bbc_feed_url_heuristic("https://notbbc.co.uk.evil.com/feed.rss")
    assert not bbc_feed_url_heuristic("https://example.com/bbc.co.uk/feed.rss")
    assert not bbc_feed_url_heuristic("")


def test_default_clip_mode():
    assert default_clip_mode(_itunes()) == "ai"
    assert default_clip_mode(_itunes(is_bbc=True)) == "bbc"
    assert default_clip_mode(_itunes(ads_by_acast=True, is_bbc=True)) == "acast"


# ── validation guardrails ────────────────────────────────────────────────────


def test_validate_trim_accepts_in_window_boundaries():
    assert validate_trim(14.3, 400.0, 240.0, 480.0, 3000.0) is None


def test_validate_trim_rejects_start_outside_head_window():
    assert validate_trim(300.0, 400.0, 240.0, 480.0, 3000.0) is not None
    assert validate_trim(-1.0, 400.0, 240.0, 480.0, 3000.0) is not None


def test_validate_trim_rejects_end_outside_tail_window():
    assert validate_trim(14.3, 500.0, 240.0, 480.0, 3000.0) is not None
    assert validate_trim(14.3, -1.0, 240.0, 480.0, 3000.0) is not None


def test_validate_trim_rejects_end_before_start():
    # Short episode: windows overlap and the model inverted the boundaries.
    assert validate_trim(100.0, 20.0, 240.0, 480.0, 0.0) is not None


# ── silence snapping ─────────────────────────────────────────────────────────


def test_snap_head_cut_picks_longest_silence_in_range():
    silences = [(9.0, 0.5), (14.5, 0.3), (15.0, 0.8), (17.0, 2.0)]
    assert snap_head_cut(silences, 14.4) == 15.0


def test_snap_head_cut_keeps_cut_when_no_silence_in_range():
    assert snap_head_cut([(20.0, 1.0)], 14.4) == 14.4
    assert snap_head_cut([], 14.4) == 14.4


def test_snap_tail_cut_takes_first_onset_after_cut():
    silences = [(2975.0, 0.4), (2981.4, 0.6), (2983.0, 1.0)]
    assert snap_tail_cut(silences, 2981.1) == 2981.4


def test_snap_tail_cut_keeps_cut_when_no_silence_within_range():
    assert snap_tail_cut([(2990.0, 1.0)], 2981.1) == 2981.1


# ── trim → ad-break cuts ─────────────────────────────────────────────────────


def test_trim_to_breaks_head_and_tail():
    breaks = trim_to_breaks(14.3, 2981.4, 3050.0, "BBC Sounds ident", "trailer")
    assert [b.source for b in breaks] == ["bbc_trim_head", "bbc_trim_tail"]
    head, tail = breaks
    assert parse_time_to_ms(head.start_time) == 0
    assert parse_time_to_ms(head.end_time) == 14300
    assert head.adverts[0].advert_for == "BBC Sounds ident"
    assert parse_time_to_ms(tail.start_time) == 2981400
    assert parse_time_to_ms(tail.end_time) == 3050000
    assert tail.adverts[0].advert_for == "trailer"


def test_trim_to_breaks_drops_near_zero_cuts():
    assert trim_to_breaks(0.0, 3050.0, 3050.0) == []
    assert trim_to_breaks(0.5, 3049.5, 3050.0) == []


def test_trim_to_breaks_head_only():
    breaks = trim_to_breaks(14.3, 3050.0, 3050.0)
    assert [b.source for b in breaks] == ["bbc_trim_head"]


def test_trim_to_breaks_tail_only():
    breaks = trim_to_breaks(0.0, 2981.4, 3050.0)
    assert [b.source for b in breaks] == ["bbc_trim_tail"]
    assert breaks[0].adverts[0].advert_for == "BBC outro"
