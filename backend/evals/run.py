from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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


@dataclass(frozen=True)
class RunConfig:
    name: str
    iou_threshold: float
    use_acast_default: bool
    models: list[ModelSpec]
    cases: list[CaseConfig]
    source_path: Path | None = None


_ALLOWED_RUN_KEYS = {"name", "iou_threshold", "use_acast", "models", "cases"}
_ALLOWED_MODEL_KEYS = {"spec", "provider", "model"}
_ALLOWED_CASE_KEYS = {"id", "podcast", "custom_prompt", "use_acast", "iou_threshold"}


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
    total_matched: int
    total_predicted: int
    total_expected: int
    precision: float
    recall: float
    f1: float
    total_cost_usd: float
    total_duration_s: float
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
            "models": [m.label for m in self.config.models],
            "cases": [
                {
                    "id": c.id,
                    "podcast": c.podcast,
                    "use_acast": c.use_acast,
                    "iou_threshold": c.iou_threshold,
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
                    "total_cost_usd": m.total_cost_usd,
                    "total_duration_s": m.total_duration_s,
                    "results": [result_to_dict(r) for r in m.results],
                }
                for m in self.per_model
            ],
            "acast_results": [result_to_dict(r) for r in self.acast_results],
        }


def _aggregate(results: list[PipelineResult]) -> tuple[int, int, int, float, float, float]:
    matched = sum(r.matched for r in results)
    predicted = sum(len(r.predicted) for r in results)
    expected = sum(len(r.expected) for r in results)
    precision = matched / predicted if predicted else (1.0 if expected == 0 else 0.0)
    recall = matched / expected if expected else (1.0 if predicted == 0 else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return matched, predicted, expected, precision, recall, f1


def execute_run(config: RunConfig) -> RunSummary:
    loaded_cases: dict[str, EvalCase] = {c.id: load_case(c.id) for c in config.cases}

    ai_cases = [c for c in config.cases if not c.use_acast]
    acast_cases = [c for c in config.cases if c.use_acast]

    # Acast results are independent of the AI model — run once and share.
    acast_results: list[PipelineResult] = []
    for case_cfg in acast_cases:
        iou = case_cfg.iou_threshold or config.iou_threshold
        acast_results.append(
            run_case(
                loaded_cases[case_cfg.id],
                use_acast=True,
                model=None,
                custom_prompt=None,
                iou_threshold=iou,
            )
        )

    per_model: list[ModelRunSummary] = []
    if config.models:
        for model_spec in config.models:
            ai_results: list[PipelineResult] = []
            for case_cfg in ai_cases:
                iou = case_cfg.iou_threshold or config.iou_threshold
                ai_results.append(
                    run_case(
                        loaded_cases[case_cfg.id],
                        use_acast=False,
                        model=model_spec,
                        custom_prompt=case_cfg.custom_prompt,
                        iou_threshold=iou,
                    )
                )
            combined = ai_results + acast_results
            matched, predicted, expected, p, r, f1 = _aggregate(combined)
            per_model.append(
                ModelRunSummary(
                    model=model_spec.label,
                    provider=model_spec.provider,
                    case_count=len(combined),
                    total_matched=matched,
                    total_predicted=predicted,
                    total_expected=expected,
                    precision=p,
                    recall=r,
                    f1=f1,
                    total_cost_usd=sum(res.cost_usd or 0.0 for res in combined),
                    total_duration_s=sum(res.duration_seconds or 0.0 for res in combined),
                    results=combined,
                )
            )
    else:
        # Acast-only run: still report aggregate under a single "no-model" summary
        matched, predicted, expected, p, r, f1 = _aggregate(acast_results)
        per_model.append(
            ModelRunSummary(
                model=None,
                provider="acast",
                case_count=len(acast_results),
                total_matched=matched,
                total_predicted=predicted,
                total_expected=expected,
                precision=p,
                recall=r,
                f1=f1,
                total_cost_usd=0.0,
                total_duration_s=sum(res.duration_seconds or 0.0 for res in acast_results),
                results=acast_results,
            )
        )

    return RunSummary(config=config, per_model=per_model, acast_results=acast_results)
