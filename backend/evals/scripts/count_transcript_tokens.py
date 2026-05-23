# ruff: noqa: T201
"""Token-count the transcripts in /home/aaron/docker/clipcast/podcasts to see
how close real episodes get to provider context windows.

Two encodings are reported per file:

  - srt    : the on-disk .mp3.srt as-is (timestamped cue blocks).
  - json   : list[TranscriptionSegment] dumped exactly like the prod analysis
             prompt does (`json.dumps(model_dump(), indent=2)`).

cl100k_base (GPT-4 / GPT-4o tokenizer) is used as a proxy; Gemini's tokenizer
differs but the ratios are close enough for sizing decisions. Run from
`backend/` with:

    uv run --with tiktoken python evals/scripts/count_transcript_tokens.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import tiktoken

PODCASTS_DIR = Path("/home/aaron/docker/clipcast/podcasts")
CONTEXT_WINDOWS = {
    "1M  (Gemini 2.5 Flash)": 1_048_576,
    "256k (most mid-tier)": 262_144,
    "128k (older GPT-4)": 131_072,
}

# SRT cue: "1\n00:00:00,000 --> 00:00:05,500\nHello\n\n"
SRT_BLOCK = re.compile(
    r"(?P<idx>\d+)\s*\n"
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(?P<end>\d{2}:\d{2}:\d{2},\d{3})\s*\n"
    r"(?P<text>.*?)(?=\n\s*\n|\n\s*\d+\s*\n|\Z)",
    re.DOTALL,
)


def _ts_to_seconds(stamp: str) -> float:
    hh, mm, rest = stamp.split(":")
    ss, ms = rest.split(",")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000


def srt_to_segments(srt_text: str) -> list[dict]:
    segments = []
    for m in SRT_BLOCK.finditer(srt_text):
        segments.append(
            {
                "start_time": _ts_to_seconds(m["start"]),
                "end_time": _ts_to_seconds(m["end"]),
                "text": m["text"].strip().replace("\n", " "),
            }
        )
    return segments


def fmt(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def main() -> None:
    enc = tiktoken.get_encoding("cl100k_base")
    srts = sorted(PODCASTS_DIR.rglob("*.mp3.srt"))
    if not srts:
        print(f"no .mp3.srt files under {PODCASTS_DIR}")
        return

    print(f"{len(srts)} transcripts under {PODCASTS_DIR}\n")
    print(
        f"{'show':<32}  {'dur':>6}  {'segs':>5}  "
        f"{'srt-tok':>8}  {'json-tok':>9}  {'ratio':>6}"
    )
    print("-" * 80)

    totals = {"srt": 0, "json": 0, "segs": 0, "secs": 0.0}
    max_json = 0
    max_json_path: Path | None = None

    for path in srts:
        srt_text = path.read_text(errors="replace")
        segs = srt_to_segments(srt_text)
        if not segs:
            continue
        duration = segs[-1]["end_time"]
        json_text = json.dumps({"segments": segs}, indent=2)

        srt_toks = len(enc.encode(srt_text))
        json_toks = len(enc.encode(json_text))

        totals["srt"] += srt_toks
        totals["json"] += json_toks
        totals["segs"] += len(segs)
        totals["secs"] += duration
        if json_toks > max_json:
            max_json = json_toks
            max_json_path = path

        show = path.parent.name[:32]
        hours = int(duration // 3600)
        mins = int((duration % 3600) // 60)
        print(
            f"{show:<32}  {hours}h{mins:02d}m  {len(segs):>5}  "
            f"{fmt(srt_toks):>8}  {fmt(json_toks):>9}  "
            f"{json_toks / srt_toks:>5.2f}x"
        )

    n = len(srts)
    avg_srt = totals["srt"] / n
    avg_json = totals["json"] / n
    print("-" * 80)
    print(
        f"avg  srt={fmt(int(avg_srt))} tokens  "
        f"json={fmt(int(avg_json))} tokens  "
        f"ratio={avg_json / avg_srt:.2f}x  "
        f"segs={int(totals['segs'] / n)}  "
        f"dur={int(totals['secs'] / n / 60)}min"
    )
    if max_json_path:
        print(f"max json: {fmt(max_json)} tokens — {max_json_path.name}")

    print("\nFit against context windows (json-encoded, as the app sends today):")
    for label, limit in CONTEXT_WINDOWS.items():
        fits = sum(
            1
            for path in srts
            if len(enc.encode(json.dumps({"segments": srt_to_segments(path.read_text(errors='replace'))}, indent=2))) <= limit
        )
        print(f"  {label:<28}  {fits}/{n}  ({fits / n * 100:.0f}%)")


if __name__ == "__main__":
    main()
