# Clipcast eval suite

Scores the ad-detection quality of Clipcast's two clipping paths:

- **`analysis`** — the AI path. Feeds a stored transcript to the configured Gemini
  model and scores the returned ad regions against hand-labelled ground truth.
- **`acast`** — the marker-based path. Runs `detect_idents` + `pair_idents` on a
  stored audio file and scores the resulting cut regions against hand-labelled
  ground truth.

Both evals share the same matching + scoring code in `metrics.py`.

## Running

```bash
cd backend

# show available fixture cases
uv run python -m evals list

# AI eval (live Gemini calls — costs real money)
GEMINI_API_KEY=... uv run python -m evals analysis
GEMINI_API_KEY=... uv run python -m evals analysis --model gemini-2.5-flash-lite
GEMINI_API_KEY=... uv run python -m evals analysis --case tifo-2026-01-08

# Acast eval (local, no API calls)
uv run python -m evals acast
uv run python -m evals acast --case foo

# tighter / looser matching
uv run python -m evals analysis --iou 0.75
```

Each run prints a per-case + aggregate summary and writes a full JSON report to
`evals/runs/<timestamp>_<eval>[_<model>].json`. The `runs/` directory is
git-ignored.

## Fixture layout

```
evals/fixtures/
  analysis/
    <case-id>/
      meta.json             # podcast, episode, notes, optional custom_prompt
      transcription.json    # list[TranscriptionSegment]
      expected_ads.json     # list[PodcastEpisodeAdvert] — ground truth
  acast/
    <case-id>/
      meta.json             # podcast, episode, notes
      audio.mp3             # full episode or representative clip
      expected_regions.json # list[CutRegion] — ground truth
```

`<case-id>` should be a short kebab-case slug like `tifo-2026-01-08`.

### File schemas

`meta.json`:
```json
{
  "podcast": "Tifo Football Podcast",
  "episode": "Ole or Carrick? Chelsea's new coach...",
  "notes": "Episode with three pre-roll ads and one mid-roll cluster.",
  "custom_prompt": "Optional per-podcast instructions, mirrors PodcastShow.custom_prompt"
}
```

`transcription.json` — array of `TranscriptionSegment`:
```json
[
  {"start_time": 0.0, "end_time": 5.5, "text": "Hello world"},
  {"start_time": 5.5, "end_time": 9.2, "text": "..."}
]
```

`expected_ads.json` — array of `PodcastEpisodeAdvert` (times as seconds or
`HH:MM:SS.mmm`):
```json
[
  {
    "start_time": "2.66",
    "end_time": "32.08",
    "advert_for": "Many Pets Pet Insurance",
    "front_text": "...",
    "tail_text": "..."
  }
]
```

`expected_regions.json` — array of `CutRegion` (times as `HH:MM:SS.mmm`):
```json
[
  {"start_time": "00:00:13.000", "end_time": "00:01:33.000", "label": "Acast ad break"}
]
```

## Seeding a fixture from a real episode

For an analysis case, the Tifo-style episodes already on disk under
`../_podcasts/<show>/` give you a starting point:

1. Pick an episode you've processed. Its `.mp3.srt` file is the transcript,
   its `.mp3.json` file is the AI's ad detection.
2. Convert the SRT to `transcription.json` (one segment per SRT cue, times in
   seconds).
3. Copy `<episode>.mp3.json` into `expected_ads.json` and hand-edit it to
   correct any errors — this is now ground truth, not a prediction.
4. Fill in `meta.json`.

For an Acast case, copy the audio (or a representative segment) and label the
true cut spans by ear or with the help of the existing detector output as a
starting point.

## Metrics

For each case the eval computes:

| Metric              | Meaning                                                              |
|---------------------|----------------------------------------------------------------------|
| `P` (precision)     | Of all predicted ads, fraction that matched a ground-truth ad        |
| `R` (recall)        | Of all ground-truth ads, fraction that were matched by a prediction  |
| `F1`                | Harmonic mean of P and R                                             |
| `dur-P`             | Of predicted-ad seconds, fraction that fall inside ground-truth ads  |
| `dur-R`             | Of ground-truth-ad seconds, fraction covered by predictions          |
| `FP` / `FN`         | False positives / false negatives — see report JSON for full spans   |

Matching is greedy 1-to-1 by descending IoU, with a default IoU threshold of
0.5. Override with `--iou`. Aggregate P/R/F1 across cases is the
micro-average (sum of matches over sum of predictions/expected).

## Adding a new eval

`metrics.py` is generic over `Interval`s, so new evals just need to:

1. Define `Interval` lists for predicted + expected.
2. Call `match_intervals` and `duration_metrics`.
3. Pack results into a dataclass and register a `sub.add_parser(...)` in `cli.py`.
