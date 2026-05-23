from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .metrics import BoundaryMetrics, boundary_metrics_from_deltas
from .pipeline import EvalCase, PipelineResult, load_case, result_to_dict, run_case
from .providers import ModelSpec, parse_model_spec

RUNS_DIR = Path(__file__).parent / "runs"


class RunConfigError(ValueError):
    pass


# ── Config schema ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CaseConfig:
    id: str
    podcast: str | None
    custom_prompt: str | None
    use_acast: bool
    iou_threshold: float | None
    break_cluster_gap_s: float | None


@dataclass(frozen=True)
class RunConfig:
    name: str
    iou_threshold: float
    use_acast_default: bool
    break_cluster_gap_s: float
    models: list[ModelSpec]
    cases: list[CaseConfig]
    source_path: Path | None = None


_ALLOWED_RUN_KEYS = {
    "name",
    "iou_threshold",
    "use_acast",
    "break_cluster_gap_s",
    "models",
    "cases",
}
_ALLOWED_MODEL_KEYS = {"spec", "provider", "model"}
_ALLOWED_CASE_KEYS = {
    "id",
    "podcast",
    "custom_prompt",
    "use_acast",
    "iou_threshold",
    "break_cluster_gap_s",
}


def _coerce_bool(value: Any, key: str) -> bool:
    if not isinstance(value, bool):
        raise RunConfigError(f"{key} must be a boolean, got {type(value).__name__}")
    return value


def _coerce_float(value: Any, key: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise RunConfigError(f"{key} must be a number, got {type(value).__name__}")
    return float(value)


def _coerce_str(value: Any, key: str) -> str:
    if not isinstance(value, str):
        raise RunConfigError(f"{key} must be a string, got {type(value).__name__}")
    return value


def _reject_unknown(data: dict[str, Any], allowed: set[str], context: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise RunConfigError(
            f"Unknown {context} keys: {sorted(unknown)}. Allowed: {sorted(allowed)}"
        )


def _parse_model(entry: Any, idx: int) -> ModelSpec:
    if not isinstance(entry, dict):
        raise RunConfigError(f"[[models]][{idx}] must be a table")
    _reject_unknown(entry, _ALLOWED_MODEL_KEYS, f"[[models]][{idx}]")
    if "spec" in entry:
        return parse_model_spec(_coerce_str(entry["spec"], f"models[{idx}].spec"))
    provider = entry.get("provider")
    model = entry.get("model")
    if not provider or not model:
        raise RunConfigError(f"[[models]][{idx}] must set 'spec' or both 'provider' and 'model'")
    return parse_model_spec(f"{_coerce_str(provider, 'provider')}:{_coerce_str(model, 'model')}")


def _parse_case(entry: Any, idx: int, default_use_acast: bool) -> CaseConfig:
    if not isinstance(entry, dict):
        raise RunConfigError(f"[[cases]][{idx}] must be a table")
    _reject_unknown(entry, _ALLOWED_CASE_KEYS, f"[[cases]][{idx}]")
    if "id" not in entry:
        raise RunConfigError(f"[[cases]][{idx}] is missing required 'id'")

    return CaseConfig(
        id=_coerce_str(entry["id"], f"cases[{idx}].id"),
        podcast=_coerce_str(entry["podcast"], f"cases[{idx}].podcast")
        if "podcast" in entry
        else None,
        custom_prompt=_coerce_str(entry["custom_prompt"], f"cases[{idx}].custom_prompt")
        if "custom_prompt" in entry
        else None,
        use_acast=_coerce_bool(entry["use_acast"], f"cases[{idx}].use_acast")
        if "use_acast" in entry
        else default_use_acast,
        iou_threshold=_coerce_float(entry["iou_threshold"], f"cases[{idx}].iou_threshold")
        if "iou_threshold" in entry
        else None,
        break_cluster_gap_s=_coerce_float(
            entry["break_cluster_gap_s"], f"cases[{idx}].break_cluster_gap_s"
        )
        if "break_cluster_gap_s" in entry
        else None,
    )


def load_run_config(path: str | Path) -> RunConfig:
    path = Path(path)
    if not path.exists():
        raise RunConfigError(f"Run config not found: {path}")

    with path.open("rb") as f:
        data = tomllib.load(f)

    run_section = data.get("run", {})
    if not isinstance(run_section, dict):
        raise RunConfigError("[run] must be a table")
    _reject_unknown(run_section, _ALLOWED_RUN_KEYS - {"models", "cases"}, "[run]")

    name = _coerce_str(run_section.get("name", path.stem), "run.name")
    iou_threshold = _coerce_float(run_section.get("iou_threshold", 0.5), "run.iou_threshold")
    use_acast_default = _coerce_bool(run_section.get("use_acast", False), "run.use_acast")
    break_cluster_gap_s = _coerce_float(
        run_section.get("break_cluster_gap_s", 5.0), "run.break_cluster_gap_s"
    )

    raw_models = data.get("models", [])
    if not isinstance(raw_models, list):
        raise RunConfigError("[[models]] must be an array of tables")
    models = [_parse_model(entry, i) for i, entry in enumerate(raw_models)]

    raw_cases = data.get("cases", [])
    if not isinstance(raw_cases, list):
        raise RunConfigError("[[cases]] must be an array of tables")
    cases = [_parse_case(entry, i, use_acast_default) for i, entry in enumerate(raw_cases)]

    if not cases:
        raise RunConfigError(f"Run config {path} declares no [[cases]]")

    needs_models = any(not c.use_acast for c in cases)
    if needs_models and not models:
        raise RunConfigError("At least one case has use_acast=false but no [[models]] are declared")

    return RunConfig(
        name=name,
        iou_threshold=iou_threshold,
        use_acast_default=use_acast_default,
        break_cluster_gap_s=break_cluster_gap_s,
        models=models,
        cases=cases,
        source_path=path,
    )


def list_run_configs() -> list[Path]:
    if not RUNS_DIR.exists():
        return []
    return sorted(p for p in RUNS_DIR.iterdir() if p.suffix == ".toml")


# ── Execution ────────────────────────────────────────────────────────────────


@dataclass
class ModelRunSummary:
    model: str | None
    provider: str | None
    case_count: int
    # Ad-level
    total_matched: int
    total_predicted: int
    total_expected: int
    precision: float
    recall: float
    f1: float
    name_similarity_mean: float
    # Break-level
    break_total_matched: int
    break_total_predicted: int
    break_total_expected: int
    break_precision: float
    break_recall: float
    break_f1: float
    # Boundary drift (aggregated across required matches in all cases)
    boundary: BoundaryMetrics | None = None
    break_boundary: BoundaryMetrics | None = None
    # Cost / time
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_duration_s: float = 0.0
    results: list[PipelineResult] = field(default_factory=list)


@dataclass
class RunSummary:
    config: RunConfig
    per_model: list[ModelRunSummary]
    acast_results: list[PipelineResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.config.name,
            "iou_threshold": self.config.iou_threshold,
            "use_acast_default": self.config.use_acast_default,
            "break_cluster_gap_s": self.config.break_cluster_gap_s,
            "models": [m.label for m in self.config.models],
            "cases": [
                {
                    "id": c.id,
                    "podcast": c.podcast,
                    "use_acast": c.use_acast,
                    "iou_threshold": c.iou_threshold,
                    "break_cluster_gap_s": c.break_cluster_gap_s,
                }
                for c in self.config.cases
            ],
            "per_model": [
                {
                    "model": m.model,
                    "provider": m.provider,
                    "case_count": m.case_count,
                    "total_matched": m.total_matched,
                    "total_predicted": m.total_predicted,
                    "total_expected": m.total_expected,
                    "precision": m.precision,
                    "recall": m.recall,
                    "f1": m.f1,
                    "name_similarity_mean": m.name_similarity_mean,
                    "break_total_matched": m.break_total_matched,
                    "break_total_predicted": m.break_total_predicted,
                    "break_total_expected": m.break_total_expected,
                    "break_precision": m.break_precision,
                    "break_recall": m.break_recall,
                    "break_f1": m.break_f1,
                    "boundary": asdict(m.boundary) if m.boundary else None,
                    "break_boundary": asdict(m.break_boundary) if m.break_boundary else None,
                    "total_cost_usd": m.total_cost_usd,
                    "total_input_tokens": m.total_input_tokens,
                    "total_output_tokens": m.total_output_tokens,
                    "total_duration_s": m.total_duration_s,
                    "results": [result_to_dict(r) for r in m.results],
                }
                for m in self.per_model
            ],
            "acast_results": [result_to_dict(r) for r in self.acast_results],
        }


def _aggregate(
    results: list[PipelineResult], *, level: str
) -> tuple[int, int, int, float, float, float]:
    """Tiered micro-average. `matched` = required-only TP. `predicted` and
    `expected` totals are the effective values: absorbed predictions are
    excluded from the predicted denominator; optional expecteds are excluded
    from the expected denominator."""
    if level == "ad":
        matched = sum(r.matched for r in results)
        # Effective predicted = TP + FP (absorbed-by-optional excluded)
        predicted = sum(r.matched + len(r.false_positives) for r in results)
        # Effective expected = required only
        expected = sum(r.expected_required_count for r in results)
    elif level == "break":
        matched = sum(r.break_matched for r in results)
        predicted = sum(r.break_matched + len(r.break_false_positives) for r in results)
        expected = sum(r.break_expected_required_count for r in results)
    else:
        raise ValueError(f"Unknown aggregation level: {level}")
    precision = matched / predicted if predicted else (1.0 if expected == 0 else 0.0)
    recall = matched / expected if expected else (1.0 if predicted == 0 else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return matched, predicted, expected, precision, recall, f1


def _mean_name_similarity(results: list[PipelineResult]) -> float:
    total_matches = 0
    total = 0.0
    for r in results:
        for nm in r.name_matches:
            total += nm.similarity
            total_matches += 1
    return total / total_matches if total_matches else 0.0


def _aggregate_boundary(results: list[PipelineResult], attr: str) -> BoundaryMetrics:
    starts: list[float] = []
    ends: list[float] = []
    for r in results:
        b: BoundaryMetrics | None = getattr(r, attr)
        if b is None or b.count == 0:
            continue
        starts.extend(b.start_deltas)
        ends.extend(b.end_deltas)
    return boundary_metrics_from_deltas(starts, ends)


def execute_run(config: RunConfig) -> RunSummary:
    loaded_cases: dict[str, EvalCase] = {c.id: load_case(c.id) for c in config.cases}

    ai_cases = [c for c in config.cases if not c.use_acast]
    acast_cases = [c for c in config.cases if c.use_acast]

    # Acast results are independent of the AI model — run once and share.
    acast_results: list[PipelineResult] = []
    for case_cfg in acast_cases:
        iou = case_cfg.iou_threshold or config.iou_threshold
        gap = (
            case_cfg.break_cluster_gap_s
            if case_cfg.break_cluster_gap_s is not None
            else config.break_cluster_gap_s
        )
        acast_results.append(
            run_case(
                loaded_cases[case_cfg.id],
                use_acast=True,
                model=None,
                custom_prompt=None,
                iou_threshold=iou,
                break_cluster_gap_s=gap,
            )
        )

    per_model: list[ModelRunSummary] = []
    if config.models:
        for model_spec in config.models:
            ai_results: list[PipelineResult] = []
            for case_cfg in ai_cases:
                iou = case_cfg.iou_threshold or config.iou_threshold
                gap = (
                    case_cfg.break_cluster_gap_s
                    if case_cfg.break_cluster_gap_s is not None
                    else config.break_cluster_gap_s
                )
                ai_results.append(
                    run_case(
                        loaded_cases[case_cfg.id],
                        use_acast=False,
                        model=model_spec,
                        custom_prompt=case_cfg.custom_prompt,
                        iou_threshold=iou,
                        break_cluster_gap_s=gap,
                    )
                )
            combined = ai_results + acast_results
            ad_matched, ad_pred, ad_exp, ad_p, ad_r, ad_f1 = _aggregate(combined, level="ad")
            br_matched, br_pred, br_exp, br_p, br_r, br_f1 = _aggregate(combined, level="break")
            per_model.append(
                ModelRunSummary(
                    model=model_spec.label,
                    provider=model_spec.provider,
                    case_count=len(combined),
                    total_matched=ad_matched,
                    total_predicted=ad_pred,
                    total_expected=ad_exp,
                    precision=ad_p,
                    recall=ad_r,
                    f1=ad_f1,
                    name_similarity_mean=_mean_name_similarity(combined),
                    break_total_matched=br_matched,
                    break_total_predicted=br_pred,
                    break_total_expected=br_exp,
                    break_precision=br_p,
                    break_recall=br_r,
                    break_f1=br_f1,
                    boundary=_aggregate_boundary(combined, "boundary"),
                    break_boundary=_aggregate_boundary(combined, "break_boundary"),
                    total_cost_usd=sum(res.cost_usd or 0.0 for res in combined),
                    total_input_tokens=sum(res.input_tokens or 0 for res in combined),
                    total_output_tokens=sum(res.output_tokens or 0 for res in combined),
                    total_duration_s=sum(res.duration_seconds or 0.0 for res in combined),
                    results=combined,
                )
            )
    else:
        # Acast-only run: still report aggregate under a single "no-model" summary
        ad_matched, ad_pred, ad_exp, ad_p, ad_r, ad_f1 = _aggregate(acast_results, level="ad")
        br_matched, br_pred, br_exp, br_p, br_r, br_f1 = _aggregate(acast_results, level="break")
        per_model.append(
            ModelRunSummary(
                model=None,
                provider="acast",
                case_count=len(acast_results),
                total_matched=ad_matched,
                total_predicted=ad_pred,
                total_expected=ad_exp,
                precision=ad_p,
                recall=ad_r,
                f1=ad_f1,
                name_similarity_mean=_mean_name_similarity(acast_results),
                break_total_matched=br_matched,
                break_total_predicted=br_pred,
                break_total_expected=br_exp,
                break_precision=br_p,
                break_recall=br_r,
                break_f1=br_f1,
                boundary=_aggregate_boundary(acast_results, "boundary"),
                break_boundary=_aggregate_boundary(acast_results, "break_boundary"),
                total_cost_usd=0.0,
                total_input_tokens=0,
                total_output_tokens=0,
                total_duration_s=sum(res.duration_seconds or 0.0 for res in acast_results),
                results=acast_results,
            )
        )

    return RunSummary(config=config, per_model=per_model, acast_results=acast_results)
