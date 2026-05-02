import numpy as np
import pytest
from pydub import AudioSegment

from app.models import ACAST_ADVERT_LABEL
from app.services.acast import (
    IDENT_PATH,
    MAX_PAIR_GAP_S,
    MIN_PAIR_GAP_S,
    SAMPLE_RATE,
    acast_feed_url_heuristic,
    detect_idents,
    idents_to_adverts,
    pair_idents,
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
    a = _ident(0)
    b = _ident(5)  # gap = 5 - 3 = 2 s, below MIN_PAIR_GAP_S
    pairs, unpaired = pair_idents([a, b])
    assert len(pairs) == 0
    assert unpaired == 2


def test_pair_idents_gap_too_large():
    a = _ident(0)
    b = _ident(MAX_PAIR_GAP_S + 10)
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


# ── idents_to_adverts ────────────────────────────────────────────────────────


def test_idents_to_adverts_cut_span():
    first = (10.0, 13.0)
    second = (90.0, 93.0)
    adverts = idents_to_adverts([(first, second)])
    assert len(adverts) == 1
    ad = adverts[0]
    assert ad.advert_for == ACAST_ADVERT_LABEL
    assert ad.front_text == ""
    assert ad.tail_text == ""
    # start = end_of_first = 13.0 s
    assert ad.start_time == "00:00:13.000"
    # end = end_of_second = 93.0 s
    assert ad.end_time == "00:01:33.000"


def test_idents_to_adverts_empty():
    assert idents_to_adverts([]) == []


def test_idents_to_adverts_multiple():
    pairs = [
        ((10.0, 13.0), (90.0, 93.0)),
        ((200.0, 203.0), (350.0, 353.0)),
    ]
    adverts = idents_to_adverts(pairs)
    assert len(adverts) == 2
    assert all(a.advert_for == ACAST_ADVERT_LABEL for a in adverts)


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

    hits = detect_idents(audio_path)

    assert len(hits) == len(target_offsets_s), (
        f"Expected {len(target_offsets_s)} hits, got {len(hits)}: {hits}"
    )
    for (start_s, _), target_s in zip(hits, target_offsets_s, strict=True):
        assert abs(start_s - target_s) <= 0.25, (
            f"Detected ident at {start_s:.3f}s, expected ~{target_s}s"
        )
