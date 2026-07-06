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

from .acoustic import AcousticMetrics, acoustic_metrics
from .metrics import (
    BoundaryMetrics,
    Interval,
    boundary_metrics,
    cluster_regions,
    duration_metrics,
    match_intervals,
    name_similarity,
    parse_time,
)
from .providers import ModelSpec, build_provider

FIXTURES_DIR = Path(__file__).parent / "fixtures"
AUDIO_CANDIDATES = ("audio.mp3", "audio.wav", "audio.m4a", "audio.ogg")


def _load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


@dataclass(frozen=True)
class ExpectedRegion:
    """One ground-truth entry in expected.json. `optional=True` means the entry
    is informational: the model is neither rewarded for matching it (no TP) nor
    penalised for missing it (no FN) and a predicted region that overlaps an
    optional ground truth is absorbed (no FP). Useful for ads with ambiguous
    boundaries (host-read self-promo, etc.)."""

    start_time: float
    end_time: float
    label: str
    optional: bool = False


@dataclass
class EvalCase:
    case_id: str
    path: Path
    meta: dict[str, Any]
    transcription_path: Path | None
    audio_path: Path | None
    expected: list[ExpectedRegion]

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
    expected = [
        ExpectedRegion(
            start_time=parse_time(r["start_time"]),
            end_time=parse_time(r["end_time"]),
            label=r.get("label", ""),
            optional=bool(r.get("optional", False)),
        )
        for r in _load_json(expected_path)
    ]

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
class NameMatch:
    predicted: str
    expected: str
    similarity: float
    optional: bool = False


@dataclass
class PipelineResult:
    case_id: str
    iou_threshold: float
    use_acast: bool
    break_cluster_gap_s: float = 5.0
    model: str | None = None
    provider: str | None = None
    predicted: list[dict[str, Any]] = field(default_factory=list)
    expected: list[dict[str, Any]] = field(default_factory=list)
    # Ad-level metrics — granular per-advert scoring
    matched: int = 0
    expected_required_count: int = 0
    expected_optional_count: int = 0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    duration_precision: float = 0.0
    duration_coverage: float = 0.0
    false_positives: list[dict[str, Any]] = field(default_factory=list)
    false_negatives: list[dict[str, Any]] = field(default_factory=list)
    absorbed: list[dict[str, Any]] = field(default_factory=list)
    unmatched_optional: list[dict[str, Any]] = field(default_factory=list)
    name_matches: list[NameMatch] = field(default_factory=list)
    name_similarity_mean: float = 0.0
    # Boundary deltas across required matches (predicted - expected, seconds)
    boundary: BoundaryMetrics | None = None
    # Acoustic kept-seam loudness across required matches (dBFS; lower = cleaner)
    acoustic: AcousticMetrics | None = None
    # Break-level metrics — touching ads clustered into ad breaks
    predicted_breaks: list[dict[str, Any]] = field(default_factory=list)
    expected_breaks: list[dict[str, Any]] = field(default_factory=list)
    break_matched: int = 0
    break_expected_required_count: int = 0
    break_expected_optional_count: int = 0
    break_precision: float = 0.0
    break_recall: float = 0.0
    break_f1: float = 0.0
    break_duration_precision: float = 0.0
    break_duration_coverage: float = 0.0
    break_false_positives: list[dict[str, Any]] = field(default_factory=list)
    break_false_negatives: list[dict[str, Any]] = field(default_factory=list)
    break_absorbed: list[dict[str, Any]] = field(default_factory=list)
    break_unmatched_optional: list[dict[str, Any]] = field(default_factory=list)
    break_boundary: BoundaryMetrics | None = None
    # Pipeline-level diagnostics
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


def _interval_to_dict(iv: Interval) -> dict[str, Any]:
    return {
        "start_time": iv.start,
        "end_time": iv.end,
        "label": iv.label,
        "optional": iv.optional,
    }


def _expected_to_dict(e: ExpectedRegion) -> dict[str, Any]:
    return {
        "start_time": e.start_time,
        "end_time": e.end_time,
        "label": e.label,
        "optional": e.optional,
    }


def _predicted_to_dict(region: CutRegion) -> dict[str, Any]:
    return {
        "start_time": parse_time(region.start_time),
        "end_time": parse_time(region.end_time),
        "label": region.label,
    }


@dataclass
class _TieredScores:
    """Result of applying tiered scoring to a match result. Optional matches
    are absorbed (no TP, no FP) and optional non-matches are ignored (no FN)."""

    matched_required: list[int]  # match indices into the `matches` list
    matched_optional: list[int]
    fp_indices: list[int]  # predicted indices with no match
    fn_indices: list[int]  # expected indices that are required and unmatched
    unmatched_optional_indices: list[int]
    required_expected_count: int
    optional_expected_count: int
    precision: float
    recall: float
    f1: float


def _tiered_score(
    match_result,
    predicted: list[Interval],
    expected: list[Interval],
) -> _TieredScores:
    matched_required: list[int] = []
    matched_optional: list[int] = []
    for i, m in enumerate(match_result.matches):
        if expected[m.expected_index].optional:
            matched_optional.append(i)
        else:
            matched_required.append(i)

    fn_required = [i for i in match_result.false_negatives if not expected[i].optional]
    unmatched_opt = [i for i in match_result.false_negatives if expected[i].optional]

    tp = len(matched_required)
    fp = len(match_result.false_positives)
    required_total = sum(1 for e in expected if not e.optional)
    optional_total = sum(1 for e in expected if e.optional)

    # Precision: TP / (TP + FP). Predictions absorbed by optional expecteds are
    # excluded from the denominator.
    effective_pred_total = tp + fp
    if effective_pred_total == 0:
        precision = 1.0 if required_total == 0 else 0.0
    else:
        precision = tp / effective_pred_total

    if required_total == 0:
        recall = 1.0 if effective_pred_total == 0 else 0.0
    else:
        recall = tp / required_total

    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return _TieredScores(
        matched_required=matched_required,
        matched_optional=matched_optional,
        fp_indices=list(match_result.false_positives),
        fn_indices=fn_required,
        unmatched_optional_indices=unmatched_opt,
        required_expected_count=required_total,
        optional_expected_count=optional_total,
        precision=precision,
        recall=recall,
        f1=f1,
    )


def run_case(
    case: EvalCase,
    *,
    use_acast: bool,
    model: ModelSpec | None = None,
    custom_prompt: str | None = None,
    iou_threshold: float = 0.5,
    break_cluster_gap_s: float = 5.0,
) -> PipelineResult:
    result = PipelineResult(
        case_id=case.case_id,
        iou_threshold=iou_threshold,
        use_acast=use_acast,
        break_cluster_gap_s=break_cluster_gap_s,
        model=model.label if model else None,
        provider=model.provider if model else ("acast" if use_acast else None),
        expected=[_expected_to_dict(e) for e in case.expected],
    )

    started = time.monotonic()
    try:
        predicted_regions = _produce_cut_regions(case, use_acast, model, custom_prompt, result)
        pred_intervals = [
            Interval(
                start=parse_time(r.start_time),
                end=parse_time(r.end_time),
                label=r.label,
            )
            for r in predicted_regions
        ]
    except Exception as exc:
        raw = [
            {"start_time": r.start_time, "end_time": r.end_time, "label": r.label}
            for r in locals().get("predicted_regions", [])
        ]
        result.error = f"{type(exc).__name__}: {exc} | raw={raw}"
        result.duration_seconds = time.monotonic() - started
        return result
    result.duration_seconds = time.monotonic() - started
    exp_intervals = [
        Interval(
            start=e.start_time,
            end=e.end_time,
            label=e.label,
            optional=e.optional,
        )
        for e in case.expected
    ]

    # ── Ad-level: individual adverts ─────────────────────────────────────────
    match = match_intervals(pred_intervals, exp_intervals, iou_threshold=iou_threshold)
    scores = _tiered_score(match, pred_intervals, exp_intervals)
    durations = duration_metrics(
        # Duration metrics ignore optional regions on the expected side so that
        # over-cutting into a non-required region isn't penalised.
        pred_intervals,
        [iv for iv in exp_intervals if not iv.optional],
    )

    name_scores: list[NameMatch] = []
    for m in match.matches:
        pred_label = pred_intervals[m.predicted_index].label
        exp_label = exp_intervals[m.expected_index].label
        name_scores.append(
            NameMatch(
                predicted=pred_label,
                expected=exp_label,
                similarity=name_similarity(pred_label, exp_label),
                optional=exp_intervals[m.expected_index].optional,
            )
        )

    result.predicted = [_predicted_to_dict(r) for r in predicted_regions]
    result.matched = len(scores.matched_required)
    result.expected_required_count = scores.required_expected_count
    result.expected_optional_count = scores.optional_expected_count
    result.precision = scores.precision
    result.recall = scores.recall
    result.f1 = scores.f1
    result.duration_precision = durations.precision
    result.duration_coverage = durations.coverage
    result.false_positives = [_predicted_to_dict(predicted_regions[i]) for i in scores.fp_indices]
    result.false_negatives = [_expected_to_dict(case.expected[i]) for i in scores.fn_indices]
    # Absorbed: predictions that matched an optional expected
    absorbed_pred_indices = [match.matches[i].predicted_index for i in scores.matched_optional]
    result.absorbed = [_predicted_to_dict(predicted_regions[i]) for i in absorbed_pred_indices]
    result.unmatched_optional = [
        _expected_to_dict(case.expected[i]) for i in scores.unmatched_optional_indices
    ]
    result.name_matches = name_scores
    result.name_similarity_mean = (
        sum(n.similarity for n in name_scores) / len(name_scores) if name_scores else 0.0
    )
    # Boundary deltas — only over required matches (optional absorbs aren't
    # held to a timing standard).
    ad_pairs = [
        (
            pred_intervals[match.matches[i].predicted_index],
            exp_intervals[match.matches[i].expected_index],
        )
        for i in scores.matched_required
    ]
    result.boundary = boundary_metrics(ad_pairs)
    result.acoustic = acoustic_metrics(case.audio_path, [p for p, _ in ad_pairs])

    # ── Break-level: touching ads clustered into ad breaks ───────────────────
    pred_breaks = cluster_regions(pred_intervals, break_cluster_gap_s)
    exp_breaks = cluster_regions(exp_intervals, break_cluster_gap_s)

    break_match = match_intervals(pred_breaks, exp_breaks, iou_threshold=iou_threshold)
    break_scores = _tiered_score(break_match, pred_breaks, exp_breaks)
    break_durations = duration_metrics(
        pred_breaks,
        [iv for iv in exp_breaks if not iv.optional],
    )

    result.predicted_breaks = [_interval_to_dict(iv) for iv in pred_breaks]
    result.expected_breaks = [_interval_to_dict(iv) for iv in exp_breaks]
    result.break_matched = len(break_scores.matched_required)
    result.break_expected_required_count = break_scores.required_expected_count
    result.break_expected_optional_count = break_scores.optional_expected_count
    result.break_precision = break_scores.precision
    result.break_recall = break_scores.recall
    result.break_f1 = break_scores.f1
    result.break_duration_precision = break_durations.precision
    result.break_duration_coverage = break_durations.coverage
    result.break_false_positives = [
        _interval_to_dict(pred_breaks[i]) for i in break_scores.fp_indices
    ]
    result.break_false_negatives = [
        _interval_to_dict(exp_breaks[i]) for i in break_scores.fn_indices
    ]
    break_absorbed_pred = [
        break_match.matches[i].predicted_index for i in break_scores.matched_optional
    ]
    result.break_absorbed = [_interval_to_dict(pred_breaks[i]) for i in break_absorbed_pred]
    result.break_unmatched_optional = [
        _interval_to_dict(exp_breaks[i]) for i in break_scores.unmatched_optional_indices
    ]
    break_pairs = [
        (
            pred_breaks[break_match.matches[i].predicted_index],
            exp_breaks[break_match.matches[i].expected_index],
        )
        for i in break_scores.matched_required
    ]
    result.break_boundary = boundary_metrics(break_pairs)

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
