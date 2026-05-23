"""Split long transcripts into overlapping windows so that analysis models with
context windows smaller than ~1M tokens can still handle multi-hour episodes.

Only kicks in when an episode is longer than 2 hours AND the estimated prompt
size exceeds 60% of the model's context window. Below 2h every transcript fits
comfortably in even a 128k model, so we skip the token-count work entirely.

Token estimation is a chars/4 heuristic — good enough for sizing decisions
without a tokenizer dependency. The 0.6x safety factor leaves room for the
prompt scaffolding and the structured output."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from app.models import PodcastEpisodeAdvert, TranscriptionSegment
from app.services.editor import parse_time_to_ms

logger = logging.getLogger(__name__)

DURATION_THRESHOLD_S = 7200.0  # 2h — below this we always single-call
CONTEXT_SAFETY_FACTOR = 0.6  # of the model's context window, in tokens
CHARS_PER_TOKEN = 4  # tiktoken-free heuristic
DEFAULT_OVERLAP_S = 300.0  # 5 minutes either side of each chunk's primary range
ADVERT_IOU_DEDUP_THRESHOLD = 0.5


@dataclass
class Chunk:
    """One window of a chunked analysis call.

    ``primary_start``/``primary_end`` describe the section this chunk is
    responsible for — adverts found outside this range are considered to belong
    to neighbouring chunks and are dropped during merge. The ``segments`` list
    includes the primary range plus overlap on each side so the model has
    enough context to identify ads that straddle the boundary."""

    primary_start: float
    primary_end: float
    segments: list[TranscriptionSegment] = field(default_factory=list)


def _segments_to_prompt_json(segments: list[TranscriptionSegment]) -> str:
    """Mirror what providers.analyse_adverts pastes into the prompt."""
    payload = {"segments": [s.model_dump() for s in segments]}
    return json.dumps(payload, indent=2)


def estimate_prompt_tokens(segments: list[TranscriptionSegment]) -> int:
    return len(_segments_to_prompt_json(segments)) // CHARS_PER_TOKEN


def should_chunk(segments: list[TranscriptionSegment], context_window: int) -> bool:
    """Fast-path gate. Returns True only when chunking is both supported
    (context_window > 0) and necessary (duration > 2h and estimated prompt
    exceeds the safety budget)."""
    if context_window <= 0 or not segments:
        return False
    duration = segments[-1].end_time
    if duration <= DURATION_THRESHOLD_S:
        return False
    budget = int(context_window * CONTEXT_SAFETY_FACTOR)
    return estimate_prompt_tokens(segments) > budget


def _target_chars_for_chunk(context_window: int) -> int:
    return int(context_window * CONTEXT_SAFETY_FACTOR) * CHARS_PER_TOKEN


def chunk_segments(
    segments: list[TranscriptionSegment],
    context_window: int,
    overlap_seconds: float = DEFAULT_OVERLAP_S,
) -> list[Chunk]:
    """Split segments into chunks whose serialised JSON stays under
    ``CONTEXT_SAFETY_FACTOR x context_window`` tokens. Adjacent chunks overlap
    by ``overlap_seconds`` on each side (snapping to segment boundaries) so the
    model has enough context to identify ads near a chunk edge."""
    if not segments:
        return []

    # Per-segment char cost — measure the segment as it actually appears inside
    # the assembled `{"segments": [...]}` array, not how `json.dumps(seg)` alone
    # would serialise it. The array nesting adds 4 leading spaces per line which
    # otherwise adds up to a ~10% undercount on long episodes.
    scaffold_cost = len(_segments_to_prompt_json([]))
    segment_costs = [
        len(_segments_to_prompt_json([s])) - scaffold_cost for s in segments
    ]

    target_chars = _target_chars_for_chunk(context_window)
    if target_chars <= scaffold_cost:
        # Pathological context_window (e.g. 1000 tokens). Don't split into
        # zero-segment chunks — fall back to one chunk and let the API error.
        return [
            Chunk(
                primary_start=segments[0].start_time,
                primary_end=segments[-1].end_time,
                segments=list(segments),
            )
        ]

    # First pass: assign each segment to a primary chunk by char budget. Each
    # chunk owns a contiguous slice [primary_start, primary_end] of episode time.
    primary_ranges: list[tuple[float, float, int, int]] = []  # start, end, first_idx, last_idx
    running = scaffold_cost
    first = 0
    for i, cost in enumerate(segment_costs):
        if running + cost > target_chars and i > first:
            primary_ranges.append(
                (segments[first].start_time, segments[i - 1].end_time, first, i - 1)
            )
            first = i
            running = scaffold_cost
        running += cost
    primary_ranges.append(
        (segments[first].start_time, segments[-1].end_time, first, len(segments) - 1)
    )

    # Second pass: expand each chunk's segment slice to include overlap on each
    # side, snapping to segment boundaries.
    chunks: list[Chunk] = []
    for primary_start, primary_end, first_idx, last_idx in primary_ranges:
        lo = first_idx
        while lo > 0 and segments[lo - 1].end_time > primary_start - overlap_seconds:
            lo -= 1
        hi = last_idx
        while hi < len(segments) - 1 and segments[hi + 1].start_time < primary_end + overlap_seconds:
            hi += 1
        chunks.append(
            Chunk(
                primary_start=primary_start,
                primary_end=primary_end,
                segments=list(segments[lo : hi + 1]),
            )
        )
    return chunks


def _advert_seconds(advert: PodcastEpisodeAdvert) -> tuple[float, float]:
    return parse_time_to_ms(advert.start_time) / 1000.0, parse_time_to_ms(advert.end_time) / 1000.0


def _iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    inter = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def merge_adverts(
    advert_lists: list[list[PodcastEpisodeAdvert]],
    iou_threshold: float = ADVERT_IOU_DEDUP_THRESHOLD,
) -> list[PodcastEpisodeAdvert]:
    """Combine adverts from multiple chunks, dropping near-duplicates that the
    overlap windows produce. Two adverts whose time intervals have IoU above
    ``iou_threshold`` are treated as the same ad; the longer one wins (it tends
    to have the cleaner boundaries since both chunks fully contained it)."""
    flat: list[PodcastEpisodeAdvert] = [a for lst in advert_lists for a in lst]
    if not flat:
        return []

    # Sort by start time so the kept list ends up in episode order.
    flat.sort(key=lambda a: _advert_seconds(a)[0])

    kept: list[PodcastEpisodeAdvert] = []
    kept_spans: list[tuple[float, float]] = []
    for ad in flat:
        span = _advert_seconds(ad)
        duplicate_idx: int | None = None
        for i, existing in enumerate(kept_spans):
            if _iou(span, existing) >= iou_threshold:
                duplicate_idx = i
                break
        if duplicate_idx is None:
            kept.append(ad)
            kept_spans.append(span)
            continue
        # Prefer the longer-spanning advert as the canonical version.
        existing_duration = kept_spans[duplicate_idx][1] - kept_spans[duplicate_idx][0]
        new_duration = span[1] - span[0]
        if new_duration > existing_duration:
            kept[duplicate_idx] = ad
            kept_spans[duplicate_idx] = span

    return kept
