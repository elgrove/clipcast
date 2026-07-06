"""Tests for deterministic silence-based boundary snapping."""

from pathlib import Path

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from app.models import AdBreak, Advert
from app.services.editor import parse_time_to_ms, snap_breaks_to_silence
from app.services.silence import Silence, detect_silences, snap_boundary

# ── snap_boundary (pure logic, no audio) ──────────────────────────────────────


def test_snap_boundary_edge_start():
    assert snap_boundary([], 2_000, "ad_start", duration_ms=60_000) == (0, "edge")


def test_snap_boundary_edge_end():
    assert snap_boundary([], 58_000, "ad_end", duration_ms=60_000) == (60_000, "edge")


def test_snap_boundary_edge_disabled():
    # snap_to_edge_ms=0 turns off episode-edge snapping
    assert snap_boundary([], 2_000, "ad_start", duration_ms=60_000, snap_to_edge_ms=0) == (
        2_000,
        "kept",
    )


def test_snap_boundary_start_snaps_to_silence_end():
    # kept content is to the left of an ad_start cut, so it snaps to the pause END
    sil = [Silence(20_000, 20_500)]
    assert snap_boundary(sil, 20_200, "ad_start", duration_ms=60_000) == (20_500, "silence")


def test_snap_boundary_end_snaps_to_silence_start():
    # kept content is to the right of an ad_end cut, so it snaps to the pause START
    sil = [Silence(20_000, 20_500)]
    assert snap_boundary(sil, 20_200, "ad_end", duration_ms=60_000) == (20_000, "silence")


def test_snap_boundary_out_of_window_kept():
    sil = [Silence(20_000, 20_500)]
    assert snap_boundary(sil, 30_000, "ad_start", duration_ms=60_000) == (30_000, "kept")


def test_snap_boundary_pad_when_no_silence():
    assert snap_boundary([], 30_000, "ad_start", duration_ms=60_000, pad_ms=150) == (29_850, "pad")
    assert snap_boundary([], 30_000, "ad_end", duration_ms=60_000, pad_ms=150) == (30_150, "pad")


def test_snap_boundary_tie_breaks_to_longer_silence():
    # Both silences' relevant edge (end, for ad_start) is 300ms from the boundary;
    # the longer pause wins.
    short = Silence(10_100, 10_300)  # end 10_300, dur 200
    long = Silence(9_200, 9_700)  # end 9_700, dur 500
    got, outcome = snap_boundary([short, long], 10_000, "ad_start", duration_ms=60_000)
    assert (got, outcome) == (9_700, "silence")


# ── detect_silences + snap_breaks_to_silence (real ffmpeg on synthesised audio) ─


def _tone(ms: int) -> AudioSegment:
    return Sine(440).to_audio_segment(duration=ms)


def _build_audio(path: Path, segments: list[tuple[str, int]]) -> None:
    """Concatenate tone/silence segments and export as mp3."""
    audio = AudioSegment.empty()
    for kind, ms in segments:
        audio += _tone(ms) if kind == "tone" else AudioSegment.silent(duration=ms)
    audio.export(path, format="mp3")


def test_detect_silences_finds_gap(tmp_path):
    # tone(2s) | silence(0.6s) | tone(2s)
    audio = tmp_path / "gap.mp3"
    _build_audio(audio, [("tone", 2_000), ("silence", 600), ("tone", 2_000)])

    silences, duration_ms = detect_silences(audio, threshold_db=-35.0, min_duration_s=0.10)

    assert duration_ms == pytest.approx(4_600, abs=200)
    assert any(s.start_ms < 2_200 and s.end_ms > 2_400 for s in silences), silences


def test_snap_breaks_to_silence_expands_into_gaps(tmp_path):
    # content(6s) | gap(0.5s) | ad(4s) | gap(0.5s) | content(6s). The ad sits
    # clear of the 5s episode-edge snap zone so the silence path is exercised.
    audio = tmp_path / "ad.mp3"
    _build_audio(
        audio,
        [("tone", 6_000), ("silence", 500), ("tone", 4_000), ("silence", 500), ("tone", 6_000)],
    )
    # AI cut a little inside the ad, leaving fragments at both seams
    breaks = [
        AdBreak(
            start_time="00:00:06.700",
            end_time="00:00:10.300",
            adverts=[Advert(start_time="00:00:06.700", end_time="00:00:10.300", advert_for="X")],
            source="acast_ident",
        )
    ]

    snapped, summary = snap_breaks_to_silence(audio, breaks)

    assert len(snapped) == 1
    new_start = parse_time_to_ms(snapped[0].start_time)
    new_end = parse_time_to_ms(snapped[0].end_time)
    # Snapped outward into the bracketing pauses (~6500 and ~10500)
    assert new_start == pytest.approx(6_500, abs=200)
    assert new_end == pytest.approx(10_500, abs=200)
    assert new_start < 6_700 and new_end > 10_300
    # Inner advert list and provenance preserved
    assert snapped[0].adverts and snapped[0].adverts[0].advert_for == "X"
    assert snapped[0].source == "acast_ident"
    assert "→pause" in summary


def test_snap_breaks_keeps_original_when_edges_collapse(tmp_path):
    # A silent file: the only silence spans the whole thing, so a mid break finds
    # no bracketing pause and (with the default pad of 0) is left untouched.
    audio = tmp_path / "silent.mp3"
    AudioSegment.silent(duration=20_000).export(audio, format="mp3")
    breaks = [AdBreak(start_time="00:00:08.000", end_time="00:00:12.000")]

    snapped, _ = snap_breaks_to_silence(audio, breaks)

    assert parse_time_to_ms(snapped[0].start_time) == 8_000
    assert parse_time_to_ms(snapped[0].end_time) == 12_000


# ── edit_episode integration (snap enabled) ───────────────────────────────────


def _make_episode(session, path_directory: str, audio_segments: list[tuple[str, int]]):
    from app.models import ClipMode, PodcastEpisode, PodcastShow

    podcast = PodcastShow(
        title=f"Silence Show {path_directory}",
        itunes_id=f"silence-show-{path_directory}",
        source_rss_url="https://example.com/feed",
        path_directory=path_directory,
        clip_mode=ClipMode.AI,
    )
    session.add(podcast)
    session.commit()
    session.refresh(podcast)

    episode = PodcastEpisode(
        podcast_id=podcast.id,
        guid=f"ep-{path_directory}",
        title="Silence Episode",
        source_audio_url="https://example.com/ep.mp3",
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)

    episode.podcast.directory.mkdir(parents=True, exist_ok=True)
    for p in (episode.mp3_path, episode.raw_path, episode.srt_path, episode.ad_breaks_path):
        if p.exists():
            p.unlink()
    _build_audio(episode.mp3_path, audio_segments)
    return episode


def _load_mp3(path: Path) -> AudioSegment:
    with open(path, "rb") as fh:
        return AudioSegment.from_file(fh, format="mp3")


def test_edit_episode_cuts_snapped_region(session, monkeypatch):
    """With snap enabled, the edit cuts the silence-snapped span, not the raw
    predicted one: [3.7,7.3] (3.6s) snaps outward to ~[3.5,7.5] (4.0s)."""
    import app.services.editor as editor_module

    monkeypatch.setattr(editor_module.settings, "silence_refinement_enabled", True)

    from app.services.editor import edit_episode

    episode = _make_episode(
        session,
        "silence_edit",
        [("tone", 6_000), ("silence", 500), ("tone", 4_000), ("silence", 500), ("tone", 6_000)],
    )
    episode.ad_breaks = [AdBreak(start_time="00:00:06.700", end_time="00:00:10.300")]
    session.add(episode)
    session.commit()

    edit_episode(episode)

    assert episode.raw_path.exists()
    assert len(_load_mp3(episode.raw_path)) == pytest.approx(17_000, abs=300)
    # Snapped cut removes ~4.0s (→13.0s); an unsnapped cut would remove 3.6s (→13.4s)
    assert len(_load_mp3(episode.mp3_path)) == pytest.approx(13_000, abs=300)
