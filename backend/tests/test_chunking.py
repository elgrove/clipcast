"""Tests for the transcript-chunking pipeline used when the analysis model's
context window can't swallow the whole episode in one call."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

import pytest

from app.models import (
    AIModel,
    AnalysisReport,
    PodcastEpisodeAdvert,
    TranscriptionSegment,
)
from app.services.analysis import analyse_transcription
from app.services.chunking import (
    DURATION_THRESHOLD_S,
    chunk_segments,
    estimate_prompt_tokens,
    merge_adverts,
    should_chunk,
)
from app.services.providers import PodcastEpisodeAdverts, Transcription


def _segments(duration_s: float, segs_per_minute: int = 30, words_per_seg: int = 12):
    """Build a fake transcript spanning ``duration_s`` seconds. Each segment is
    a fixed length so the test can reason about chunk sizes precisely."""
    seg_count = int(duration_s / 60 * segs_per_minute)
    seg_len = duration_s / seg_count
    word = "transcribe"
    text = " ".join([word] * words_per_seg)
    return [
        TranscriptionSegment(
            start_time=i * seg_len,
            end_time=(i + 1) * seg_len,
            text=text,
        )
        for i in range(seg_count)
    ]


# ── should_chunk ─────────────────────────────────────────────────────────────


def test_should_chunk_skips_when_context_window_unset():
    segs = _segments(duration_s=5 * 3600)  # 5h
    assert should_chunk(segs, context_window=0) is False


def test_should_chunk_skips_under_two_hours():
    segs = _segments(duration_s=DURATION_THRESHOLD_S - 60)  # 1h59m
    assert should_chunk(segs, context_window=131_072) is False


def test_should_chunk_skips_when_transcript_fits_comfortably():
    # 2h05m of low-density transcript stays well under 60% of a 1M context.
    segs = _segments(duration_s=DURATION_THRESHOLD_S + 300, segs_per_minute=10)
    assert should_chunk(segs, context_window=1_048_576) is False


def test_should_chunk_triggers_long_episode_small_context():
    segs = _segments(duration_s=4 * 3600)
    assert should_chunk(segs, context_window=131_072) is True


# ── chunk_segments ───────────────────────────────────────────────────────────


def test_chunk_segments_produces_multiple_chunks_for_long_episode():
    segs = _segments(duration_s=4 * 3600)
    chunks = chunk_segments(segs, context_window=131_072)
    assert len(chunks) >= 2
    # First segment of the episode appears in the first chunk; last in the last.
    assert chunks[0].segments[0].start_time == pytest.approx(segs[0].start_time)
    assert chunks[-1].segments[-1].end_time == pytest.approx(segs[-1].end_time)


def test_chunk_segments_primary_ranges_tile_the_episode():
    segs = _segments(duration_s=4 * 3600)
    chunks = chunk_segments(segs, context_window=131_072)
    # Primary ranges are contiguous and cover [0, episode_end].
    assert chunks[0].primary_start == pytest.approx(segs[0].start_time)
    for prev, curr in pairwise(chunks):
        # Each next chunk's primary starts where the previous one ended (within
        # one segment of slop because boundaries snap to segment edges).
        assert curr.primary_start >= prev.primary_end - 1.0
        assert curr.primary_start <= prev.primary_end + 5.0
    assert chunks[-1].primary_end == pytest.approx(segs[-1].end_time)


def test_chunk_segments_overlap_extends_into_neighbours():
    segs = _segments(duration_s=4 * 3600)
    chunks = chunk_segments(segs, context_window=131_072, overlap_seconds=300.0)
    if len(chunks) < 2:
        pytest.skip("Need at least 2 chunks to inspect overlap")
    # The second chunk's segment list starts earlier than its primary_start,
    # because it grabs ~5min of context from the preceding chunk.
    chunk = chunks[1]
    assert chunk.segments[0].start_time < chunk.primary_start
    overlap_back = chunk.primary_start - chunk.segments[0].start_time
    assert 60.0 <= overlap_back <= 600.0  # ballpark of the 300s target


def test_chunk_segments_each_chunk_fits_target():
    segs = _segments(duration_s=4 * 3600)
    context = 131_072
    chunks = chunk_segments(segs, context_window=context)
    # Each chunk's primary segments (no overlap) must fit the safety budget,
    # so the chunk-plus-overlap might be a touch over — we only assert the
    # primary slice respects the budget here.
    budget_tokens = int(context * 0.6)
    for chunk in chunks:
        primary_segs = [
            s for s in chunk.segments if chunk.primary_start <= s.start_time < chunk.primary_end + 0.001
        ]
        assert estimate_prompt_tokens(primary_segs) <= budget_tokens * 1.05


# ── merge_adverts ────────────────────────────────────────────────────────────


def _ad(start: float, end: float, label: str = "Ad") -> PodcastEpisodeAdvert:
    def fmt(s: float) -> str:
        h = int(s // 3600)
        m = int((s % 3600) // 60)
        secs = s % 60
        return f"{h:02d}:{m:02d}:{secs:06.3f}"

    return PodcastEpisodeAdvert(
        start_time=fmt(start),
        end_time=fmt(end),
        advert_for=label,
        front_text="",
        tail_text="",
    )


def test_merge_adverts_dedupes_overlap_duplicates():
    # The same ad found by two adjacent chunks — boundaries slightly off.
    a1 = _ad(1800.0, 1860.0, "Acme")
    a2 = _ad(1802.0, 1858.0, "Acme")
    merged = merge_adverts([[a1], [a2]])
    assert len(merged) == 1


def test_merge_adverts_keeps_distinct_ads():
    # Two real ads that happen to be close in time — well below IoU 0.5.
    a1 = _ad(100.0, 130.0, "Brand A")
    a2 = _ad(140.0, 170.0, "Brand B")
    merged = merge_adverts([[a1], [a2]])
    assert len(merged) == 2


def test_merge_adverts_prefers_longer_span():
    # Same ad seen by overlapping chunks: short version trims the head/tail,
    # long version captures the full break. IoU must clear 0.5 for merge.
    short = _ad(1005.0, 1025.0, "Truncated")
    long_ = _ad(1000.0, 1030.0, "Full")
    merged = merge_adverts([[short], [long_]])
    assert len(merged) == 1
    assert merged[0].advert_for == "Full"


def test_merge_adverts_sorts_by_start_time():
    ads_lists = [[_ad(2000.0, 2030.0, "B")], [_ad(100.0, 130.0, "A")]]
    merged = merge_adverts(ads_lists)
    assert [m.advert_for for m in merged] == ["A", "B"]


# ── analyse_transcription orchestration ──────────────────────────────────────


@dataclass
class _StubProvider:
    """In-process provider that records each chunk's segments + the chunk_range
    it was called with, and emits a canned advert in the middle of each chunk."""

    model_config: AIModel
    calls: list[tuple[float, float, int]] = None
    tokens_per_call: int = 1000
    cost_per_call: float = 0.01

    def __post_init__(self):
        self.calls = []

    def transcribe(self, audio_path, report=None):  # pragma: no cover - unused
        raise NotImplementedError

    def analyse_adverts(
        self,
        transcription: Transcription,
        report: AnalysisReport | None = None,
        custom_instructions: str | None = None,
        chunk_range: tuple[float, float] | None = None,
    ) -> PodcastEpisodeAdverts:
        if chunk_range is None:
            chunk_range = (
                transcription.segments[0].start_time,
                transcription.segments[-1].end_time,
            )
        self.calls.append((chunk_range[0], chunk_range[1], len(transcription.segments)))
        if report is not None:
            report.input_tokens = self.tokens_per_call
            report.output_tokens = self.tokens_per_call // 4
            report.cost_usd = self.cost_per_call
        midpoint = (chunk_range[0] + chunk_range[1]) / 2
        return PodcastEpisodeAdverts(adverts=[_ad(midpoint, midpoint + 60.0, "Acme")])


def _model(context_window: int) -> AIModel:
    # Tests only need context_window; analyse_transcription reads nothing else
    # off the model_config. Avoid the AIProvider relationship to keep the test
    # stub free of SQLAlchemy plumbing.
    return AIModel(name="stub", context_window=context_window)


def test_analyse_transcription_single_call_for_short_episode():
    segs = _segments(duration_s=DURATION_THRESHOLD_S - 60)  # 1h59m
    provider = _StubProvider(model_config=_model(context_window=131_072))
    report = AnalysisReport(provider="openrouter", model_name="stub")
    adverts = analyse_transcription(segs, provider, report)
    assert len(provider.calls) == 1
    assert adverts and adverts[0].advert_for == "Acme"
    assert report.input_tokens == 1000


def test_analyse_transcription_chunks_long_episode():
    segs = _segments(duration_s=4 * 3600)
    provider = _StubProvider(model_config=_model(context_window=131_072))
    report = AnalysisReport(provider="openrouter", model_name="stub")
    adverts = analyse_transcription(segs, provider, report)

    assert len(provider.calls) >= 2, "Expected multiple chunked calls"
    # Tokens/cost accumulate across chunks rather than overwriting.
    assert report.input_tokens == 1000 * len(provider.calls)
    assert report.output_tokens == 250 * len(provider.calls)
    assert report.cost_usd == pytest.approx(0.01 * len(provider.calls))
    # One advert per chunk, none dropped because each lives in its own primary
    # range and there are no IoU duplicates.
    assert len(adverts) == len(provider.calls)


def test_analyse_transcription_filters_advert_outside_primary_range():
    # Provider returns an ad outside the chunk's primary range — should be
    # dropped because the neighbouring chunk owns that region.
    segs = _segments(duration_s=4 * 3600)
    model = _model(context_window=131_072)

    class _OutOfRangeProvider(_StubProvider):
        def analyse_adverts(self, transcription, report=None, custom_instructions=None, chunk_range=None):
            self.calls.append((chunk_range[0], chunk_range[1], len(transcription.segments)))
            if report is not None:
                report.input_tokens = 100
                report.output_tokens = 25
                report.cost_usd = 0.001
            # Always return an ad placed in the first chunk's range.
            return PodcastEpisodeAdverts(adverts=[_ad(100.0, 130.0, "Acme")])

    provider = _OutOfRangeProvider(model_config=model)
    report = AnalysisReport(provider="openrouter", model_name="stub")
    adverts = analyse_transcription(segs, provider, report)
    # Every chunk reports the same ad, but only the chunk whose primary range
    # contains it keeps it; the rest get dropped.
    assert len(adverts) == 1
    assert adverts[0].advert_for == "Acme"
