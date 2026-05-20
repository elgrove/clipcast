from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from . import pipeline, run
from .providers import ProviderError

ENV_FILE = Path(__file__).parent.parent / ".env"
REPORTS_DIR = Path(__file__).parent / "reports"


def _load_env() -> None:
    if ENV_FILE.exists():
        load_dotenv(ENV_FILE)


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "run"


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))
    for row in rows:
        print(fmt.format(*row))


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _fmt_float(x: float | None, places: int = 2) -> str:
    if x is None:
        return "-"
    return f"{x:.{places}f}"


def _write_report(summary: dict[str, Any], run_name: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = REPORTS_DIR / f"{timestamp}_{_slug(run_name)}.json"
    with path.open("w") as f:
        json.dump(summary, f, indent=2, default=str)
    return path


# ── Output ───────────────────────────────────────────────────────────────────


def _print_model_run(m: run.ModelRunSummary) -> None:
    label = m.model or f"({m.provider})"
    print(f"\n── {label} ──")
    print(
        f"Cases: {m.case_count}  matched: {m.total_matched}/"
        f"{m.total_expected} expected, {m.total_predicted} predicted"
    )
    print(f"Precision: {_fmt_pct(m.precision)}  Recall: {_fmt_pct(m.recall)}  F1: {_fmt_pct(m.f1)}")
    cost_str = f"${m.total_cost_usd:.4f}" if m.total_cost_usd else "$0.0000"
    print(f"Total cost: {cost_str}  Total time: {m.total_duration_s:.1f}s")

    headers = ["case", "mode", "P", "R", "F1", "dur-P", "dur-R", "FP", "FN", "$"]
    rows = []
    for r in m.results:
        mode = "acast" if r.use_acast else "ai"
        rows.append(
            [
                r.case_id,
                mode,
                _fmt_pct(r.precision),
                _fmt_pct(r.recall),
                _fmt_pct(r.f1),
                _fmt_pct(r.duration_precision),
                _fmt_pct(r.duration_coverage),
                str(len(r.false_positives)),
                str(len(r.false_negatives)),
                _fmt_float(r.cost_usd, 4),
            ]
        )
    _print_table(headers, rows)

    for r in m.results:
        if r.error:
            print(f"\n[error] {r.case_id}: {r.error}")


def _print_comparison(summary: run.RunSummary) -> None:
    if len(summary.per_model) <= 1:
        return
    print(f"\n── comparison (IoU≥{summary.config.iou_threshold}) ──")
    headers = ["model", "P", "R", "F1", "matched", "FP", "FN", "$", "time"]
    rows = []
    for m in summary.per_model:
        fp = sum(len(c.false_positives) for c in m.results)
        fn = sum(len(c.false_negatives) for c in m.results)
        rows.append(
            [
                m.model or f"({m.provider})",
                _fmt_pct(m.precision),
                _fmt_pct(m.recall),
                _fmt_pct(m.f1),
                f"{m.total_matched}/{m.total_expected}",
                str(fp),
                str(fn),
                _fmt_float(m.total_cost_usd, 4),
                _fmt_float(m.total_duration_s, 1) + "s",
            ]
        )
    _print_table(headers, rows)


# ── Commands ─────────────────────────────────────────────────────────────────


def _cmd_list(_args: argparse.Namespace) -> int:
    cases = pipeline.list_cases()
    configs = run.list_run_configs()
    print(f"fixtures ({len(cases)} cases):")
    for c in cases:
        print(f"  {c}")
    print(f"\nrun configs ({len(configs)}):")
    for p in configs:
        print(f"  {p.relative_to(Path.cwd())}" if p.is_absolute() else f"  {p}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    config = run.load_run_config(args.path)

    print(
        f"Run: {config.name}  IoU≥{config.iou_threshold}  "
        f"use_acast default={config.use_acast_default}"
    )
    print(
        f"Models: {len(config.models)}  Cases: {len(config.cases)} "
        f"(ai: {sum(1 for c in config.cases if not c.use_acast)}, "
        f"acast: {sum(1 for c in config.cases if c.use_acast)})"
    )

    summary = run.execute_run(config)
    for model_summary in summary.per_model:
        _print_model_run(model_summary)
    _print_comparison(summary)

    path = _write_report(summary.to_dict(), config.name)
    print(f"\nReport: {path}")

    any_errors = any(c.error for m in summary.per_model for c in m.results)
    return 0 if not any_errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evals", description="Clipcast eval suite")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List fixture cases and run configs").set_defaults(func=_cmd_list)

    p_run = sub.add_parser("run", help="Execute a TOML run config")
    p_run.add_argument("path", help="Path to a .toml run config (see evals/runs/)")
    p_run.set_defaults(func=_cmd_run)

    return parser


def main(argv: list[str] | None = None) -> int:
    _load_env()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (RuntimeError, ProviderError, run.RunConfigError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
