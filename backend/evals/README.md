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

API keys live in `backend/.env` (git-ignored). Copy the example and fill in:

```bash
cp backend/.env.example backend/.env
# set GEMINI_API_KEY=...
```

The CLI loads `backend/.env` automatically.

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

| `[run]`            | Type    | Default       | Notes                                       |
|--------------------|---------|---------------|---------------------------------------------|
| `name`             | string  | file stem     | Used in the report filename                 |
| `iou_threshold`    | float   | `0.5`         | Default IoU for matching                    |
| `use_acast`        | bool    | `false`       | Default `use_acast` for cases below         |

| `[[models]]`       | Type    | Required      | Notes                                       |
|--------------------|---------|---------------|---------------------------------------------|
| `spec`             | string  | one form req. | `"provider:model"` (preferred)              |
| `provider`         | string  | one form req. | Alternative to `spec`                       |
| `model`            | string  | one form req. | Alternative to `spec`                       |

| `[[cases]]`        | Type    | Required      | Notes                                       |
|--------------------|---------|---------------|---------------------------------------------|
| `id`               | string  | yes           | Must match `evals/fixtures/<id>/`           |
| `podcast`          | string  | no            | Informational                               |
| `custom_prompt`    | string  | no            | Per-case AI instructions (AI mode only)     |
| `use_acast`        | bool    | no            | Overrides `[run].use_acast`                 |
| `iou_threshold`    | float   | no            | Overrides `[run].iou_threshold`             |

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

`expected.json` — array of `CutRegion` (times as seconds or `HH:MM:SS.mmm`):
```json
[
  {"start_time": "00:00:13.000", "end_time": "00:01:33.000", "label": "Sponsor block"}
]
```

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

For each case (per model):

| Metric              | Meaning                                                              |
|---------------------|----------------------------------------------------------------------|
| `P` (precision)     | Of all predicted cut regions, fraction matching a ground-truth one   |
| `R` (recall)        | Of all ground-truth cut regions, fraction matched by a prediction    |
| `F1`                | Harmonic mean of P and R                                             |
| `dur-P`             | Of predicted seconds, fraction inside ground-truth cuts              |
| `dur-R`             | Of ground-truth seconds, fraction covered by predictions             |
| `FP` / `FN`         | False positives / false negatives — see report JSON for full spans   |

Matching is greedy 1-to-1 by descending IoU at the configured threshold.
Aggregate P/R/F1 across cases is the micro-average (sum of matches over sum
of predictions/expected).

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
