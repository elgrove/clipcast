"""Tests for the tiered scoring logic in evals.pipeline.

Exercises `_tiered_score` directly so we don't have to spin up the full
run_case + provider stack."""

from evals.metrics import Interval, match_intervals
from evals.pipeline import _tiered_score


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
