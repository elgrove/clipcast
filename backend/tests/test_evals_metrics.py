import pytest

from evals.metrics import (
    Interval,
    boundary_metrics,
    boundary_metrics_from_deltas,
    cluster_regions,
    count_metrics,
    duration_metrics,
    iou,
    match_intervals,
    name_similarity,
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


# ── cluster_regions ──────────────────────────────────────────────────────────


def test_cluster_regions_empty():
    assert cluster_regions([], gap_threshold=5.0) == []


def test_cluster_regions_no_merges_when_gaps_exceed_threshold():
    # 30s gap > 5s threshold; nothing merges
    intervals = [Interval(0, 30, "a"), Interval(60, 90, "b")]
    result = cluster_regions(intervals, gap_threshold=5.0)
    assert len(result) == 2
    assert result == intervals


def test_cluster_regions_merges_touching_back_to_back():
    # Two back-to-back ads (gap = 0) collapse into one
    intervals = [Interval(0, 30, "Cadbury"), Interval(30, 60, "Monday")]
    result = cluster_regions(intervals, gap_threshold=5.0)
    assert len(result) == 1
    assert result[0].start == 0
    assert result[0].end == 60
    assert "Cadbury" in result[0].label and "Monday" in result[0].label


def test_cluster_regions_merges_within_threshold():
    # 3-second gap is within the 5s threshold
    intervals = [Interval(0, 30, "a"), Interval(33, 60, "b")]
    result = cluster_regions(intervals, gap_threshold=5.0)
    assert len(result) == 1
    assert (result[0].start, result[0].end) == (0, 60)


def test_cluster_regions_separates_at_threshold_boundary():
    # Gap of exactly 5.001s is over threshold; should not merge
    intervals = [Interval(0, 30, "a"), Interval(35.001, 65, "b")]
    result = cluster_regions(intervals, gap_threshold=5.0)
    assert len(result) == 2


def test_cluster_regions_handles_real_guardiola_data():
    # Three back-to-back ads at episode start (gaps 0.32s, 0s) — one break
    # Mid-roll cluster of 3 (gaps 3.28s, 0s) — one break
    # Final cluster of 3 (gaps 0s, 0s) — one break
    intervals = [
        Interval(0.0, 29.92, "Cadbury"),
        Interval(30.24, 61.09, "Monday"),
        Interval(61.09, 92.6, "Starling"),
        Interval(1674.434, 1718.554, "Tui"),
        Interval(1721.834, 1748.674, "Starling"),
        Interval(1748.674, 1781.054, "Cadbury"),
        Interval(4965.14, 4997.305, "Swiss"),
        Interval(4997.305, 5017.545, "McDonald's"),
        Interval(5017.545, 5047.353, "Vanta"),
    ]
    result = cluster_regions(intervals, gap_threshold=5.0)
    assert len(result) == 3
    assert (result[0].start, result[0].end) == (0.0, 92.6)
    assert (result[1].start, result[1].end) == (1674.434, 1781.054)
    assert (result[2].start, result[2].end) == (4965.14, 5047.353)


def test_cluster_regions_unsorted_input():
    intervals = [Interval(60, 90, "b"), Interval(0, 30, "a")]
    result = cluster_regions(intervals, gap_threshold=5.0)
    # Sorted by start, not merged (30s gap > 5s threshold)
    assert [iv.start for iv in result] == [0, 60]


# ── name_similarity ──────────────────────────────────────────────────────────


def test_name_similarity_identical():
    assert name_similarity("Monday.com", "Monday.com") == 1.0


def test_name_similarity_case_insensitive():
    assert name_similarity("Monday.com", "monday.com") == 1.0


def test_name_similarity_punctuation_matches():
    # Both tokenise to {monday, com} regardless of casing/symbols
    assert name_similarity("Monday.com", "MONDAY .COM") == 1.0


def test_name_similarity_partial():
    # {microsoft, 365, copilot} vs {copilot}: F1 = 2*1/(3+1) = 0.5
    assert name_similarity("Microsoft 365 Copilot", "Copilot") == pytest.approx(0.5)


def test_name_similarity_completely_different():
    assert name_similarity("Cadbury", "Monday") == 0.0


def test_name_similarity_empty_string():
    assert name_similarity("", "Cadbury") == 0.0
    assert name_similarity("Cadbury", "") == 0.0


def test_name_similarity_extra_tokens_lower_score():
    # {tui} vs {tui, travel}: F1 = 2*1/(1+2) ≈ 0.667
    assert name_similarity("Tui", "Tui Travel") == pytest.approx(2 / 3)


# ── optional flag on Interval / cluster_regions ──────────────────────────────


def test_interval_optional_defaults_false():
    iv = Interval(0, 10)
    assert iv.optional is False


def test_cluster_regions_optional_aggregates_via_and():
    # Two adjacent intervals: one required, one optional → cluster is REQUIRED
    intervals = [
        Interval(0, 30, "a", optional=False),
        Interval(30, 60, "b", optional=True),
    ]
    result = cluster_regions(intervals, gap_threshold=5.0)
    assert len(result) == 1
    assert result[0].optional is False


def test_cluster_regions_all_optional_stays_optional():
    intervals = [
        Interval(0, 30, "a", optional=True),
        Interval(30, 60, "b", optional=True),
    ]
    result = cluster_regions(intervals, gap_threshold=5.0)
    assert len(result) == 1
    assert result[0].optional is True


def test_cluster_regions_distant_optional_preserved():
    # Two non-adjacent intervals; the optional one stays its own cluster
    intervals = [
        Interval(0, 30, "a", optional=False),
        Interval(200, 300, "b", optional=True),
    ]
    result = cluster_regions(intervals, gap_threshold=5.0)
    assert len(result) == 2
    assert result[0].optional is False
    assert result[1].optional is True


# ── boundary_metrics ─────────────────────────────────────────────────────────


def test_boundary_metrics_empty():
    b = boundary_metrics([])
    assert b.count == 0
    assert b.start_mean == 0.0
    assert b.start_abs_mean == 0.0
    assert b.start_abs_p95 == 0.0
    assert b.end_mean == 0.0
    assert b.end_abs_mean == 0.0
    assert b.end_abs_p95 == 0.0
    assert b.start_deltas == []
    assert b.end_deltas == []


def test_boundary_metrics_exact_match():
    pred = Interval(10.0, 30.0)
    exp = Interval(10.0, 30.0)
    b = boundary_metrics([(pred, exp)])
    assert b.count == 1
    assert b.start_mean == 0.0
    assert b.start_abs_mean == 0.0
    assert b.start_abs_p95 == 0.0
    assert b.end_mean == 0.0


def test_boundary_metrics_signs_predicted_minus_expected():
    # Predicted starts 2s late and ends 3s early — start delta +2, end delta -3
    pred = Interval(12.0, 27.0)
    exp = Interval(10.0, 30.0)
    b = boundary_metrics([(pred, exp)])
    assert b.start_mean == pytest.approx(2.0)
    assert b.start_abs_mean == pytest.approx(2.0)
    assert b.end_mean == pytest.approx(-3.0)
    assert b.end_abs_mean == pytest.approx(3.0)


def test_boundary_metrics_signed_bias_cancels():
    # Three pairs with start deltas -2, 0, +2 → signed mean 0, abs mean 4/3
    pairs = [
        (Interval(8.0, 30.0), Interval(10.0, 30.0)),  # start -2
        (Interval(10.0, 30.0), Interval(10.0, 30.0)),  # start 0
        (Interval(12.0, 30.0), Interval(10.0, 30.0)),  # start +2
    ]
    b = boundary_metrics(pairs)
    assert b.start_mean == pytest.approx(0.0)
    assert b.start_abs_mean == pytest.approx(4.0 / 3.0)


def test_boundary_metrics_p95_tracks_worst_case():
    # 10 pairs: 9 have a 0.5s end delta, 1 has a 10s end delta. Linear-interp
    # p95 over a sorted list of [0.5 nine times, 10.0] sits at position
    # 0.95*(10-1)=8.55,
    # blending sorted[8]=0.5 and sorted[9]=10.0 → 0.5*0.45 + 10*0.55 = 5.725.
    # Well above the mean (1.45) and pulled toward the outlier, which is what
    # we want from a "worst-case tail" metric.
    pairs = [(Interval(0, 30), Interval(0, 30.5)) for _ in range(9)]
    pairs.append((Interval(0, 30), Interval(0, 40)))
    b = boundary_metrics(pairs)
    assert b.end_abs_mean == pytest.approx((9 * 0.5 + 10.0) / 10)
    assert b.end_abs_p95 == pytest.approx(0.5 * 0.45 + 10.0 * 0.55)
    assert b.end_abs_p95 > b.end_abs_mean


def test_boundary_metrics_from_deltas_round_trips():
    # Aggregating two cases of raw deltas should match the pair-based metric
    # over the same flattened pairs.
    pairs_a = [
        (Interval(11.0, 30.0), Interval(10.0, 31.0)),  # +1, -1
        (Interval(9.0, 32.0), Interval(10.0, 30.0)),  # -1, +2
    ]
    pairs_b = [
        (Interval(14.0, 30.0), Interval(10.0, 28.0)),  # +4, +2
    ]
    combined = boundary_metrics(pairs_a + pairs_b)

    a_metrics = boundary_metrics(pairs_a)
    b_metrics = boundary_metrics(pairs_b)
    aggregated = boundary_metrics_from_deltas(
        a_metrics.start_deltas + b_metrics.start_deltas,
        a_metrics.end_deltas + b_metrics.end_deltas,
    )
    assert aggregated.count == combined.count
    assert aggregated.start_mean == pytest.approx(combined.start_mean)
    assert aggregated.start_abs_mean == pytest.approx(combined.start_abs_mean)
    assert aggregated.start_abs_p95 == pytest.approx(combined.start_abs_p95)
    assert aggregated.end_mean == pytest.approx(combined.end_mean)
    assert aggregated.end_abs_mean == pytest.approx(combined.end_abs_mean)
    assert aggregated.end_abs_p95 == pytest.approx(combined.end_abs_p95)
