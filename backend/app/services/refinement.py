"""WIP — boundary refinement is not wired into the production AI clipping
chain. `queue_episode_for_clipping` deliberately omits `task_refine_boundaries`
because offline evals have not yet shown a clear quality win over plain
analysis to justify the extra cost and latency. Until that changes, the
helper below is only exercised by the `ai_refined` eval mode and by direct
invocation of `task_refine_boundaries` (which remains a registered Celery
task and a config-gated no-op if no `boundary_refinement_model` is set).

Shared boundary-refinement logic. Given a text-model-predicted ad-break edge,
decides whether to snap it to an episode edge, send a short audio window to
the refinement provider, or keep the original boundary."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal, Protocol

from pydub import AudioSegment

from app.models import RefinementReport
from app.services.editor import format_ms_to_time

SNAP_TO_EDGE_MS = 5000  # snap an outer ad-break edge to 0 / episode-end if within this gap
REFINEMENT_WINDOW_MS = 10_000  # ±10s around the analysed boundary → 20s symmetric window


class RefinementProvider(Protocol):
    """Anything with a ``refine_boundary`` method matching GeminiProvider's
    signature can be passed in. Keeps this module decoupled from the concrete
    provider class so the eval pipeline can pass its own."""

    def refine_boundary(
        self,
        audio_path: Path,
        direction: Literal["ad_start", "ad_end"],
        report: RefinementReport | None = ...,
    ) -> int | None: ...


def refine_or_snap_boundary(
    *,
    audio: AudioSegment,
    episode_duration_ms: int,
    boundary_ms: int,
    direction: Literal["ad_start", "ad_end"],
    provider: RefinementProvider,
    refinement_report: RefinementReport,
    log: Callable[[str], None] | None = None,
    break_index: int | None = None,
) -> int:
    """Decide whether to snap, refine, or keep a single ad-break boundary.

    Returns the new (or unchanged) boundary in absolute milliseconds. Mutates
    ``refinement_report`` counters as a side effect. If ``log`` is supplied,
    appends a one-line per-boundary outcome to it; pass ``None`` to suppress
    logging (e.g. from the eval pipeline)."""
    prefix = f"Break {break_index} " if break_index is not None else ""

    def _emit(message: str) -> None:
        if log is not None:
            log(f"{prefix}{message}")

    is_outer_edge = (direction == "ad_start" and boundary_ms < SNAP_TO_EDGE_MS) or (
        direction == "ad_end" and (episode_duration_ms - boundary_ms) < SNAP_TO_EDGE_MS
    )
    if is_outer_edge:
        snapped_ms = 0 if direction == "ad_start" else episode_duration_ms
        refinement_report.boundaries_snapped += 1
        _emit(
            f"{direction}: snapped {format_ms_to_time(boundary_ms)} → "
            f"{format_ms_to_time(snapped_ms)} (within {SNAP_TO_EDGE_MS}ms of episode edge)"
        )
        return snapped_ms

    window_start_ms = max(0, boundary_ms - REFINEMENT_WINDOW_MS)
    window_end_ms = min(episode_duration_ms, boundary_ms + REFINEMENT_WINDOW_MS)
    if window_end_ms <= window_start_ms:
        refinement_report.boundaries_kept += 1
        _emit(f"{direction}: window collapsed, keeping original boundary")
        return boundary_ms

    window_audio = audio[window_start_ms:window_end_ms]
    temp_fd, temp_path_str = tempfile.mkstemp(suffix=".mp3")
    temp_path = Path(temp_path_str)
    os.close(temp_fd)
    try:
        window_audio.export(temp_path, format="mp3")
        offset_in_window = provider.refine_boundary(
            audio_path=temp_path,
            direction=direction,
            report=refinement_report,
        )
    finally:
        if temp_path.exists():
            temp_path.unlink()

    window_length_ms = window_end_ms - window_start_ms
    if offset_in_window is None or offset_in_window > window_length_ms:
        refinement_report.boundaries_kept += 1
        _emit(
            f"{direction}: model could not determine boundary "
            f"(returned {offset_in_window!r}), keeping original"
        )
        return boundary_ms

    refined_ms = window_start_ms + offset_in_window
    refinement_report.boundaries_refined += 1
    _emit(f"{direction}: refined {format_ms_to_time(boundary_ms)} → {format_ms_to_time(refined_ms)}")
    return refined_ms
