from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.models import (
    AIModel,
    AnalysisReport,
    PodcastEpisodeAdvert,
    Provider,
    TranscriptionSegment,
)
from app.services.analysis import analyse_transcription
from app.services.providers import GeminiProvider

from .metrics import (
    Interval,
    count_metrics,
    duration_metrics,
    match_intervals,
    parse_time,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "analysis"


@dataclass
class AnalysisCase:
    case_id: str
    path: Path
    meta: dict[str, Any]
    transcription: list[TranscriptionSegment]
    expected: list[PodcastEpisodeAdvert]

    @property
    def custom_prompt(self) -> str | None:
        return self.meta.get("custom_prompt") or None


@dataclass
class AnalysisCaseResult:
    case_id: str
    iou_threshold: float
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
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_seconds: float | None = None
    error: str | None = None


def _load_json(path: Path) -> Any:
    with path.open() as f:
        return json.load(f)


def list_cases() -> list[str]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(p.name for p in FIXTURES_DIR.iterdir() if p.is_dir())


def load_case(case_id: str) -> AnalysisCase:
    case_dir = FIXTURES_DIR / case_id
    if not case_dir.exists():
        raise FileNotFoundError(f"Analysis case not found: {case_dir}")

    meta = _load_json(case_dir / "meta.json") if (case_dir / "meta.json").exists() else {}
    transcription_raw = _load_json(case_dir / "transcription.json")
    expected_raw = _load_json(case_dir / "expected_ads.json")

    return AnalysisCase(
        case_id=case_id,
        path=case_dir,
        meta=meta,
        transcription=[TranscriptionSegment(**s) for s in transcription_raw],
        expected=[PodcastEpisodeAdvert(**a) for a in expected_raw],
    )


def _ad_to_interval(ad: PodcastEpisodeAdvert) -> Interval:
    return Interval(
        start=parse_time(ad.start_time),
        end=parse_time(ad.end_time),
        label=ad.advert_for,
    )


def _ad_to_dict(ad: PodcastEpisodeAdvert) -> dict[str, Any]:
    return {
        "start_time": parse_time(ad.start_time),
        "end_time": parse_time(ad.end_time),
        "advert_for": ad.advert_for,
    }


def _build_provider(model_name: str, api_key: str) -> GeminiProvider:
    model_config = AIModel(
        name=model_name,
        provider=Provider.GEMINI.value,
        is_preset=False,
    )
    return GeminiProvider(api_key=api_key, model_config=model_config)


def run_case(
    case: AnalysisCase,
    model_name: str,
    api_key: str,
    iou_threshold: float = 0.5,
) -> AnalysisCaseResult:
    provider = _build_provider(model_name, api_key)
    report = AnalysisReport(provider=Provider.GEMINI.value, model_name=model_name)

    started = time.monotonic()
    try:
        predicted = analyse_transcription(
            case.transcription,
            provider=provider,
            report=report,
            custom_instructions=case.custom_prompt,
        )
    except Exception as exc:
        return AnalysisCaseResult(
            case_id=case.case_id,
            iou_threshold=iou_threshold,
            expected=[_ad_to_dict(a) for a in case.expected],
            error=f"{type(exc).__name__}: {exc}",
            duration_seconds=time.monotonic() - started,
        )
    elapsed = time.monotonic() - started

    pred_intervals = [_ad_to_interval(a) for a in predicted]
    exp_intervals = [_ad_to_interval(a) for a in case.expected]

    match = match_intervals(pred_intervals, exp_intervals, iou_threshold=iou_threshold)
    counts = count_metrics(match, len(pred_intervals), len(exp_intervals))
    durations = duration_metrics(pred_intervals, exp_intervals)

    return AnalysisCaseResult(
        case_id=case.case_id,
        iou_threshold=iou_threshold,
        predicted=[_ad_to_dict(a) for a in predicted],
        expected=[_ad_to_dict(a) for a in case.expected],
        matched=counts.matched,
        precision=counts.precision,
        recall=counts.recall,
        f1=counts.f1,
        duration_precision=durations.precision,
        duration_coverage=durations.coverage,
        false_positives=[_ad_to_dict(predicted[i]) for i in match.false_positives],
        false_negatives=[_ad_to_dict(case.expected[i]) for i in match.false_negatives],
        cost_usd=report.cost_usd,
        input_tokens=report.input_tokens,
        output_tokens=report.output_tokens,
        duration_seconds=elapsed,
    )


@dataclass
class AnalysisRunSummary:
    model: str
    iou_threshold: float
    case_count: int
    total_matched: int
    total_predicted: int
    total_expected: int
    precision: float
    recall: float
    f1: float
    total_cost_usd: float
    total_duration_s: float
    results: list[AnalysisCaseResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "iou_threshold": self.iou_threshold,
            "case_count": self.case_count,
            "total_matched": self.total_matched,
            "total_predicted": self.total_predicted,
            "total_expected": self.total_expected,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "total_cost_usd": self.total_cost_usd,
            "total_duration_s": self.total_duration_s,
            "results": [asdict(r) for r in self.results],
        }


def run(
    case_ids: list[str] | None = None,
    model_name: str = "gemini-2.5-flash",
    api_key: str | None = None,
    iou_threshold: float = 0.5,
) -> AnalysisRunSummary:
    api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is required for the analysis eval. "
            "Set it in the environment or pass --api-key."
        )

    cases = case_ids or list_cases()
    if not cases:
        raise RuntimeError(
            f"No analysis fixtures found in {FIXTURES_DIR}. See evals/README.md for fixture layout."
        )

    results = [run_case(load_case(c), model_name, api_key, iou_threshold) for c in cases]

    matched = sum(r.matched for r in results)
    predicted = sum(len(r.predicted) for r in results)
    expected = sum(len(r.expected) for r in results)
    precision = matched / predicted if predicted else (1.0 if expected == 0 else 0.0)
    recall = matched / expected if expected else (1.0 if predicted == 0 else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return AnalysisRunSummary(
        model=model_name,
        iou_threshold=iou_threshold,
        case_count=len(results),
        total_matched=matched,
        total_predicted=predicted,
        total_expected=expected,
        precision=precision,
        recall=recall,
        f1=f1,
        total_cost_usd=sum(r.cost_usd or 0.0 for r in results),
        total_duration_s=sum(r.duration_seconds or 0.0 for r in results),
        results=results,
    )
