from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Interval:
    start: float
    end: float
    label: str = ""

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"Interval end {self.end} < start {self.start}")

    @property
    def duration(self) -> float:
        return self.end - self.start


def parse_time(value: str | float | int) -> float:
    if isinstance(value, int | float):
        return float(value)
    text = value.strip()
    if ":" in text:
        parts = text.split(":")
        if len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        raise ValueError(f"Unrecognised time format: {value!r}")
    return float(text)


def iou(a: Interval, b: Interval) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    union = (a.end - a.start) + (b.end - b.start) - inter
    if union <= 0:
        return 0.0
    return inter / union


@dataclass
class Match:
    predicted_index: int
    expected_index: int
    iou: float


@dataclass
class MatchResult:
    matches: list[Match] = field(default_factory=list)
    false_positives: list[int] = field(default_factory=list)
    false_negatives: list[int] = field(default_factory=list)


def match_intervals(
    predicted: list[Interval],
    expected: list[Interval],
    iou_threshold: float = 0.5,
) -> MatchResult:
    """Greedy 1-to-1 matching by descending IoU. Each predicted interval may
    match at most one expected interval, and vice versa. Pairs below
    `iou_threshold` are discarded."""
    candidates: list[tuple[float, int, int]] = []
    for pi, p in enumerate(predicted):
        for ei, e in enumerate(expected):
            score = iou(p, e)
            if score >= iou_threshold:
                candidates.append((score, pi, ei))
    candidates.sort(reverse=True)

    used_p: set[int] = set()
    used_e: set[int] = set()
    matches: list[Match] = []
    for score, pi, ei in candidates:
        if pi in used_p or ei in used_e:
            continue
        used_p.add(pi)
        used_e.add(ei)
        matches.append(Match(predicted_index=pi, expected_index=ei, iou=score))

    fp = [i for i in range(len(predicted)) if i not in used_p]
    fn = [i for i in range(len(expected)) if i not in used_e]
    return MatchResult(matches=matches, false_positives=fp, false_negatives=fn)


@dataclass
class CountMetrics:
    matched: int
    predicted_total: int
    expected_total: int

    @property
    def precision(self) -> float:
        if self.predicted_total == 0:
            return 1.0 if self.expected_total == 0 else 0.0
        return self.matched / self.predicted_total

    @property
    def recall(self) -> float:
        if self.expected_total == 0:
            return 1.0 if self.predicted_total == 0 else 0.0
        return self.matched / self.expected_total

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        if p + r == 0:
            return 0.0
        return 2 * p * r / (p + r)


def count_metrics(result: MatchResult, predicted_total: int, expected_total: int) -> CountMetrics:
    return CountMetrics(
        matched=len(result.matches),
        predicted_total=predicted_total,
        expected_total=expected_total,
    )


def _merge(intervals: list[Interval]) -> list[tuple[float, float]]:
    if not intervals:
        return []
    sorted_iv = sorted(((iv.start, iv.end) for iv in intervals), key=lambda x: x[0])
    merged: list[tuple[float, float]] = [sorted_iv[0]]
    for start, end in sorted_iv[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _overlap_duration(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """Total overlap between two sets of merged, sorted, non-overlapping intervals."""
    total = 0.0
    i = j = 0
    while i < len(a) and j < len(b):
        a_start, a_end = a[i]
        b_start, b_end = b[j]
        inter = max(0.0, min(a_end, b_end) - max(a_start, b_start))
        total += inter
        if a_end < b_end:
            i += 1
        else:
            j += 1
    return total


@dataclass
class DurationMetrics:
    predicted_seconds: float
    expected_seconds: float
    overlap_seconds: float

    @property
    def coverage(self) -> float:
        """Fraction of expected ad seconds that the predictions cover (recall by duration)."""
        if self.expected_seconds == 0:
            return 1.0 if self.predicted_seconds == 0 else 0.0
        return self.overlap_seconds / self.expected_seconds

    @property
    def precision(self) -> float:
        """Fraction of predicted seconds that fall inside expected ads (precision by duration)."""
        if self.predicted_seconds == 0:
            return 1.0 if self.expected_seconds == 0 else 0.0
        return self.overlap_seconds / self.predicted_seconds


def duration_metrics(predicted: list[Interval], expected: list[Interval]) -> DurationMetrics:
    p_merged = _merge(predicted)
    e_merged = _merge(expected)
    p_total = sum(end - start for start, end in p_merged)
    e_total = sum(end - start for start, end in e_merged)
    overlap = _overlap_duration(p_merged, e_merged)
    return DurationMetrics(
        predicted_seconds=p_total,
        expected_seconds=e_total,
        overlap_seconds=overlap,
    )
