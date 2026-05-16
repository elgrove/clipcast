from pathlib import Path

import pytest
from pydub import AudioSegment

from app.models import PodcastEpisodeAdvert
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


# ── format_ms_to_time / clipped_ms_to_raw_ms ─────────────────────────────────


def test_format_ms_to_time_round_trip():
    assert format_ms_to_time(0) == "00:00:00.000"
    assert format_ms_to_time(93_500) == "00:01:33.500"
    assert format_ms_to_time(5_400_000) == "01:30:00.000"


def _ad(start_s: float, end_s: float) -> PodcastEpisodeAdvert:
    return PodcastEpisodeAdvert(
        start_time=format_ms_to_time(int(start_s * 1000)),
        end_time=format_ms_to_time(int(end_s * 1000)),
        advert_for="test",
        front_text="",
        tail_text="",
    )


def test_clipped_ms_to_raw_ms_no_cuts():
    assert clipped_ms_to_raw_ms(12345, []) == 12345


def test_clipped_ms_to_raw_ms_before_first_cut():
    # Cut 1 starts at 10s in raw; clipped 5s is before any cut
    assert clipped_ms_to_raw_ms(5_000, [_ad(10, 50)]) == 5_000


def test_clipped_ms_to_raw_ms_past_first_cut():
    # Cut [10, 50] in raw (40s removed). Clipped 15s → raw 55s.
    assert clipped_ms_to_raw_ms(15_000, [_ad(10, 50)]) == 55_000


def test_clipped_ms_to_raw_ms_past_multiple_cuts():
    # Cuts [10, 50] (40s) and [100, 130] (30s). Clipped 80s → raw 150s.
    assert clipped_ms_to_raw_ms(80_000, [_ad(10, 50), _ad(100, 130)]) == 150_000


def test_clipped_ms_to_raw_ms_skips_invalid_ads():
    # Inverted ad must not shift the conversion
    assert clipped_ms_to_raw_ms(15_000, [_ad(10, 50), _ad(200, 100)]) == 55_000


def test_clipped_ms_to_raw_ms_ads_unsorted():
    assert clipped_ms_to_raw_ms(80_000, [_ad(100, 130), _ad(10, 50)]) == 150_000


# ── apply_cuts_inplace ───────────────────────────────────────────────────────


def _silent_mp3(path: Path, duration_ms: int) -> None:
    AudioSegment.silent(duration=duration_ms).export(path, format="mp3")


def test_apply_cuts_inplace_skips_inverted_ad(tmp_path):
    """Regression for Bug 2: an inverted (start > end) ad must be skipped, not
    treated as a region to remove. Previously this caused overlapping kept
    segments and duplicated audio in the output."""
    source = tmp_path / "raw.mp3"
    target = tmp_path / "out.mp3"
    _silent_mp3(source, 10_000)  # 10s of silence

    ads = [
        _ad(2, 4),  # valid 2s cut
        PodcastEpisodeAdvert(
            start_time="00:00:09.000",
            end_time="00:00:05.000",
            advert_for="invalid",
            front_text="",
            tail_text="",
        ),
    ]
    cuts = apply_cuts_inplace(source, ads, output_path=target)

    assert cuts == 1
    out = AudioSegment.from_mp3(target)
    # Expected length: 10s - 2s = 8s. Allow small encoding wobble.
    assert len(out) == pytest.approx(8_000, abs=200)


def test_apply_cuts_inplace_overlapping_cuts(tmp_path):
    source = tmp_path / "raw.mp3"
    target = tmp_path / "out.mp3"
    _silent_mp3(source, 10_000)

    ads = [_ad(2, 5), _ad(4, 7)]  # overlap: combined removes [2, 7] = 5s
    cuts = apply_cuts_inplace(source, ads, output_path=target)

    assert cuts == 2
    out = AudioSegment.from_mp3(target)
    assert len(out) == pytest.approx(5_000, abs=200)


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


def _task_names_from_chain(report):
    """Return celery task names from the chain stored in the report's eager execution."""
    # In eager mode the pipeline runs synchronously; we inspect via the report logs
    # and the existence of the report's celery_task_id (not meaningful in eager mode).
    # Instead, patch celery chain to capture task names.
    return report


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
        "app.tasks.task_edit",
        "app.tasks.task_verify_clipped_with_ai",
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


# ── AI verification task ─────────────────────────────────────────────────────


def _make_acast_episode_with_clipped_audio(session, tmp_path):
    """Create an episode with mp3_path = a 12s "clipped" silent mp3 and
    raw_path = a 15s "original" silent mp3 alongside an acast cut at [5, 8]
    in raw coords (3s removed → 12s clipped)."""
    from app.models import ClipMode, PodcastEpisode, PodcastShow

    podcast = PodcastShow(
        title="Acast Show",
        itunes_id="acast-verify",
        source_rss_url="https://example.com/feed",
        path_directory="acast_verify",
        clip_mode=ClipMode.ACAST,
    )
    session.add(podcast)
    session.commit()
    session.refresh(podcast)

    episode = PodcastEpisode(
        podcast_id=podcast.id,
        guid="ep-acast-verify",
        title="Acast Episode",
        source_audio_url="https://example.com/ep.mp3",
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)

    episode.podcast.directory.mkdir(parents=True, exist_ok=True)
    _silent_mp3(episode.mp3_path, 12_000)  # clipped audio
    _silent_mp3(episode.raw_path, 15_000)  # original audio
    episode.ads = [_ad(5, 8)]  # acast cut
    session.add(episode)
    session.commit()
    session.refresh(episode)

    return episode


def _align_task_engine(monkeypatch):
    """tasks.py binds `engine` at module-load time, which goes stale across the
    per-test engine swap. Realign before executing tasks directly."""
    from app.database import engine as current_engine

    monkeypatch.setattr("app.tasks.engine", current_engine)


def test_verify_clipped_with_ai_no_models_configured(session, tmp_path, monkeypatch):
    """No transcription/analysis model configured → skip gracefully."""
    from app.models import AppConfig, ClippingReport
    from app.tasks import task_verify_clipped_with_ai

    _align_task_engine(monkeypatch)

    episode = _make_acast_episode_with_clipped_audio(session, tmp_path)
    report = ClippingReport(episode_id=episode.id)
    session.add(report)
    session.commit()
    session.refresh(report)

    config = session.get(AppConfig, "config")
    config.transcription_model_id = None
    config.analysis_model_id = None
    session.add(config)
    session.commit()

    task_verify_clipped_with_ai.apply(args=[episode.id, report.id]).get()

    session.refresh(report)
    assert "AI verification skipped" in report.logs


def test_verify_clipped_with_ai_finds_and_re_edits(session, tmp_path, monkeypatch):
    """AI returns an ad in clipped coords; task converts to raw, appends, and
    re-edits the audio from raw."""
    from app.models import AIModel, AppConfig, ClippingReport
    from app.services.providers import PodcastEpisodeAdverts, Transcription
    from app.tasks import task_verify_clipped_with_ai

    _align_task_engine(monkeypatch)

    episode = _make_acast_episode_with_clipped_audio(session, tmp_path)
    report = ClippingReport(episode_id=episode.id)
    session.add(report)
    session.commit()
    session.refresh(report)

    # Wire up dummy AI models so the task doesn't skip on missing config
    tx_model = AIModel(name="dummy-tx", provider="gemini", api_key="k", supports_transcription=True)
    an_model = AIModel(name="dummy-an", provider="gemini", api_key="k", supports_analysis=True)
    session.add(tx_model)
    session.add(an_model)
    session.commit()
    session.refresh(tx_model)
    session.refresh(an_model)

    config = session.get(AppConfig, "config")
    config.transcription_model_id = tx_model.id
    config.analysis_model_id = an_model.id
    session.add(config)
    session.commit()

    class _StubProvider:
        def transcribe(self, audio_path, report=None):
            return Transcription(segments=[])

        def analyse_adverts(self, transcription, report=None, custom_instructions=None):
            # Return one ad in clipped-audio coords inside the first 5-min window
            return PodcastEpisodeAdverts(
                adverts=[
                    PodcastEpisodeAdvert(
                        start_time="00:00:01.000",
                        end_time="00:00:03.000",
                        advert_for="Sponsor",
                        front_text="",
                        tail_text="",
                    )
                ]
            )

    monkeypatch.setattr("app.services.providers.get_ai_provider", lambda *_a, **_k: _StubProvider())

    task_verify_clipped_with_ai.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    # acast cut [5, 8] (raw); AI ad clipped [1, 3] → raw [1, 3] (before the acast cut)
    ads_sorted = sorted(episode.ads, key=lambda a: parse_time_to_ms(a.start_time))
    assert len(ads_sorted) == 2
    assert parse_time_to_ms(ads_sorted[0].start_time) == 1_000
    assert parse_time_to_ms(ads_sorted[0].end_time) == 3_000
    assert ads_sorted[0].advert_for == "Sponsor"
    assert parse_time_to_ms(ads_sorted[1].start_time) == 5_000
    assert parse_time_to_ms(ads_sorted[1].end_time) == 8_000

    # Re-edited audio: original 15s - 2s (AI cut) - 3s (acast cut) = 10s
    out = AudioSegment.from_mp3(episode.mp3_path)
    assert len(out) == pytest.approx(10_000, abs=300)

    assert report.edited_at is not None
