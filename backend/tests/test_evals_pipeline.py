"""Tests for the tiered scoring logic in evals.pipeline.

Exercises `_tiered_score` directly so we don't have to spin up the full
run_case + provider stack."""

import json

import pytest
from pydub import AudioSegment

from app.models import AdBreak, Advert
from evals.metrics import Interval, match_intervals
from evals.pipeline import _tiered_score, load_case, run_case
from evals.providers import ModelSpec


def _score(predicted: list[Interval], expected: list[Interval], iou: float = 0.5):
    match = match_intervals(predicted, expected, iou_threshold=iou)
    return match, _tiered_score(match, predicted, expected)


def test_tiered_score_all_required_perfect():
    predicted = [Interval(0, 10), Interval(20, 30)]
    expected = [Interval(0, 10, optional=False), Interval(20, 30, optional=False)]
    _, s = _score(predicted, expected)
    assert s.precision == 1.0
    assert s.recall == 1.0
    assert s.f1 == 1.0
    assert s.required_expected_count == 2
    assert s.optional_expected_count == 0
    assert s.matched_optional == []


def test_tiered_score_optional_match_absorbs_prediction():
    # One required matched, one prediction that matches an optional ad → absorbed
    predicted = [Interval(0, 10), Interval(100, 110)]
    expected = [
        Interval(0, 10, optional=False),
        Interval(100, 110, optional=True),
    ]
    _, s = _score(predicted, expected)
    # 1 required matched, 0 unmatched predictions → precision 100%
    assert s.precision == 1.0
    assert len(s.matched_required) == 1
    assert len(s.matched_optional) == 1
    assert s.fp_indices == []
    assert s.required_expected_count == 1
    # Recall over required only → 1/1
    assert s.recall == 1.0


def test_tiered_score_optional_miss_not_penalised():
    # One required ad matched. An optional ad in ground truth is not predicted —
    # this should NOT show up as a false negative.
    predicted = [Interval(0, 10)]
    expected = [
        Interval(0, 10, optional=False),
        Interval(100, 110, optional=True),
    ]
    _, s = _score(predicted, expected)
    assert s.precision == 1.0
    assert s.recall == 1.0
    assert s.fn_indices == []
    assert len(s.unmatched_optional_indices) == 1


def test_tiered_score_optional_only_no_predictions():
    # Only optional expecteds, no predictions → both denominators are zero
    predicted: list[Interval] = []
    expected = [Interval(100, 110, optional=True)]
    _, s = _score(predicted, expected)
    assert s.precision == 1.0
    assert s.recall == 1.0
    assert s.required_expected_count == 0


def test_tiered_score_fp_outside_optional_still_penalised():
    # Prediction that doesn't match anything (required or optional) is still FP
    predicted = [Interval(500, 600)]  # nothing nearby in expected
    expected = [
        Interval(0, 10, optional=False),
        Interval(100, 110, optional=True),
    ]
    _, s = _score(predicted, expected)
    # 0 TP, 1 FP, 1 FN (the required at 0-10)
    assert s.precision == 0.0
    assert s.recall == 0.0
    assert len(s.fp_indices) == 1
    assert len(s.fn_indices) == 1


def test_tiered_score_required_miss_counts_as_fn():
    predicted = [Interval(0, 10)]
    expected = [
        Interval(0, 10, optional=False),
        Interval(100, 110, optional=False),  # required, missed
    ]
    _, s = _score(predicted, expected)
    assert s.precision == 1.0  # 1 TP, 0 FP
    assert s.recall == 0.5  # 1 TP, 1 FN
    assert len(s.fn_indices) == 1


def test_tiered_score_optional_only_match_when_iou_passes():
    # Predicted partially overlaps optional ground truth — but IoU < 0.5, so
    # not matched. Then it's NOT absorbed; it's a FP.
    predicted = [Interval(0, 5)]
    expected = [Interval(0, 20, optional=True)]  # IoU = 5/20 = 0.25
    _, s = _score(predicted, expected)
    assert len(s.matched_optional) == 0
    assert len(s.fp_indices) == 1
    # No required expecteds → recall denominator is zero
    assert s.recall == 0.0  # because there's a prediction, FP-only


def test_tiered_score_high_iou_optional_match_is_absorbed():
    # Same span as before but IoU >= 0.5 → absorbed
    predicted = [Interval(0, 18)]
    expected = [Interval(0, 20, optional=True)]  # IoU = 18/20 = 0.9
    _, s = _score(predicted, expected)
    assert len(s.matched_optional) == 1
    assert s.fp_indices == []
    # No required expecteds, all predictions absorbed → precision 1.0
    assert s.precision == 1.0


# ── run_case(mode="ai_refined") integration ──────────────────────────────────


@pytest.fixture
def refined_case(tmp_path, monkeypatch):
    """Build a self-contained eval fixture in tmp_path: 60s silent mp3, stub
    transcription, expected ad at [14s, 32s]. Monkeypatches FIXTURES_DIR so
    the real fixtures directory is untouched."""
    fixtures_dir = tmp_path / "fixtures"
    case_id = "eval-refined-test"
    case_dir = fixtures_dir / case_id
    case_dir.mkdir(parents=True)

    (case_dir / "meta.json").write_text(json.dumps({"podcast": "Stub", "episode_title": "Stub"}))
    AudioSegment.silent(duration=60_000).export(case_dir / "audio.mp3", format="mp3")
    (case_dir / "transcription.json").write_text(
        json.dumps([{"start_time": 0.0, "end_time": 60.0, "text": "stub transcript"}])
    )
    (case_dir / "expected.json").write_text(
        json.dumps([{"start_time": "14.0", "end_time": "32.0", "label": "Sponsor"}])
    )

    monkeypatch.setattr("evals.pipeline.FIXTURES_DIR", fixtures_dir)
    return load_case(case_id)


def test_run_case_ai_refined_happy_path(refined_case, monkeypatch):
    """run_case with mode='ai_refined' produces refined cut regions and
    populates the refinement diagnostics on PipelineResult."""

    def fake_analyse(_segments, *, provider, report, custom_instructions=None):
        # Analysis returns one break at [20s, 30s] (rough text-level boundaries)
        report.cost_usd = 0.001
        report.input_tokens = 100
        report.output_tokens = 20
        return [
            AdBreak(
                start_time="00:00:20.000",
                end_time="00:00:30.000",
                adverts=[
                    Advert(
                        start_time="00:00:20.000",
                        end_time="00:00:30.000",
                        advert_for="Sponsor",
                    )
                ],
            )
        ]

    class _StubRefiner:
        """Returns scripted offsets: window [10, 30] + 4000 = 14s,
        window [20, 40] + 12000 = 32s — matching expected.json exactly."""

        def refine_boundary(self, *, audio_path, direction, report=None):
            if report is not None:
                report.input_tokens = (report.input_tokens or 0) + 50
                report.output_tokens = (report.output_tokens or 0) + 5
                report.cost_usd = (report.cost_usd or 0.0) + 0.0001
            return {"ad_start": 4000, "ad_end": 12000}[direction]

    monkeypatch.setattr("evals.pipeline.analyse_transcription", fake_analyse)
    monkeypatch.setattr("evals.pipeline.build_provider", lambda spec: _StubRefiner())

    result = run_case(
        refined_case,
        mode="ai_refined",
        model=ModelSpec(provider="gemini", model="dummy-analysis"),
        refinement_model=ModelSpec(provider="gemini", model="dummy-refine"),
    )

    assert result.error is None
    assert result.mode == "ai_refined"
    assert result.refinement_model == "gemini:dummy-refine"
    # The refined break is what gets cut. Its inner advert is preserved as-is
    # from analysis, so ad-level metrics check that; break-level metrics check
    # the refined outer edges.
    assert len(result.predicted_breaks) == 1
    assert result.predicted_breaks[0]["start_time"] == pytest.approx(14.0, abs=0.01)
    assert result.predicted_breaks[0]["end_time"] == pytest.approx(32.0, abs=0.01)
    assert result.boundaries_refined == 2
    assert result.boundaries_snapped == 0
    assert result.boundaries_kept == 0
    assert result.refinement_input_tokens == 100  # 2 boundaries x 50
    assert result.refinement_cost_usd == pytest.approx(0.0002, abs=1e-6)
    # Analysis tokens recorded separately
    assert result.input_tokens == 100
    assert result.cost_usd == pytest.approx(0.001, abs=1e-6)
    assert result.break_f1 == 1.0


def test_run_case_ai_refined_requires_refinement_model(refined_case, monkeypatch):
    def fake_analyse(_segments, *, provider, report, custom_instructions=None):
        return [
            AdBreak(
                start_time="00:00:20.000",
                end_time="00:00:30.000",
                adverts=[
                    Advert(
                        start_time="00:00:20.000",
                        end_time="00:00:30.000",
                        advert_for="Sponsor",
                    )
                ],
            )
        ]

    monkeypatch.setattr("evals.pipeline.analyse_transcription", fake_analyse)
    monkeypatch.setattr("evals.pipeline.build_provider", lambda spec: object())

    result = run_case(
        refined_case,
        mode="ai_refined",
        model=ModelSpec(provider="gemini", model="dummy-analysis"),
        refinement_model=None,
    )

    assert result.error is not None
    assert "refinement_model is required" in result.error
