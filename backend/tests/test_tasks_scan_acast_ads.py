"""Tests for task_scan_acast_ads — the post-ident AI pass that reports the
advertisers inside each Acast ad section, sweeps the opening of the episode for
the pre-roll stack, and scans the content around later breaks for host-read
adverts."""

from pathlib import Path

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
    config.scan_acast_ads = enabled
    session.add(config)
    session.commit()


class _StubProvider:
    """Returns a fixed transcription and fixed (window-relative) breaks, dispatched
    by the analysis ``context``: opening pass, post-break host-read window,
    confirmed-section itemisation, or whole-episode fallback."""

    def __init__(
        self,
        *,
        opening_breaks: list[AdBreak] | None = None,
        host_reads: list[AdBreak] | None = None,
        section_breaks: list[AdBreak] | None = None,
        fallback_breaks: list[AdBreak] | None = None,
        empty_transcript: bool = False,
    ):
        self.opening_breaks = opening_breaks or []
        self.host_reads = host_reads or []
        self.section_breaks = section_breaks or []
        self.fallback_breaks = fallback_breaks or []
        self.empty_transcript = empty_transcript
        self.model_config = None  # real providers carry one; analyse_transcription reads it
        self.transcribe_calls = 0
        self.opening_calls = 0
        self.host_read_calls = 0
        self.section_calls = 0
        self.analyse_calls = 0
        self.opening_instructions: list[str | None] = []
        self.host_read_instructions: list[str | None] = []
        self.analyse_instructions: list[str | None] = []

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

    def analyse_ads(
        self, transcription, context, report=None, custom_instructions=None, chunk_range=None
    ):
        from app.services.prompts import (
            ADS_CONTEXT_CONFIRMED_BREAK,
            ADS_CONTEXT_OPENING,
            ADS_CONTEXT_POST_BREAK_WINDOW,
        )

        if context == ADS_CONTEXT_CONFIRMED_BREAK:
            self.section_calls += 1
            result, bump = self.section_breaks, (100, 15, 0.0015)
        elif context == ADS_CONTEXT_OPENING:
            self.opening_calls += 1
            self.opening_instructions.append(custom_instructions)
            result, bump = self.opening_breaks, (200, 20, 0.002)
        elif context == ADS_CONTEXT_POST_BREAK_WINDOW:
            self.host_read_calls += 1
            self.host_read_instructions.append(custom_instructions)
            result, bump = self.host_reads, (200, 20, 0.002)
        else:  # ADS_CONTEXT_FULL_EPISODE (low-confidence fallback)
            self.analyse_calls += 1
            self.analyse_instructions.append(custom_instructions)
            result, bump = self.fallback_breaks, (300, 40, 0.004)
        if report is not None:
            report.input_tokens = (report.input_tokens or 0) + bump[0]
            report.output_tokens = (report.output_tokens or 0) + bump[1]
            report.cost_usd = (report.cost_usd or 0.0) + bump[2]
        return list(result)


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


def _advert(start_ms: int, end_ms: int, name: str) -> Advert:
    return Advert(
        start_time=format_ms_to_time(start_ms),
        end_time=format_ms_to_time(end_ms),
        advert_for=name,
    )


# A mid-roll break sits well past the 5-minute opening region, so the section and
# host-read window logic can be exercised without the opening pass overlapping it.
_MIDROLL = (500_000, 530_000)
_LONG_MS = 900_000


# ── Tests ────────────────────────────────────────────────────────────────────


def test_scan_disabled_is_noop(session, monkeypatch):
    """Toggle off → task sets refined_at and touches nothing else."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=False)

    episode = _make_acast_episode(session, duration_ms=200_000, breaks=[(60_000, 90_000)])
    report = _make_report(session, episode)

    stub = _StubProvider()
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert report.refined_at is not None
    assert stub.transcribe_calls == 0
    assert [b.source for b in episode.ad_breaks] == ["acast_ident"]
    assert episode.ad_breaks[0].adverts is None
    assert "disabled" in report.logs


def test_scan_skipped_without_models(session, monkeypatch):
    """Enabled but no transcription/analysis model configured → graceful no-op."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    config = session.get(AppConfig, "config")
    config.scan_acast_ads = True
    session.add(config)
    session.commit()

    episode = _make_acast_episode(session, duration_ms=200_000, breaks=[(60_000, 90_000)])
    report = _make_report(session, episode)

    stub = _StubProvider()
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    session.refresh(report)
    assert report.refined_at is not None
    assert stub.transcribe_calls == 0
    assert "not configured" in report.logs


def test_scan_reports_section_and_appends_host_read(session, monkeypatch):
    """A mid-roll ident section gets its advertisers itemised (absolute time), the
    opening pass runs once, and window-relative host reads are offset and appended."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    episode = _make_acast_episode(session, duration_ms=_LONG_MS, breaks=[_MIDROLL])
    report = _make_report(session, episode)

    # Section advert 5s-25s into the 500s-530s break → absolute 505s-525s.
    section = AdBreak(
        start_time=format_ms_to_time(5_000),
        end_time=format_ms_to_time(25_000),
        adverts=[_advert(5_000, 25_000, "Shopify")],
    )
    host_read = AdBreak(
        start_time=format_ms_to_time(10_000),
        end_time=format_ms_to_time(40_000),
        adverts=[_advert(10_000, 40_000, "Squarespace")],
    )
    stub = _StubProvider(host_reads=[host_read], section_breaks=[section])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    # Opening pass (1) + section (1) + leading window (1) + trailing window (1).
    assert stub.transcribe_calls == 4
    assert stub.opening_calls == 1
    assert stub.section_calls == 1
    assert stub.host_read_calls == 2

    breaks = episode.ad_breaks
    assert len(breaks) == 3
    ident = next(b for b in breaks if b.source == "acast_ident")
    hosts = sorted(
        (b for b in breaks if b.source == "host_read"),
        key=lambda b: parse_time_to_ms(b.start_time),
    )
    assert len(hosts) == 2
    leading, trailing = hosts

    # Section advert reported at absolute time (500s + 5s/25s → 505s/525s).
    assert ident.adverts is not None
    assert ident.adverts[0].advert_for == "Shopify"
    assert parse_time_to_ms(ident.adverts[0].start_time) == 505_000
    assert parse_time_to_ms(ident.adverts[0].end_time) == 525_000

    # Leading window [380s, 500s] → the read 10s-40s in stays at 390s/420s.
    assert parse_time_to_ms(leading.start_time) == 390_000
    assert parse_time_to_ms(leading.end_time) == 420_000
    # Trailing window starts at 530s → the read is offset to 540s/570s.
    assert parse_time_to_ms(trailing.start_time) == 540_000
    assert parse_time_to_ms(trailing.end_time) == 570_000
    assert trailing.adverts is not None
    assert parse_time_to_ms(trailing.adverts[0].start_time) == 540_000

    assert report.refined_at is not None
    assert "reported ads in 1 section(s)" in report.logs
    assert "0 opening-pass break(s)" in report.logs
    assert "2 host-read(s) across 2 window(s)" in report.logs
    assert "3 cut(s) after merge" in report.logs
    assert report.refinement_report is not None
    assert report.refinement_report.cost_usd and report.refinement_report.cost_usd > 0


def test_scan_reports_section_when_no_host_read(session, monkeypatch):
    """Section itemised, opening pass and windows find nothing → only the ident
    break remains, now carrying its advert detail."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    episode = _make_acast_episode(session, duration_ms=_LONG_MS, breaks=[_MIDROLL])
    report = _make_report(session, episode)

    section = AdBreak(
        start_time=format_ms_to_time(0),
        end_time=format_ms_to_time(30_000),
        adverts=[_advert(0, 30_000, "BetMGM")],
    )
    stub = _StubProvider(host_reads=[], section_breaks=[section])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert [b.source for b in episode.ad_breaks] == ["acast_ident"]
    assert episode.ad_breaks[0].adverts[0].advert_for == "BetMGM"
    assert "reported ads in 1 section(s)" in report.logs
    assert "0 host-read(s) across 2 window(s)" in report.logs
    assert report.refined_at is not None


def test_opening_pass_detects_preroll_the_idents_missed(session, monkeypatch):
    """The opening pass finds a pre-roll advert that has no jingle to anchor on and
    appends it as a new cut tagged opening_scan, alongside the mid-roll ident."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    episode = _make_acast_episode(session, duration_ms=_LONG_MS, breaks=[_MIDROLL])
    report = _make_report(session, episode)

    # Pre-roll the jingle detector missed: 20s-80s, absolute (opening window is 0).
    preroll = AdBreak(
        start_time=format_ms_to_time(20_000),
        end_time=format_ms_to_time(80_000),
        adverts=[_advert(20_000, 80_000, "Cunard")],
    )
    stub = _StubProvider(opening_breaks=[preroll])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert stub.opening_calls == 1
    opening = next(b for b in episode.ad_breaks if b.source == "opening_scan")
    assert parse_time_to_ms(opening.start_time) == 20_000
    assert parse_time_to_ms(opening.end_time) == 80_000
    assert opening.adverts[0].advert_for == "Cunard"
    assert "1 opening-pass break(s)" in report.logs


def test_opening_pass_fuses_with_overlapping_preroll_ident(session, monkeypatch):
    """A pre-roll ident is inside the opening region: its section is NOT re-itemised
    and its near windows are dropped; the opening-pass break overlapping it fuses
    into one clean cut keeping the jingle-precise source label."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    # Pre-roll ident break 0s-32s; episode 900s with no other break.
    episode = _make_acast_episode(session, duration_ms=_LONG_MS, breaks=[(0, 32_000)])
    report = _make_report(session, episode)

    # The opening pass sees the whole pre-roll stack 0s-113s.
    opening = AdBreak(
        start_time=format_ms_to_time(0),
        end_time=format_ms_to_time(113_000),
        adverts=[_advert(0, 113_000, "Arnold Clark")],
    )
    stub = _StubProvider(opening_breaks=[opening])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    # Section itemisation skipped (break is inside the opening region) and the
    # trailing window inside the opening region dropped → only the opening pass ran.
    assert stub.section_calls == 0
    assert stub.host_read_calls == 0
    assert stub.opening_calls == 1
    assert stub.transcribe_calls == 1

    assert len(episode.ad_breaks) == 1
    fused = episode.ad_breaks[0]
    assert fused.source == "acast_ident"
    assert parse_time_to_ms(fused.start_time) == 0
    assert parse_time_to_ms(fused.end_time) == 113_000
    assert fused.adverts[0].advert_for == "Arnold Clark"


def test_opening_pass_receives_custom_instructions(session, monkeypatch):
    """The per-podcast custom prompt reaches both the opening pass and the
    host-read windows."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    episode = _make_acast_episode(session, duration_ms=_LONG_MS, breaks=[_MIDROLL])
    episode.podcast.custom_prompt = "Never clip the eBay segment."
    session.add(episode.podcast)
    session.commit()
    report = _make_report(session, episode)

    stub = _StubProvider()
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    assert stub.opening_instructions == ["Never clip the eBay segment."]
    assert stub.host_read_instructions == ["Never clip the eBay segment."] * 2


def test_scan_idempotent_on_second_run(session, monkeypatch):
    """Second invocation short-circuits on refined_at — no extra provider calls
    and no duplicate breaks."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    episode = _make_acast_episode(session, duration_ms=_LONG_MS, breaks=[_MIDROLL])
    report = _make_report(session, episode)

    host_read = AdBreak(
        start_time=format_ms_to_time(10_000),
        end_time=format_ms_to_time(40_000),
    )
    stub = _StubProvider(host_reads=[host_read])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()
    first_transcribe = stub.transcribe_calls
    assert first_transcribe == 4  # opening + section + leading + trailing

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    assert stub.transcribe_calls == first_transcribe, "second run should short-circuit"
    assert sum(1 for b in episode.ad_breaks if b.source == "host_read") == 2


def test_scan_clamps_overshooting_results_to_their_slice(session, monkeypatch):
    """A section advert or host-read break whose end runs past its slice is
    clamped to the slice bounds so it can't over-report or over-cut."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    episode = _make_acast_episode(session, duration_ms=_LONG_MS, breaks=[_MIDROLL])
    report = _make_report(session, episode)

    # Section advert overshoots the 30s section (ends at 50s relative).
    section = AdBreak(
        start_time=format_ms_to_time(5_000),
        end_time=format_ms_to_time(50_000),
        adverts=[_advert(5_000, 50_000, "Overshoot")],
    )
    # Host read overshoots its window (ends at 150s relative).
    host_read = AdBreak(
        start_time=format_ms_to_time(10_000),
        end_time=format_ms_to_time(150_000),
        adverts=[_advert(10_000, 150_000, "LongRead")],
    )
    stub = _StubProvider(host_reads=[host_read], section_breaks=[section])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    ident = next(b for b in episode.ad_breaks if b.source == "acast_ident")
    hosts = sorted(
        (b for b in episode.ad_breaks if b.source == "host_read"),
        key=lambda b: parse_time_to_ms(b.start_time),
    )
    leading, trailing = hosts

    # Section advert clamped to the section end (530s).
    assert parse_time_to_ms(ident.adverts[0].end_time) == 530_000
    # Each host read is clamped to its own window: the leading window ends at the
    # break start (500s), the trailing window at break end + 120s (650s).
    assert parse_time_to_ms(leading.end_time) == 500_000
    assert parse_time_to_ms(leading.adverts[0].end_time) == 500_000
    assert parse_time_to_ms(trailing.start_time) == 540_000
    assert parse_time_to_ms(trailing.end_time) == 650_000
    assert parse_time_to_ms(trailing.adverts[0].end_time) == 650_000


def test_scan_skips_section_transcription_when_already_reported(session, monkeypatch):
    """A mid-roll ident break that already carries advert detail is not
    re-transcribed for itemisation."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    episode = _make_acast_episode(session, duration_ms=_LONG_MS, breaks=[_MIDROLL])
    # Pre-populate the ident break with advert detail.
    breaks = episode.ad_breaks
    breaks[0] = AdBreak(
        start_time=breaks[0].start_time,
        end_time=breaks[0].end_time,
        adverts=[_advert(500_000, 530_000, "Existing")],
        source="acast_ident",
    )
    episode.ad_breaks = breaks
    session.add(episode)
    session.commit()
    report = _make_report(session, episode)

    stub = _StubProvider(host_reads=[])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    # No section transcription (already reported); only opening + scan windows.
    assert stub.section_calls == 0
    ident = next(b for b in episode.ad_breaks if b.source == "acast_ident")
    assert ident.adverts[0].advert_for == "Existing"


def test_scan_catches_host_read_leading_into_break(session, monkeypatch):
    """A host read that airs just BEFORE an ident break (leading into it) is scanned
    and cut, as well as one trailing the break."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    episode = _make_acast_episode(session, duration_ms=_LONG_MS, breaks=[_MIDROLL])
    report = _make_report(session, episode)

    host_read = AdBreak(
        start_time=format_ms_to_time(10_000),
        end_time=format_ms_to_time(40_000),
        adverts=[_advert(10_000, 40_000, "Contentful")],
    )
    stub = _StubProvider(host_reads=[host_read])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()
    session.refresh(episode)

    hosts = sorted(
        (b for b in episode.ad_breaks if b.source == "host_read"),
        key=lambda b: parse_time_to_ms(b.start_time),
    )
    # Leading window [380s, 500s]: read 10s in → 390s-420s, before the break.
    # Trailing window [530s, 650s]: read 10s in → 540s-570s.
    assert [parse_time_to_ms(b.start_time) for b in hosts] == [390_000, 540_000]
    # The lead-in read ends before the break starts — the case that used to slip.
    assert parse_time_to_ms(hosts[0].end_time) == 420_000
    assert parse_time_to_ms(hosts[0].end_time) <= 500_000


def test_scan_low_confidence_falls_back_to_whole_episode(session, monkeypatch):
    """Too few ident breaks for the episode length → the whole-episode fallback
    runs (full-episode context) and the opening pass does not."""
    from app.tasks import task_scan_acast_ads

    _align_task_engine(monkeypatch)
    _configure_models(session, enabled=True)

    # 900s episode expects one break; with zero idents detected it's low-confidence.
    episode = _make_acast_episode(session, duration_ms=_LONG_MS, breaks=[])
    report = _make_report(session, episode)

    fallback = AdBreak(
        start_time=format_ms_to_time(30_000),
        end_time=format_ms_to_time(150_000),
        adverts=[_advert(30_000, 150_000, "Shopify")],
        source="ai_fallback",
    )
    stub = _StubProvider(fallback_breaks=[fallback])
    _patch_provider(monkeypatch, stub)

    task_scan_acast_ads.apply(args=[episode.id, report.id]).get()

    session.refresh(episode)
    session.refresh(report)

    assert stub.analyse_calls == 1
    assert stub.opening_calls == 0
    assert stub.section_calls == 0
    assert stub.host_read_calls == 0
    assert [b.source for b in episode.ad_breaks] == ["ai_fallback"]
    assert "whole-episode AI pass" in report.logs
