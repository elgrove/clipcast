import pytest

from evals.metrics import (
    Interval,
    count_metrics,
    duration_metrics,
    iou,
    match_intervals,
    parse_time,
)

# ── parse_time ───────────────────────────────────────────────────────────────


def test_parse_time_seconds_float():
    assert parse_time(12.5) == 12.5


def test_parse_time_seconds_int():
    assert parse_time(30) == 30.0


def test_parse_time_seconds_string():
    assert parse_time("42.25") == 42.25


def test_parse_time_hms():
    assert parse_time("00:01:30.500") == 90.5
    assert parse_time("01:00:00.000") == 3600.0


def test_parse_time_ms():
    assert parse_time("02:30.500") == 150.5


def test_parse_time_invalid():
    with pytest.raises(ValueError):
        parse_time("1:2:3:4")


# ── Interval ─────────────────────────────────────────────────────────────────


def test_interval_duration():
    assert Interval(10.0, 25.5).duration == 15.5


def test_interval_rejects_inverted():
    with pytest.raises(ValueError):
        Interval(start=10.0, end=5.0)


# ── iou ──────────────────────────────────────────────────────────────────────


def test_iou_identical():
    a = Interval(10, 30)
    assert iou(a, a) == 1.0


def test_iou_disjoint():
    assert iou(Interval(0, 10), Interval(20, 30)) == 0.0


def test_iou_partial_overlap():
    # [0, 10] vs [5, 15] → intersection = 5, union = 15
    assert iou(Interval(0, 10), Interval(5, 15)) == pytest.approx(5 / 15)


def test_iou_one_contains_other():
    # [0, 100] vs [10, 20] → intersection = 10, union = 100
    assert iou(Interval(0, 100), Interval(10, 20)) == pytest.approx(0.10)


def test_iou_zero_duration_intervals():
    # Two point intervals at the same place → both zero union, returns 0
    assert iou(Interval(5, 5), Interval(5, 5)) == 0.0


# ── match_intervals ──────────────────────────────────────────────────────────


def test_match_intervals_perfect():
    predicted = [Interval(0, 10), Interval(20, 30)]
    expected = [Interval(0, 10), Interval(20, 30)]
    result = match_intervals(predicted, expected)
    assert len(result.matches) == 2
    assert result.false_positives == []
    assert result.false_negatives == []


def test_match_intervals_below_threshold_drops():
    # IoU = 5/15 ≈ 0.33 — below default 0.5
    predicted = [Interval(0, 10)]
    expected = [Interval(5, 15)]
    result = match_intervals(predicted, expected, iou_threshold=0.5)
    assert result.matches == []
    assert result.false_positives == [0]
    assert result.false_negatives == [0]


def test_match_intervals_greedy_picks_best():
    # Two predicted both overlap one expected; greedy picks the higher-IoU one
    predicted = [Interval(0, 10), Interval(1, 11)]
    expected = [Interval(1, 11)]  # perfect match for predicted[1]
    result = match_intervals(predicted, expected)
    assert len(result.matches) == 1
    assert result.matches[0].predicted_index == 1
    assert result.matches[0].expected_index == 0
    assert result.false_positives == [0]
    assert result.false_negatives == []


def test_match_intervals_empty_predicted():
    result = match_intervals([], [Interval(0, 10)])
    assert result.matches == []
    assert result.false_negatives == [0]


def test_match_intervals_empty_expected():
    result = match_intervals([Interval(0, 10)], [])
    assert result.matches == []
    assert result.false_positives == [0]


# ── count_metrics ────────────────────────────────────────────────────────────


def test_count_metrics_perfect():
    predicted = [Interval(0, 10), Interval(20, 30)]
    expected = [Interval(0, 10), Interval(20, 30)]
    result = match_intervals(predicted, expected)
    c = count_metrics(result, len(predicted), len(expected))
    assert c.precision == 1.0
    assert c.recall == 1.0
    assert c.f1 == 1.0


def test_count_metrics_partial():
    # 1 match out of 2 predicted, 1 match out of 2 expected
    predicted = [Interval(0, 10), Interval(100, 110)]
    expected = [Interval(0, 10), Interval(200, 210)]
    result = match_intervals(predicted, expected)
    c = count_metrics(result, len(predicted), len(expected))
    assert c.precision == 0.5
    assert c.recall == 0.5
    assert c.f1 == 0.5


def test_count_metrics_both_empty():
    c = count_metrics(match_intervals([], []), 0, 0)
    assert c.precision == 1.0
    assert c.recall == 1.0


# ── duration_metrics ─────────────────────────────────────────────────────────


def test_duration_metrics_perfect():
    predicted = [Interval(0, 30), Interval(100, 160)]
    expected = [Interval(0, 30), Interval(100, 160)]
    d = duration_metrics(predicted, expected)
    assert d.predicted_seconds == 90
    assert d.expected_seconds == 90
    assert d.overlap_seconds == 90
    assert d.precision == 1.0
    assert d.coverage == 1.0


def test_duration_metrics_partial_overlap():
    # predicted covers 0-30, expected covers 15-45 → overlap = 15, union not needed
    predicted = [Interval(0, 30)]
    expected = [Interval(15, 45)]
    d = duration_metrics(predicted, expected)
    assert d.predicted_seconds == 30
    assert d.expected_seconds == 30
    assert d.overlap_seconds == 15
    assert d.precision == 0.5
    assert d.coverage == 0.5


def test_duration_metrics_merges_overlapping_predictions():
    # Two overlapping predictions should count as 20s total, not 30s
    predicted = [Interval(0, 20), Interval(10, 20)]
    expected = [Interval(0, 20)]
    d = duration_metrics(predicted, expected)
    assert d.predicted_seconds == 20
    assert d.overlap_seconds == 20
    assert d.precision == 1.0


def test_duration_metrics_no_predictions():
    d = duration_metrics([], [Interval(0, 30)])
    assert d.predicted_seconds == 0
    assert d.expected_seconds == 30
    assert d.overlap_seconds == 0
    assert d.coverage == 0.0


def test_duration_metrics_no_expected():
    d = duration_metrics([Interval(0, 30)], [])
    assert d.predicted_seconds == 30
    assert d.expected_seconds == 0
    assert d.precision == 0.0
