from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import acast, analysis

RUNS_DIR = Path(__file__).parent / "runs"


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


def _write_run(summary: dict[str, Any], eval_name: str, suffix: str = "") -> Path:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    stem = f"{timestamp}_{eval_name}"
    if suffix:
        stem += f"_{suffix}"
    path = RUNS_DIR / f"{stem}.json"
    with path.open("w") as f:
        json.dump(summary, f, indent=2, default=str)
    return path


def _print_analysis_summary(s: analysis.AnalysisRunSummary) -> None:
    print(f"\nAnalysis eval — model: {s.model}  IoU≥{s.iou_threshold}")
    print(
        f"Cases: {s.case_count}  matched: {s.total_matched}/"
        f"{s.total_expected} expected, {s.total_predicted} predicted"
    )
    print(f"Precision: {_fmt_pct(s.precision)}  Recall: {_fmt_pct(s.recall)}  F1: {_fmt_pct(s.f1)}")
    print(f"Total cost: ${s.total_cost_usd:.4f}  Total time: {s.total_duration_s:.1f}s\n")

    headers = ["case", "P", "R", "F1", "dur-P", "dur-R", "FP", "FN", "$"]
    rows = []
    for r in s.results:
        rows.append(
            [
                r.case_id,
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

    failing = [r for r in s.results if r.error]
    for r in failing:
        print(f"\n[error] {r.case_id}: {r.error}")


def _print_acast_summary(s: acast.AcastRunSummary) -> None:
    print(f"\nAcast eval — IoU≥{s.iou_threshold}")
    print(
        f"Cases: {s.case_count}  matched: {s.total_matched}/"
        f"{s.total_expected} expected, {s.total_predicted} predicted"
    )
    print(f"Precision: {_fmt_pct(s.precision)}  Recall: {_fmt_pct(s.recall)}  F1: {_fmt_pct(s.f1)}")
    print(f"Total time: {s.total_duration_s:.1f}s\n")

    headers = ["case", "P", "R", "F1", "dur-P", "dur-R", "idents", "unpaired", "FP", "FN"]
    rows = []
    for r in s.results:
        rows.append(
            [
                r.case_id,
                _fmt_pct(r.precision),
                _fmt_pct(r.recall),
                _fmt_pct(r.f1),
                _fmt_pct(r.duration_precision),
                _fmt_pct(r.duration_coverage),
                str(r.raw_ident_count),
                str(r.unpaired_idents),
                str(len(r.false_positives)),
                str(len(r.false_negatives)),
            ]
        )
    _print_table(headers, rows)

    failing = [r for r in s.results if r.error]
    for r in failing:
        print(f"\n[error] {r.case_id}: {r.error}")


def _cmd_list(_args: argparse.Namespace) -> int:
    a_cases = analysis.list_cases()
    c_cases = acast.list_cases()
    print(f"analysis ({len(a_cases)} cases):")
    for c in a_cases:
        print(f"  {c}")
    print(f"\nacast ({len(c_cases)} cases):")
    for c in c_cases:
        print(f"  {c}")
    return 0


def _cmd_analysis(args: argparse.Namespace) -> int:
    summary = analysis.run(
        case_ids=args.case or None,
        model_name=args.model,
        api_key=args.api_key,
        iou_threshold=args.iou,
    )
    _print_analysis_summary(summary)
    path = _write_run(summary.to_dict(), "analysis", suffix=args.model.replace("/", "_"))
    print(f"\nReport: {path}")
    return 0 if summary.case_count and not any(r.error for r in summary.results) else 1


def _cmd_acast(args: argparse.Namespace) -> int:
    summary = acast.run(case_ids=args.case or None, iou_threshold=args.iou)
    _print_acast_summary(summary)
    path = _write_run(summary.to_dict(), "acast")
    print(f"\nReport: {path}")
    return 0 if summary.case_count and not any(r.error for r in summary.results) else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evals", description="Clipcast eval suite")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="List available fixture cases").set_defaults(func=_cmd_list)

    p_analysis = sub.add_parser("analysis", help="Run AI ad-detection eval (live Gemini calls)")
    p_analysis.add_argument("--case", action="append", help="Case id to run (repeatable)")
    p_analysis.add_argument("--model", default="gemini-2.5-flash", help="Gemini model name")
    p_analysis.add_argument("--api-key", default=None, help="Overrides GEMINI_API_KEY env var")
    p_analysis.add_argument("--iou", type=float, default=0.5, help="IoU threshold for matching")
    p_analysis.set_defaults(func=_cmd_analysis)

    p_acast = sub.add_parser("acast", help="Run Acast marker-detection eval")
    p_acast.add_argument("--case", action="append", help="Case id to run (repeatable)")
    p_acast.add_argument("--iou", type=float, default=0.5, help="IoU threshold for matching")
    p_acast.set_defaults(func=_cmd_acast)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RuntimeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
