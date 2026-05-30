"""Tests for task_refine_boundaries — refining ad-break outer edges with a
Gemini audio model after the text analysis pass."""

from pathlib import Path

import pytest
from pydub import AudioSegment

from app.models import (
    AdBreak,
    Advert,
    AIModel,
    AIProvider,
    AppConfig,
    ClipMode,
    ClippingReport,
    PodcastEpisode,
    PodcastShow,
)
from app.services.editor import format_ms_to_time, parse_time_to_ms


def _silent_mp3(path: Path, duration_ms: int) -> None:
    AudioSegment.silent(duration=duration_ms).export(path, format="mp3")


def _align_task_engine(monkeypatch):
    """`app.tasks` binds the engine at module-load time. Realign with the
    per-test engine before invoking tasks directly."""
    from app.database import engine as current_engine

    monkeypatch.setattr("app.tasks.engine", current_engine)


def _make_ai_episode(
    session, *, duration_ms: int, breaks: list[tuple[int, int]]
) -> PodcastEpisode:
    """Create an AI clip-mode episode with a silent mp3 of the given duration
    and the given ad-break list (ms tuples for outer break bounds). Each break
    gets a single inner Advert spanning the whole break."""
    podcast = PodcastShow(
        title="Refine Show",
        itunes_id=f"refine-show-{duration_ms}-{len(breaks)}",
        source_rss_url="https://example.com/feed",
        path_directory=f"refine_show_{duration_ms}_{len(breaks)}",
        clip_mode=ClipMode.AI,
    )
    session.add(podcast)
    session.commit()
    session.refresh(podcast)

    episode = PodcastEpisode(
        podcast_id=podcast.id,
        guid=f"refine-ep-{duration_ms}-{len(breaks)}",
        title="Refine Episode",
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
            adverts=[
                Advert(
                    start_time=format_ms_to_time(s),
                    end_time=format_ms_to_time(e),
                    advert_for=f"Sponsor {i}",
                )
            ],
        )
        for i, (s, e) in enumerate(breaks, start=1)
    ]
    session.add(episode)
    session.commit()
    session.refresh(episode)
    return episode


def _configure_refinement_model(session) -> AIModel:
    provider_row = AIProvider(kind="gemini", name="Gemini", api_key="k")
    session.add(provider_row)
    session.commit()
    session.refresh(provider_row)
    model = AIModel(provider_id=provider_row.id, name="gemini-2.5-flash")
    session.add(model)
    session.commit()
    session.refresh(model)

    config = session.get(AppConfig, "config")
    config.boundary_refinement_model_id = model.id
    session.add(config)
    session.commit()
    return model


class _StubProvider:
    """Captures calls and returns scripted offsets keyed by direction."""

    def __init__(self, *, offsets: dict[str, int | None]):
        self.offsets = offsets
        self.calls: list[dict] = []

    def refine_boundary(
        self,
        *,
        audio_path,
        direction,
        report=None,
    ):
        self.calls.append({"direction": direction, "audio_path": audio_path})
        if report is not None:
            report.input_tokens = (report.input_tokens or 0) + 100
            report.output_tokens = (report.output_tokens or 0) + 5
            report.cost_usd = (report.cost_usd or 0.0) + 0.0001
        return self.offsets.get(direction)


def _patch_provider(monkeypatch, stub: _StubProvider):
    """Patch get_ai_provider to return the stub when called for refinement."""

    def _factory(task_type, _config):
        if task_type != "boundary_refinement":
            raise AssertionError(f"unexpected task_type: {task_type}")
        return stub

    monkeypatch.setattr("app.tasks.get_ai_provider", _factory)


def _make_report(session, episode: PodcastEpisode) -> ClippingReport:
    report = ClippingReport(episode_id=episode.id)
    session.add(report)
    session.commit()
    session.refresh(report)
    return report


# ── Tests ────────────────────────────────────────────────────────────────────


def test_refine_boundaries_skipped_when_no_model_configured(session, monkeypatch):
    """No boundary_refinement_model on AppConfig → task is a no-op that sets
    refined_at, leaving ad_breaks untouched."""
    from app.tasks import task_refine_boundaries

    _align_task_engine(monkeypatch)

    episode = _make_ai_episode(session, duration_ms=60_000, breaks=[(20_000, 30_000)])
    report = _make_report(session, episode)

    original_breaks = list(episode.ad_breaks)

    task_refine_boundaries.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert report.refined_at is not None
    assert "no refinement model configured" in report.logs
    assert [b.start_time for b in episode.ad_breaks] == [b.start_time for b in original_breaks]
    assert [b.end_time for b in episode.ad_breaks] == [b.end_time for b in original_breaks]


def test_refine_boundaries_no_breaks_skipped(session, monkeypatch):
    """No ad breaks on the episode → log + advance, no provider calls."""
    from app.tasks import task_refine_boundaries

    _align_task_engine(monkeypatch)
    _configure_refinement_model(session)

    episode = _make_ai_episode(session, duration_ms=60_000, breaks=[])
    report = _make_report(session, episode)

    stub = _StubProvider(offsets={})
    _patch_provider(monkeypatch, stub)

    task_refine_boundaries.apply(args=[episode.id, report.id]).get()

    session.refresh(report)
    assert report.refined_at is not None
    assert stub.calls == []
    assert "No ad breaks to refine" in report.logs


def test_refine_boundaries_mid_episode_both_edges_refined(session, monkeypatch):
    """Break is comfortably inside the episode — both edges sent to the model
    and refined to the model's reported offsets."""
    from app.tasks import task_refine_boundaries

    _align_task_engine(monkeypatch)
    _configure_refinement_model(session)

    # 60s episode, break at [20s, 30s]
    episode = _make_ai_episode(session, duration_ms=60_000, breaks=[(20_000, 30_000)])
    report = _make_report(session, episode)

    # ad_start window is [10s, 30s] (20s ±10s); offset 4000 → refined start = 14s
    # ad_end   window is [20s, 40s]; offset 12000 → refined end = 32s
    stub = _StubProvider(offsets={"ad_start": 4000, "ad_end": 12000})
    _patch_provider(monkeypatch, stub)

    task_refine_boundaries.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert len(stub.calls) == 2
    assert {c["direction"] for c in stub.calls} == {"ad_start", "ad_end"}

    refined = episode.ad_breaks
    assert len(refined) == 1
    assert parse_time_to_ms(refined[0].start_time) == 14_000
    assert parse_time_to_ms(refined[0].end_time) == 32_000
    # Inner advert list is preserved
    assert refined[0].adverts and refined[0].adverts[0].advert_for == "Sponsor 1"

    rr = report.refinement_report
    assert rr is not None
    assert rr.boundaries_refined == 2
    assert rr.boundaries_snapped == 0
    assert rr.boundaries_kept == 0
    assert report.refined_at is not None
    assert report.refinement_model_id is not None


def test_refine_boundaries_start_snapped_end_refined(session, monkeypatch):
    """Break starts within 5s of episode start → snap that edge to 0; refine the end."""
    from app.tasks import task_refine_boundaries

    _align_task_engine(monkeypatch)
    _configure_refinement_model(session)

    # 60s episode, break at [2s, 30s] — start is within SNAP_TO_EDGE_MS (5s) of 0
    episode = _make_ai_episode(session, duration_ms=60_000, breaks=[(2_000, 30_000)])
    report = _make_report(session, episode)

    # ad_end window [20s, 40s]; offset 12000 → refined end = 32s
    stub = _StubProvider(offsets={"ad_end": 12_000})
    _patch_provider(monkeypatch, stub)

    task_refine_boundaries.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    # Only the end was sent to the model
    assert len(stub.calls) == 1
    assert stub.calls[0]["direction"] == "ad_end"

    refined = episode.ad_breaks
    assert parse_time_to_ms(refined[0].start_time) == 0
    assert parse_time_to_ms(refined[0].end_time) == 32_000

    rr = report.refinement_report
    assert rr.boundaries_snapped == 1
    assert rr.boundaries_refined == 1
    assert rr.boundaries_kept == 0


def test_refine_boundaries_end_snapped_start_refined(session, monkeypatch):
    """Break ends within 5s of episode end → snap end to duration; refine the start."""
    from app.tasks import task_refine_boundaries

    _align_task_engine(monkeypatch)
    _configure_refinement_model(session)

    # 60s episode, break at [40s, 57s] — end is within 5s of 60s
    episode = _make_ai_episode(session, duration_ms=60_000, breaks=[(40_000, 57_000)])
    report = _make_report(session, episode)

    # ad_start window [30s, 50s]; offset 12000 → refined start = 42s
    stub = _StubProvider(offsets={"ad_start": 12_000})
    _patch_provider(monkeypatch, stub)

    task_refine_boundaries.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert len(stub.calls) == 1
    assert stub.calls[0]["direction"] == "ad_start"

    refined = episode.ad_breaks
    assert parse_time_to_ms(refined[0].start_time) == 42_000
    # End was snapped to episode_duration_ms (≈ 60s, allowing pydub wobble)
    assert parse_time_to_ms(refined[0].end_time) == pytest.approx(60_000, abs=300)

    rr = report.refinement_report
    assert rr.boundaries_snapped == 1
    assert rr.boundaries_refined == 1


def test_refine_boundaries_model_returns_none_keeps_original(session, monkeypatch):
    """Model returns None (unparseable / -1) → original boundary preserved,
    boundaries_kept incremented."""
    from app.tasks import task_refine_boundaries

    _align_task_engine(monkeypatch)
    _configure_refinement_model(session)

    episode = _make_ai_episode(session, duration_ms=60_000, breaks=[(20_000, 30_000)])
    report = _make_report(session, episode)

    stub = _StubProvider(offsets={"ad_start": None, "ad_end": None})
    _patch_provider(monkeypatch, stub)

    task_refine_boundaries.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    refined = episode.ad_breaks
    assert parse_time_to_ms(refined[0].start_time) == 20_000
    assert parse_time_to_ms(refined[0].end_time) == 30_000

    rr = report.refinement_report
    assert rr.boundaries_kept == 2
    assert rr.boundaries_refined == 0


def test_refine_boundaries_out_of_window_treated_as_keep(session, monkeypatch):
    """If the model returns an offset larger than the window length, the task
    must treat it as 'kept' rather than apply a wild boundary."""
    from app.tasks import task_refine_boundaries

    _align_task_engine(monkeypatch)
    _configure_refinement_model(session)

    episode = _make_ai_episode(session, duration_ms=60_000, breaks=[(20_000, 30_000)])
    report = _make_report(session, episode)

    # Window length is 20_000ms; 999_999 is far past the end.
    stub = _StubProvider(offsets={"ad_start": 999_999, "ad_end": 5_000})
    _patch_provider(monkeypatch, stub)

    task_refine_boundaries.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    refined = episode.ad_breaks
    # ad_start kept; ad_end refined to 20s window_start + 5s = 25s
    assert parse_time_to_ms(refined[0].start_time) == 20_000
    assert parse_time_to_ms(refined[0].end_time) == 25_000

    rr = report.refinement_report
    assert rr.boundaries_kept == 1
    assert rr.boundaries_refined == 1


def test_refine_boundaries_idempotent_on_second_run(session, monkeypatch):
    """If the task is invoked twice (e.g. retry after the chain re-runs), the
    second call should short-circuit on refined_at and not call the model again."""
    from app.tasks import task_refine_boundaries

    _align_task_engine(monkeypatch)
    _configure_refinement_model(session)

    episode = _make_ai_episode(session, duration_ms=60_000, breaks=[(20_000, 30_000)])
    report = _make_report(session, episode)

    stub = _StubProvider(offsets={"ad_start": 4_000, "ad_end": 12_000})
    _patch_provider(monkeypatch, stub)

    task_refine_boundaries.apply(args=[episode.id, report.id]).get()
    first_call_count = len(stub.calls)
    assert first_call_count == 2

    task_refine_boundaries.apply(args=[episode.id, report.id]).get()

    assert len(stub.calls) == first_call_count, "second invocation should short-circuit"


def test_refine_boundaries_full_episode_break_both_snapped(session, monkeypatch):
    """Degenerate case: break spans the whole episode. Both edges snap, no
    provider calls."""
    from app.tasks import task_refine_boundaries

    _align_task_engine(monkeypatch)
    _configure_refinement_model(session)

    episode = _make_ai_episode(session, duration_ms=10_000, breaks=[(1_000, 9_000)])
    report = _make_report(session, episode)

    stub = _StubProvider(offsets={})
    _patch_provider(monkeypatch, stub)

    task_refine_boundaries.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert stub.calls == []
    refined = episode.ad_breaks
    assert parse_time_to_ms(refined[0].start_time) == 0
    assert parse_time_to_ms(refined[0].end_time) == pytest.approx(10_000, abs=300)
    rr = report.refinement_report
    assert rr.boundaries_snapped == 2
