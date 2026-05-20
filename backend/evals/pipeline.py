from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.models import (
    ACAST_ADVERT_LABEL,
    AnalysisReport,
    CutRegion,
    PodcastEpisodeAdvert,
    TranscriptionSegment,
)
from app.services.acast import detect_idents, idents_to_cut_regions, pair_idents
from app.services.analysis import analyse_transcription

from .metrics import (
    Interval,
    count_metrics,
    duration_metrics,
    match_intervals,
    parse_time,
)
from .providers import ModelSpec, build_provider

FIXTURES_DIR = Path(__file__).parent / "fixtures"
AUDIO_CANDIDATES = ("audio.mp3", "audio.wav", "audio.m4a", "audio.ogg")


def _load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


@dataclass
class EvalCase:
    case_id: str
    path: Path
    meta: dict[str, Any]
    transcription_path: Path | None
    audio_path: Path | None
    expected: list[CutRegion]

    def load_transcription(self) -> list[TranscriptionSegment]:
        if not self.transcription_path:
            raise FileNotFoundError(
                f"Case {self.case_id!r} has no transcription.json; required when use_acast=false."
            )
        raw = _load_json(self.transcription_path)
        return [TranscriptionSegment(**s) for s in raw]

    def require_audio(self) -> Path:
        if not self.audio_path:
            raise FileNotFoundError(
                f"Case {self.case_id!r} has no audio file; required when use_acast=true."
            )
        return self.audio_path


def list_cases() -> list[str]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(
        p.name for p in FIXTURES_DIR.iterdir() if p.is_dir() and not p.name.startswith(".")
    )


def load_case(case_id: str) -> EvalCase:
    case_dir = FIXTURES_DIR / case_id
    if not case_dir.exists():
        raise FileNotFoundError(f"Case fixture not found: {case_dir}")

    meta = _load_json(case_dir / "meta.json") if (case_dir / "meta.json").exists() else {}

    transcription_path = case_dir / "transcription.json"
    if not transcription_path.exists():
        transcription_path = None

    audio_path: Path | None = None
    for name in AUDIO_CANDIDATES:
        candidate = case_dir / name
        if candidate.exists():
            audio_path = candidate
            break

    expected_path = case_dir / "expected.json"
    if not expected_path.exists():
        raise FileNotFoundError(f"Missing expected.json in {case_dir}")
    expected = [CutRegion(**r) for r in _load_json(expected_path)]

    return EvalCase(
        case_id=case_id,
        path=case_dir,
        meta=meta,
        transcription_path=transcription_path,
        audio_path=audio_path,
        expected=expected,
    )


# ── Cut-region conversion ────────────────────────────────────────────────────


def _ad_to_cut_region(ad: PodcastEpisodeAdvert) -> CutRegion:
    return CutRegion(
        start_time=str(ad.start_time),
        end_time=str(ad.end_time),
        label=ad.advert_for or "Ad",
    )


def _region_to_interval(region: CutRegion) -> Interval:
    return Interval(
        start=parse_time(region.start_time),
        end=parse_time(region.end_time),
        label=region.label,
    )


def _region_to_dict(region: CutRegion) -> dict[str, Any]:
    return {
        "start_time": parse_time(region.start_time),
        "end_time": parse_time(region.end_time),
        "label": region.label,
    }


# ── Pipeline ─────────────────────────────────────────────────────────────────


@dataclass
class PipelineResult:
    case_id: str
    iou_threshold: float
    use_acast: bool
    model: str | None = None
    provider: str | None = None
    predicted: list[dict[str, Any]] = field(default_factory=list)
    expected: list[dict[str, Any]] = field(default_factory=list)
    matched: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    duration_precision: float = 0.0
    duration_coverage: float = 0.0
    false_positives: list[dict[str, Any]] = field(default_factory=list)
    false_negatives: list[dict[str, Any]] = field(default_factory=list)
    audio_duration_s: float | None = None
    raw_ident_count: int | None = None
    unpaired_idents: int | None = None
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_seconds: float | None = None
    error: str | None = None


def _produce_cut_regions(
    case: EvalCase,
    use_acast: bool,
    model: ModelSpec | None,
    custom_prompt: str | None,
    result: PipelineResult,
) -> list[CutRegion]:
    """Reproduce the clipping pipeline for one case.

    Mirrors tasks.py: when use_acast is true the cuts are the Acast bracket
    spans only (the AI analysis-inside-brackets step is reporting-only and is
    not included). Otherwise the cuts are AI-detected ads."""
    if use_acast:
        audio_path = case.require_audio()
        idents, audio_duration = detect_idents(audio_path)
        pairs, unpaired = pair_idents(idents, audio_duration=audio_duration)
        result.audio_duration_s = audio_duration
        result.raw_ident_count = len(idents)
        result.unpaired_idents = unpaired
        return idents_to_cut_regions(pairs)

    if model is None:
        raise ValueError("A model is required when use_acast=false")

    transcription = case.load_transcription()
    provider = build_provider(model)
    report = AnalysisReport(provider=model.provider, model_name=model.model)
    ads = analyse_transcription(
        transcription,
        provider=provider,
        report=report,
        custom_instructions=custom_prompt,
    )
    result.cost_usd = report.cost_usd
    result.input_tokens = report.input_tokens
    result.output_tokens = report.output_tokens
    return [_ad_to_cut_region(ad) for ad in ads]


def run_case(
    case: EvalCase,
    *,
    use_acast: bool,
    model: ModelSpec | None = None,
    custom_prompt: str | None = None,
    iou_threshold: float = 0.5,
) -> PipelineResult:
    result = PipelineResult(
        case_id=case.case_id,
        iou_threshold=iou_threshold,
        use_acast=use_acast,
        model=model.label if model else None,
        provider=model.provider if model else ("acast" if use_acast else None),
        expected=[_region_to_dict(r) for r in case.expected],
    )

    started = time.monotonic()
    try:
        predicted_regions = _produce_cut_regions(case, use_acast, model, custom_prompt, result)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.duration_seconds = time.monotonic() - started
        return result
    result.duration_seconds = time.monotonic() - started

    pred_intervals = [_region_to_interval(r) for r in predicted_regions]
    exp_intervals = [_region_to_interval(r) for r in case.expected]

    match = match_intervals(pred_intervals, exp_intervals, iou_threshold=iou_threshold)
    counts = count_metrics(match, len(pred_intervals), len(exp_intervals))
    durations = duration_metrics(pred_intervals, exp_intervals)

    result.predicted = [_region_to_dict(r) for r in predicted_regions]
    result.matched = counts.matched
    result.precision = counts.precision
    result.recall = counts.recall
    result.f1 = counts.f1
    result.duration_precision = durations.precision
    result.duration_coverage = durations.coverage
    result.false_positives = [_region_to_dict(predicted_regions[i]) for i in match.false_positives]
    result.false_negatives = [_region_to_dict(case.expected[i]) for i in match.false_negatives]
    return result


def result_to_dict(result: PipelineResult) -> dict[str, Any]:
    return asdict(result)


# Re-export so callers can use a stable label constant
__all__ = [
    "ACAST_ADVERT_LABEL",
    "EvalCase",
    "PipelineResult",
    "list_cases",
    "load_case",
    "result_to_dict",
    "run_case",
]
