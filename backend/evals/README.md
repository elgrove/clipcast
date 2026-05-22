# Clipcast eval suite

Scores the cut regions Clipcast's clipping pipeline would produce against
hand-labelled ground truth, for a declared bundle of episodes, models, and
per-podcast settings.

A *run* is declared as a TOML file under `evals/runs/`. Each run:

- references one or more fixture cases (episodes),
- declares one or more AI models to evaluate,
- carries per-podcast settings (custom prompt, `use_acast` on/off),
- writes a JSON report to `evals/reports/` and prints a per-model table.

There is one eval pipeline. Per case it either:

- runs **AI analysis** on the transcript with the configured model and
  `custom_prompt`, yielding cut regions = the AI-detected ads; or
- runs **Acast marker detection** on the audio (`detect_idents` →
  `pair_idents`), yielding cut regions = the Acast bracket spans.

(Per the real pipeline in `tasks.py`, the AI analysis-inside-acast-brackets
step is reporting-only and does not influence cut regions, so it is not
included in the eval pipeline.)

## Configuration

API keys live in `backend/.env.evals` (git-ignored). Copy the example and fill in:

```bash
cp backend/.env.evals.example backend/.env.evals
# set GEMINI_API_KEY=...
```

Kept separate from the app's `backend/.env` so pydantic-settings (which only
recognises infra config) doesn't reject API-key keys it doesn't know about.
The CLI loads `backend/.env.evals` automatically on every run.

## Running

```bash
cd backend

# show fixture cases and run configs
uv run python -m evals list

# execute a run
uv run python -m evals run evals/runs/three-podcasts-baseline.toml
```

Each run writes a full JSON report to
`evals/reports/<timestamp>_<run-name>.json`. The `reports/` directory is
git-ignored.

## Run config schema

```toml
[run]
name = "three-podcasts-baseline"   # default: file stem
iou_threshold = 0.5                # default: 0.5
use_acast = false                  # default for [[cases]] below

# Models to evaluate. Each [[models]] block declares one model.
# Either `spec = "provider:model"` or split `provider`/`model`.
[[models]]
spec = "gemini:gemini-2.5-flash"

[[models]]
provider = "gemini"
model = "gemini-2.5-flash-lite"

# Cases — each references an evals/fixtures/<id>/ directory.
[[cases]]
id = "tifo-2026-01-08"
podcast = "Tifo Football Podcast"
custom_prompt = """
Tifo opens with a host-read sponsor segment. Anything before the first guest
introduction is likely an ad.
"""

[[cases]]
id = "tff-2026-01-09"
podcast = "Totally Football"
use_acast = true                   # per-case override

[[cases]]
id = "fof-2026-01-05"
podcast = "Footballers on Football"
iou_threshold = 0.75               # tighter matching for this case
```

### Field reference

| `[run]`                  | Type    | Default       | Notes                                       |
|--------------------------|---------|---------------|---------------------------------------------|
| `name`                   | string  | file stem     | Used in the report filename                 |
| `iou_threshold`          | float   | `0.5`         | Default IoU for matching                    |
| `use_acast`              | bool    | `false`       | Default `use_acast` for cases below         |
| `break_cluster_gap_s`    | float   | `5.0`         | Max gap (s) for merging ads into one break  |

| `[[models]]`       | Type    | Required      | Notes                                       |
|--------------------|---------|---------------|---------------------------------------------|
| `spec`             | string  | one form req. | `"provider:model"` (preferred)              |
| `provider`         | string  | one form req. | Alternative to `spec`                       |
| `model`            | string  | one form req. | Alternative to `spec`                       |

| `[[cases]]`              | Type    | Required      | Notes                                       |
|--------------------------|---------|---------------|---------------------------------------------|
| `id`                     | string  | yes           | Must match `evals/fixtures/<id>/`           |
| `podcast`                | string  | no            | Informational                               |
| `custom_prompt`          | string  | no            | Per-case AI instructions (AI mode only)     |
| `use_acast`              | bool    | no            | Overrides `[run].use_acast`                 |
| `iou_threshold`          | float   | no            | Overrides `[run].iou_threshold`             |
| `break_cluster_gap_s`    | float   | no            | Overrides `[run].break_cluster_gap_s`       |

Unknown keys are rejected so typos surface early.

## Fixture layout

```
evals/fixtures/<case-id>/
  meta.json             # podcast, episode_title, notes (informational)
  transcription.json    # list[TranscriptionSegment] — needed when use_acast=false
  audio.mp3             # needed when use_acast=true
  expected.json         # list[CutRegion] — ground truth
```

`<case-id>` should be a short kebab-case slug like `tifo-2026-01-08`.

### File schemas

`meta.json`:
```json
{
  "podcast": "Tifo Football Podcast",
  "episode_title": "Ole or Carrick? Chelsea's new coach...",
  "notes": "Three pre-rolls and one mid-roll cluster."
}
```

`transcription.json` — array of `TranscriptionSegment`:
```json
[
  {"start_time": 0.0, "end_time": 5.5, "text": "Hello world"},
  {"start_time": 5.5, "end_time": 9.2, "text": "..."}
]
```

`expected.json` — array of ground-truth ad entries (times as seconds or
`HH:MM:SS.mmm`):
```json
[
  {"start_time": "0.0", "end_time": "29.0", "label": "Ticumbo"},
  {"start_time": "205.844", "end_time": "315.539", "label": "SC Libero", "optional": true}
]
```

The optional `optional` field (default `false`) flags ground-truth ads that
the model is free to either find or skip — useful for ads with fuzzy
boundaries (host-read self-promo, segues without clean audio markers):

- If the model **predicts** an optional ad → absorbed (no FP penalty, no TP credit).
- If the model **misses** an optional ad → not counted as FN.
- If matched, the name-similarity score still records the pair.

Use this when you want the fixture to *describe* an ad break without
committing to a verdict on whether it should be cut.

## Seeding a fixture from a real episode

Episodes you've already processed give you a starting point. For each
episode under `../_podcasts/<show>/`:

1. The `.mp3.srt` cue list is the transcript — convert each cue to a
   `TranscriptionSegment` and save as `transcription.json`.
2. The `.mp3.json` ads list is the AI's prediction — convert to
   `CutRegion`s and hand-edit to correct any errors. Save as
   `expected.json`.
3. Copy or symlink the source audio in as `audio.mp3` if the case will be
   evaluated with `use_acast = true`.
4. Fill in `meta.json`.

## Metrics

Every case is scored at **two layers**, both reported separately:

### Ad-level (granular, individual adverts)

Measures how well the model picks out individual adverts: count, boundaries,
and the advertiser/brand name.

| Metric        | Meaning                                                            |
|---------------|--------------------------------------------------------------------|
| `ad-P`        | Of all predicted ads, fraction matching a ground-truth ad          |
| `ad-R`        | Of all ground-truth ads, fraction matched by a prediction          |
| `ad-F1`       | Harmonic mean of `ad-P` and `ad-R`                                 |
| `name`        | Mean token-set F1 between predicted/expected advertiser names      |
| `FP` / `FN`   | Granular false positives / false negatives                         |

`name` is computed only over matched pairs. Names are lowercased and split
on non-alphanumerics; the score is `2·|A ∩ B| / (|A| + |B|)` over the token
sets. `Monday.com` ↔ `monday.com` → 1.0; `Microsoft 365 Copilot` ↔ `Copilot`
→ 0.5; `Cadbury` ↔ `Monday` → 0.

### Break-level (merged ad breaks)

Measures how well the *cut audio* would line up — touching ads (gap ≤
`break_cluster_gap_s`, default 5s) are merged into a single ad-break region
in both prediction and ground truth, then scored.

| Metric        | Meaning                                                            |
|---------------|--------------------------------------------------------------------|
| `brk-P`       | Of merged predicted breaks, fraction matching a ground-truth break |
| `brk-R`       | Of merged ground-truth breaks, fraction matched by a prediction    |
| `brk-F1`      | Harmonic mean of `brk-P` and `brk-R`                               |
| `dur-P`       | Of merged-predicted seconds, fraction inside ground-truth breaks   |
| `dur-R`       | Of merged ground-truth seconds, covered by merged predictions      |

This is the layer that asks "did we cut from the start of the first ad in
the break to the end of the last ad?". A model that emits one big region
covering a 3-ad break will score perfectly here, even though its `ad-F1`
will be 0 against the granular ground truth.

### Configuration

| Key                          | Default | Notes                                       |
|------------------------------|---------|---------------------------------------------|
| `iou_threshold`              | `0.5`   | IoU at which two regions are a match        |
| `break_cluster_gap_s`        | `5.0`   | Gap (s) below which two ads are one break   |

Both can be set at run level and overridden per case.

Matching at either layer is greedy 1-to-1 by descending IoU. Aggregate
P/R/F1 across cases is the micro-average (sum of matches over sum of
predictions/expected).

Acast cases produce the same result regardless of model (the model is not
used) and are shared across each model's aggregate.

## Adding a provider

Register a provider in `evals/providers.py`:

```python
REGISTRY["openai"] = ProviderSpec(
    name="openai",
    api_key_env="OPENAI_API_KEY",
    factory=lambda model, key: OpenAIProvider(api_key=key, model=model),
)
```

The factory must return any `AIProviderBase` that implements
`analyse_adverts`. After registering, models become referenceable as
`openai:<model-name>` in run configs.
