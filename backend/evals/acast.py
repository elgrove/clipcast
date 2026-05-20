from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.models import CutRegion
from app.services.acast import detect_idents, idents_to_cut_regions, pair_idents

from .metrics import (
    Interval,
    count_metrics,
    duration_metrics,
    match_intervals,
    parse_time,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "acast"
AUDIO_CANDIDATES = ("audio.mp3", "audio.wav", "audio.m4a", "audio.ogg")


@dataclass
class AcastCase:
    case_id: str
    path: Path
    audio_path: Path
    meta: dict[str, Any]
    expected: list[CutRegion]


@dataclass
class AcastCaseResult:
    case_id: str
    iou_threshold: float
    audio_duration_s: float = 0.0
    raw_ident_count: int = 0
    unpaired_idents: int = 0
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
    duration_seconds: float | None = None
    error: str | None = None


def _load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def list_cases() -> list[str]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(p.name for p in FIXTURES_DIR.iterdir() if p.is_dir())


def _find_audio(case_dir: Path) -> Path:
    for name in AUDIO_CANDIDATES:
        candidate = case_dir / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"No audio file in {case_dir}. Expected one of: {', '.join(AUDIO_CANDIDATES)}"
    )


def load_case(case_id: str) -> AcastCase:
    case_dir = FIXTURES_DIR / case_id
    if not case_dir.exists():
        raise FileNotFoundError(f"Acast case not found: {case_dir}")

    meta = _load_json(case_dir / "meta.json") if (case_dir / "meta.json").exists() else {}
    expected_raw = _load_json(case_dir / "expected_regions.json")
    return AcastCase(
        case_id=case_id,
        path=case_dir,
        audio_path=_find_audio(case_dir),
        meta=meta,
        expected=[CutRegion(**r) for r in expected_raw],
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


def run_case(case: AcastCase, iou_threshold: float = 0.5) -> AcastCaseResult:
    started = time.monotonic()
    try:
        idents, audio_duration = detect_idents(case.audio_path)
        pairs, unpaired = pair_idents(idents, audio_duration=audio_duration)
        predicted = idents_to_cut_regions(pairs)
    except Exception as exc:
        return AcastCaseResult(
            case_id=case.case_id,
            iou_threshold=iou_threshold,
            expected=[_region_to_dict(r) for r in case.expected],
            error=f"{type(exc).__name__}: {exc}",
            duration_seconds=time.monotonic() - started,
        )
    elapsed = time.monotonic() - started

    pred_intervals = [_region_to_interval(r) for r in predicted]
    exp_intervals = [_region_to_interval(r) for r in case.expected]

    match = match_intervals(pred_intervals, exp_intervals, iou_threshold=iou_threshold)
    counts = count_metrics(match, len(pred_intervals), len(exp_intervals))
    durations = duration_metrics(pred_intervals, exp_intervals)

    return AcastCaseResult(
        case_id=case.case_id,
        iou_threshold=iou_threshold,
        audio_duration_s=audio_duration,
        raw_ident_count=len(idents),
        unpaired_idents=unpaired,
        predicted=[_region_to_dict(r) for r in predicted],
        expected=[_region_to_dict(r) for r in case.expected],
        matched=counts.matched,
        precision=counts.precision,
        recall=counts.recall,
        f1=counts.f1,
        duration_precision=durations.precision,
        duration_coverage=durations.coverage,
        false_positives=[_region_to_dict(predicted[i]) for i in match.false_positives],
        false_negatives=[_region_to_dict(case.expected[i]) for i in match.false_negatives],
        duration_seconds=elapsed,
    )


@dataclass
class AcastRunSummary:
    iou_threshold: float
    case_count: int
    total_matched: int
    total_predicted: int
    total_expected: int
    precision: float
    recall: float
    f1: float
    total_duration_s: float
    results: list[AcastCaseResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "iou_threshold": self.iou_threshold,
            "case_count": self.case_count,
            "total_matched": self.total_matched,
            "total_predicted": self.total_predicted,
            "total_expected": self.total_expected,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "total_duration_s": self.total_duration_s,
            "results": [asdict(r) for r in self.results],
        }


def run(case_ids: list[str] | None = None, iou_threshold: float = 0.5) -> AcastRunSummary:
    cases = case_ids or list_cases()
    if not cases:
        raise RuntimeError(
            f"No acast fixtures found in {FIXTURES_DIR}. See evals/README.md for fixture layout."
        )

    results = [run_case(load_case(c), iou_threshold) for c in cases]

    matched = sum(r.matched for r in results)
    predicted = sum(len(r.predicted) for r in results)
    expected = sum(len(r.expected) for r in results)
    precision = matched / predicted if predicted else (1.0 if expected == 0 else 0.0)
    recall = matched / expected if expected else (1.0 if predicted == 0 else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return AcastRunSummary(
        iou_threshold=iou_threshold,
        case_count=len(results),
        total_matched=matched,
        total_predicted=predicted,
        total_expected=expected,
        precision=precision,
        recall=recall,
        f1=f1,
        total_duration_s=sum(r.duration_seconds or 0.0 for r in results),
        results=results,
    )
