"""Tests for task_scan_acast_host_reads — the post-break host-read advert scan
that runs after Acast ident detection."""

from pathlib import Path

from pydub import AudioSegment

from app.models import (
    AdBreak,
    AIModel,
    AIProvider,
    AppConfig,
    ClipMode,
    ClippingReport,
    PodcastEpisode,
    PodcastShow,
    TranscriptionSegment,
)
from app.services.editor import format_ms_to_time, parse_time_to_ms
from app.services.providers import Transcription


def _silent_mp3(path: Path, duration_ms: int) -> None:
    AudioSegment.silent(duration=duration_ms).export(path, format="mp3")


def _align_task_engine(monkeypatch):
    from app.database import engine as current_engine

    monkeypatch.setattr("app.tasks.engine", current_engine)


def _make_acast_episode(
    session, *, duration_ms: int, breaks: list[tuple[int, int]]
) -> PodcastEpisode:
    """Acast-mode episode with a silent mp3 and ident-detected breaks already set."""
    podcast = PodcastShow(
        title="Acast Show",
        itunes_id=f"acast-show-{duration_ms}-{len(breaks)}",
        source_rss_url="https://feeds.acast.com/public/shows/x",
        path_directory=f"acast_show_{duration_ms}_{len(breaks)}",
        clip_mode=ClipMode.ACAST,
    )
    session.add(podcast)
    session.commit()
    session.refresh(podcast)

    episode = PodcastEpisode(
        podcast_id=podcast.id,
        guid=f"acast-ep-{duration_ms}-{len(breaks)}",
        title="Acast Episode",
        source_audio_url="https://example.com/ep.mp3",
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)

    episode.podcast.directory.mkdir(parents=True, exist_ok=True)
    for p in (episode.mp3_path, episode.raw_path, episode.srt_path, episode.ad_breaks_path):
        if p.exists():
            p.unlink()
    _silent_mp3(episode.mp3_path, duration_ms)

    episode.ad_breaks = [
        AdBreak(
            start_time=format_ms_to_time(s),
            end_time=format_ms_to_time(e),
            source="acast_ident",
        )
        for s, e in breaks
    ]
    session.add(episode)
    session.commit()
    session.refresh(episode)
    return episode


def _configure_models(session, *, enabled: bool) -> None:
    provider_row = AIProvider(kind="gemini", name="Gemini", api_key="k")
    session.add(provider_row)
    session.commit()
    session.refresh(provider_row)

    transcribe_model = AIModel(
        provider_id=provider_row.id, name="gemini-transcribe", supports_transcription=True
    )
    analyse_model = AIModel(
        provider_id=provider_row.id, name="gemini-analyse", supports_analysis=True
    )
    session.add(transcribe_model)
    session.add(analyse_model)
    session.commit()
    session.refresh(transcribe_model)
    session.refresh(analyse_model)

    config = session.get(AppConfig, "config")
    config.transcription_model_id = transcribe_model.id
    config.analysis_model_id = analyse_model.id
    config.scan_acast_host_reads = enabled
    session.add(config)
    session.commit()


class _StubProvider:
    """Returns a fixed transcription and a fixed (window-relative) host-read list."""

    def __init__(self, *, host_reads: list[AdBreak], empty_transcript: bool = False):
        self.host_reads = host_reads
        self.empty_transcript = empty_transcript
        self.transcribe_calls = 0
        self.analyse_calls = 0

    def transcribe(self, audio_path, report=None):
        self.transcribe_calls += 1
        if report is not None:
            report.input_tokens = (report.input_tokens or 0) + 50
            report.output_tokens = (report.output_tokens or 0) + 10
            report.cost_usd = (report.cost_usd or 0.0) + 0.001
        if self.empty_transcript:
            return Transcription(segments=[])
        return Transcription(
            segments=[TranscriptionSegment(start_time=0.0, end_time=100.0, text="hello")]
        )

    def analyse_host_reads(self, transcription, report=None):
        self.analyse_calls += 1
        if report is not None:
            report.input_tokens = (report.input_tokens or 0) + 200
            report.output_tokens = (report.output_tokens or 0) + 20
            report.cost_usd = (report.cost_usd or 0.0) + 0.002
        return list(self.host_reads)


def _patch_provider(monkeypatch, stub: _StubProvider):
    def _factory(task_type, _config):
        assert task_type in ("transcription", "analysis"), task_type
        return stub

    monkeypatch.setattr("app.tasks.get_ai_provider", _factory)


def _make_report(session, episode: PodcastEpisode) -> ClippingReport:
    report = ClippingReport(episode_id=episode.id)
    session.add(report)
    session.commit()
    session.refresh(report)
    return report


# ── Tests ────────────────────────────────────────────────────────────────────


def test_scan_disabled_is_noop(session, monkeypatch):
    """Toggle off (default) → task sets refined_at and touches nothing else."""
    from app.tasks import task_scan_acast_host_reads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=False)

    episode = _make_acast_episode(session, duration_ms=200_000, breaks=[(60_000, 90_000)])
    report = _make_report(session, episode)

    stub = _StubProvider(host_reads=[])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_host_reads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert report.refined_at is not None
    assert stub.transcribe_calls == 0
    assert [b.source for b in episode.ad_breaks] == ["acast_ident"]
    assert "disabled" in report.logs


def test_scan_skipped_without_models(session, monkeypatch):
    """Enabled but no transcription/analysis model configured → graceful no-op."""
    from app.tasks import task_scan_acast_host_reads

    _align_task_engine(monkeypatch)
    config = session.get(AppConfig, "config")
    config.scan_acast_host_reads = True
    session.add(config)
    session.commit()

    episode = _make_acast_episode(session, duration_ms=200_000, breaks=[(60_000, 90_000)])
    report = _make_report(session, episode)

    stub = _StubProvider(host_reads=[])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_host_reads.apply(args=[episode.id, report.id]).get()

    session.refresh(report)
    assert report.refined_at is not None
    assert stub.transcribe_calls == 0
    assert "not configured" in report.logs


def test_scan_appends_host_read_at_absolute_offset(session, monkeypatch):
    """A window-relative host read is offset to absolute time, tagged, and
    appended alongside the preserved ident break."""
    from app.tasks import task_scan_acast_host_reads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    # Break ends at 90s; window starts there. Stub reports a read 10s-40s into it.
    episode = _make_acast_episode(session, duration_ms=200_000, breaks=[(60_000, 90_000)])
    report = _make_report(session, episode)

    host_read = AdBreak(
        start_time=format_ms_to_time(10_000),
        end_time=format_ms_to_time(40_000),
        source=None,
    )
    stub = _StubProvider(host_reads=[host_read])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_host_reads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert stub.transcribe_calls == 1
    assert stub.analyse_calls == 1

    breaks = episode.ad_breaks
    assert len(breaks) == 2
    ident = next(b for b in breaks if b.source == "acast_ident")
    host = next(b for b in breaks if b.source == "host_read")
    assert parse_time_to_ms(ident.start_time) == 60_000
    # 90s window start + 10s/40s → 100s/130s absolute
    assert parse_time_to_ms(host.start_time) == 100_000
    assert parse_time_to_ms(host.end_time) == 130_000

    assert report.refined_at is not None
    assert "1 found" in report.logs
    assert report.refinement_report is not None
    assert report.refinement_report.cost_usd and report.refinement_report.cost_usd > 0


def test_scan_no_host_read_found_keeps_ident_only(session, monkeypatch):
    """Empty analysis result → only the ident break remains; scan still completes."""
    from app.tasks import task_scan_acast_host_reads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    episode = _make_acast_episode(session, duration_ms=200_000, breaks=[(60_000, 90_000)])
    report = _make_report(session, episode)

    stub = _StubProvider(host_reads=[])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_host_reads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert [b.source for b in episode.ad_breaks] == ["acast_ident"]
    assert "0 found" in report.logs
    assert report.refined_at is not None


def test_scan_short_tail_skips_transcription(session, monkeypatch):
    """If the only break ends near the episode end, the window is too short to
    scan, so no provider call is made."""
    from app.tasks import task_scan_acast_host_reads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    # 100s episode, break ends at 90s → 10s tail, below the minimum window.
    episode = _make_acast_episode(session, duration_ms=100_000, breaks=[(60_000, 90_000)])
    report = _make_report(session, episode)

    stub = _StubProvider(host_reads=[])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_host_reads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert stub.transcribe_calls == 0
    assert [b.source for b in episode.ad_breaks] == ["acast_ident"]
    assert report.refined_at is not None


def test_scan_idempotent_on_second_run(session, monkeypatch):
    """Second invocation short-circuits on refined_at — no extra provider calls
    and no duplicate host-read breaks."""
    from app.tasks import task_scan_acast_host_reads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    episode = _make_acast_episode(session, duration_ms=200_000, breaks=[(60_000, 90_000)])
    report = _make_report(session, episode)

    host_read = AdBreak(
        start_time=format_ms_to_time(10_000),
        end_time=format_ms_to_time(40_000),
        source=None,
    )
    stub = _StubProvider(host_reads=[host_read])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_host_reads.apply(args=[episode.id, report.id]).get()
    first_transcribe = stub.transcribe_calls
    assert first_transcribe == 1

    task_scan_acast_host_reads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    assert stub.transcribe_calls == first_transcribe, "second run should short-circuit"
    assert sum(1 for b in episode.ad_breaks if b.source == "host_read") == 1
