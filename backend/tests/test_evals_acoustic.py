"""Tests for the acoustic kept-seam metric."""

from pathlib import Path

from pydub import AudioSegment
from pydub.generators import Sine

from evals.acoustic import acoustic_from_values, acoustic_metrics
from evals.metrics import Interval


def _build(path: Path, segments: list[tuple[str, int]]) -> None:
    audio = AudioSegment.empty()
    for kind, ms in segments:
        audio += (
            Sine(440).to_audio_segment(duration=ms)
            if kind == "tone"
            else AudioSegment.silent(duration=ms)
        )
    audio.export(path, format="mp3")


def test_acoustic_metrics_none_without_audio_or_pairs():
    assert acoustic_metrics(None, [Interval(1, 2)]) is None
    assert acoustic_metrics(Path("x.mp3"), []) is None


def test_acoustic_metrics_scores_silent_seams_quiet(tmp_path):
    # tone(3s) | silence(1s) | tone(3s). A cut whose seams sit in the pause is quiet.
    audio = tmp_path / "a.mp3"
    _build(audio, [("tone", 3_000), ("silence", 1_000), ("tone", 3_000)])

    m = acoustic_metrics(audio, [Interval(3.5, 3.5)])  # both kept seams land in silence

    assert m is not None
    assert m.overall_dbfs_mean < -40
    assert m.quiet_seams == m.total_seams == 2


def test_acoustic_metrics_scores_tone_seams_loud(tmp_path):
    audio = tmp_path / "b.mp3"
    _build(audio, [("tone", 3_000), ("silence", 1_000), ("tone", 3_000)])

    m = acoustic_metrics(audio, [Interval(1.0, 6.0)])  # both kept seams land inside tone

    assert m is not None
    assert m.overall_dbfs_mean > -20
    assert m.quiet_seams == 0


def test_acoustic_from_values_aggregates():
    a = acoustic_from_values([-50.0, -30.0], [-45.0, -35.0])
    assert a.count == 2
    assert a.total_seams == 4
    assert a.quiet_seams == 2  # -50 and -45 are below -40
    assert a.overall_dbfs_mean == (-50 - 30 - 45 - 35) / 4
