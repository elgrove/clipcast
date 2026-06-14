from pathlib import Path

import pytest
from pydub import AudioSegment

from app.models import AdBreak
from app.services.editor import (
    apply_cuts_inplace,
    clipped_ms_to_raw_ms,
    format_ms_to_time,
    parse_time_to_ms,
)


def test_parse_time_to_ms_hhmmss():
    assert parse_time_to_ms("1:30:00") == 5400000


def test_parse_time_to_ms_mmss():
    assert parse_time_to_ms("2:30") == 150000


def test_parse_time_to_ms_seconds():
    assert parse_time_to_ms("90.5") == 90500


def test_parse_time_to_ms_integer():
    assert parse_time_to_ms("60") == 60000


def test_parse_time_to_ms_hhmmss_with_ms():
    assert parse_time_to_ms("0:01:33.000") == 93000
    assert parse_time_to_ms("00:00:13.500") == 13500


def test_parse_time_to_ms_comma_decimal():
    # SRT-style timestamps use a comma before the fractional second
    assert parse_time_to_ms("00:00:40,600000") == 40600
    assert parse_time_to_ms("01:31,960") == 91960
    assert parse_time_to_ms("31,960") == 31960


# ── format_ms_to_time / clipped_ms_to_raw_ms ─────────────────────────────────


def test_format_ms_to_time_round_trip():
    assert format_ms_to_time(0) == "00:00:00.000"
    assert format_ms_to_time(93_500) == "00:01:33.500"
    assert format_ms_to_time(5_400_000) == "01:30:00.000"


def _break(start_s: float, end_s: float) -> AdBreak:
    return AdBreak(
        start_time=format_ms_to_time(int(start_s * 1000)),
        end_time=format_ms_to_time(int(end_s * 1000)),
    )


def test_clipped_ms_to_raw_ms_no_cuts():
    assert clipped_ms_to_raw_ms(12345, []) == 12345


def test_clipped_ms_to_raw_ms_before_first_cut():
    # Cut 1 starts at 10s in raw; clipped 5s is before any cut
    assert clipped_ms_to_raw_ms(5_000, [_break(10, 50)]) == 5_000


def test_clipped_ms_to_raw_ms_past_first_cut():
    # Cut [10, 50] in raw (40s removed). Clipped 15s → raw 55s.
    assert clipped_ms_to_raw_ms(15_000, [_break(10, 50)]) == 55_000


def test_clipped_ms_to_raw_ms_past_multiple_cuts():
    # Cuts [10, 50] (40s) and [100, 130] (30s). Clipped 80s → raw 150s.
    assert clipped_ms_to_raw_ms(80_000, [_break(10, 50), _break(100, 130)]) == 150_000


def test_clipped_ms_to_raw_ms_skips_invalid_regions():
    # Inverted break must not shift the conversion
    assert clipped_ms_to_raw_ms(15_000, [_break(10, 50), _break(200, 100)]) == 55_000


def test_clipped_ms_to_raw_ms_regions_unsorted():
    assert clipped_ms_to_raw_ms(80_000, [_break(100, 130), _break(10, 50)]) == 150_000


# ── apply_cuts_inplace ───────────────────────────────────────────────────────


def _silent_mp3(path: Path, duration_ms: int) -> None:
    AudioSegment.silent(duration=duration_ms).export(path, format="mp3")


def test_apply_cuts_inplace_skips_inverted_region(tmp_path):
    """Regression: an inverted (start > end) break must be skipped, not
    treated as a span to remove."""
    source = tmp_path / "raw.mp3"
    target = tmp_path / "out.mp3"
    _silent_mp3(source, 10_000)  # 10s of silence

    breaks = [
        _break(2, 4),  # valid 2s cut
        AdBreak(start_time="00:00:09.000", end_time="00:00:05.000"),
    ]
    cuts = apply_cuts_inplace(source, breaks, output_path=target)

    assert cuts == 1
    out = AudioSegment.from_mp3(target)
    # Expected length: 10s - 2s = 8s. Allow small encoding wobble.
    assert len(out) == pytest.approx(8_000, abs=200)


def test_apply_cuts_inplace_overlapping_cuts(tmp_path):
    source = tmp_path / "raw.mp3"
    target = tmp_path / "out.mp3"
    _silent_mp3(source, 10_000)

    breaks = [_break(2, 5), _break(4, 7)]  # overlap: combined removes [2, 7] = 5s
    cuts = apply_cuts_inplace(source, breaks, output_path=target)

    assert cuts == 2
    out = AudioSegment.from_mp3(target)
    assert len(out) == pytest.approx(5_000, abs=200)


# ── edit_episode (keep_raw flag) ──────────────────────────────────────────────


def _load_mp3(path: Path) -> AudioSegment:
    """Read an mp3 via file handle. Episode raw_path uses a `.mp3.raw` suffix
    which pydub would otherwise interpret as raw PCM."""
    with open(path, "rb") as fh:
        return AudioSegment.from_file(fh, format="mp3")


def _make_episode_with_cuts(session, path_directory: str, cuts_s: list[tuple[float, float]]):
    from app.models import ClipMode, PodcastEpisode, PodcastShow

    podcast = PodcastShow(
        title=f"Edit Show {path_directory}",
        itunes_id=f"edit-show-{path_directory}",
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
        title="Edit Episode",
        source_audio_url="https://example.com/ep.mp3",
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)

    episode.podcast.directory.mkdir(parents=True, exist_ok=True)
    # Clean any artefacts from prior test runs (settings.podcasts_dir is a
    # relative path so the directory persists between sessions).
    for p in (episode.mp3_path, episode.raw_path, episode.srt_path, episode.ad_breaks_path):
        if p.exists():
            p.unlink()
    _silent_mp3(episode.mp3_path, 10_000)
    episode.ad_breaks = [_break(start, end) for start, end in cuts_s]
    session.add(episode)
    session.commit()
    session.refresh(episode)
    return episode


def test_edit_episode_keeps_raw_by_default(session):
    from app.services.editor import edit_episode

    episode = _make_episode_with_cuts(session, "edit_show_keep_raw", [(2, 4)])

    edit_episode(episode)

    assert episode.raw_path.exists()
    assert len(_load_mp3(episode.raw_path)) == pytest.approx(10_000, abs=300)
    assert len(AudioSegment.from_mp3(episode.mp3_path)) == pytest.approx(8_000, abs=300)


def test_edit_episode_skips_raw_when_disabled(session):
    from app.services.editor import edit_episode

    episode = _make_episode_with_cuts(session, "edit_show_no_raw", [(2, 4)])

    edit_episode(episode, keep_raw=False)

    assert not episode.raw_path.exists()
    assert len(AudioSegment.from_mp3(episode.mp3_path)) == pytest.approx(8_000, abs=300)


# ── Pipeline chain routing ────────────────────────────────────────────────────


def _make_podcast_and_episode(session, clip_mode: str):
    from app.models import PodcastEpisode, PodcastShow

    podcast = PodcastShow(
        title="Test Show",
        itunes_id=f"test-{clip_mode}",
        source_rss_url="https://example.com/feed",
        path_directory="test_show",
        clip_mode=clip_mode,
    )
    session.add(podcast)
    session.commit()
    session.refresh(podcast)

    episode = PodcastEpisode(
        podcast_id=podcast.id,
        guid="ep-001",
        title="Episode 1",
        source_audio_url="https://example.com/ep1.mp3",
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)
    return episode


def _mock_chain(monkeypatch):
    """Return a mock chain factory that captures task names without executing."""
    captured = []

    class _FakeResult:
        id = "mock-task-id"

    class _FakeChain:
        def __init__(self, *tasks):
            for t in tasks:
                captured.append(t.task)

        def apply_async(self):
            return _FakeResult()

    monkeypatch.setattr("app.tasks.chain", lambda *tasks: _FakeChain(*tasks))
    return captured


def test_queue_acast_chain_tasks(session, monkeypatch):
    captured = _mock_chain(monkeypatch)
    episode = _make_podcast_and_episode(session, "acast")

    from app.tasks import queue_episode_for_clipping

    queue_episode_for_clipping(session, episode)

    assert captured == [
        "app.tasks.task_download",
        "app.tasks.task_detect_acast_ads",
        "app.tasks.task_scan_acast_ads",
        "app.tasks.task_edit",
    ], f"Got: {captured}"


def test_queue_ai_chain_tasks(session, monkeypatch):
    captured = _mock_chain(monkeypatch)
    episode = _make_podcast_and_episode(session, "ai")

    from app.tasks import queue_episode_for_clipping

    queue_episode_for_clipping(session, episode)

    assert captured == [
        "app.tasks.task_download",
        "app.tasks.task_transcribe",
        "app.tasks.task_analyse",
        "app.tasks.task_edit",
    ], f"Got: {captured}"
