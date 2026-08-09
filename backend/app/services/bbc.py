"""BBC trim pipeline: detect where show content starts and ends in a BBC
podcast episode and cut the wrapper audio (Sounds idents, continuity,
trailers, credits) outside it. Generalised from the In Our Time cleaning
pipeline (~/dev/iotc); the silence-snap constants are its battle-tested
values."""

from pathlib import Path
from urllib.parse import urlparse

from app.models import AdBreak, Advert
from app.services import audio
from app.services.editor import format_ms_to_time
from app.services.prompts import TRIM_BBC_PROMPT
from app.services.providers import Transcription

HEAD_WINDOW_S = 240.0  # idents + preamble + continuity + stray news fragments
TAIL_WINDOW_S = 480.0  # bigger: trailers + extra-time chat run long
MIN_TRIM_S = 1.0  # drop a cut this short — nothing real to trim

# Whisper timestamps run 0.2-0.4s early at word ends, so a raw cut leaves an
# audible fragment of the ident/trailer. After the LLM picks boundaries, each
# cut is pushed forward to a silence found by ffmpeg silencedetect.
SILENCE_THRESHOLD_DB = -35
SILENCE_MIN_DURATION_S = 0.10
HEAD_SNAP_FORWARD_MAX_S = 1.5  # past the fragment, before the host's inhale
TAIL_SNAP_FORWARD_MAX_S = 3.0  # end of the host's last word + trailing breath


def bbc_feed_url_heuristic(feed_url: str) -> bool:
    """BBC feeds and enclosures serve from bbc.co.uk / bbci.co.uk hosts
    (e.g. podcasts.files.bbci.co.uk)."""
    hostname = urlparse(feed_url).hostname or ""
    return hostname in ("bbc.co.uk", "bbci.co.uk") or hostname.endswith(
        (".bbc.co.uk", ".bbci.co.uk")
    )


def format_transcript(transcription: Transcription) -> str:
    return "\n".join(f"[{s.start_time:8.2f}s] {s.text}" for s in transcription.segments)


def build_trim_prompt(
    title: str,
    description: str,
    head_transcript: str,
    tail_transcript: str,
    head_window_s: float,
    tail_window_s: float,
    tail_offset_s: float,
) -> str:
    return TRIM_BBC_PROMPT.format(
        title=title,
        description=(description or "").strip()[:600],
        head_transcript=head_transcript or "(no speech detected)",
        tail_transcript=tail_transcript or "(no speech detected)",
        head_window_s=head_window_s,
        tail_window_s=tail_window_s,
        tail_offset_s=tail_offset_s,
    )


def validate_trim(
    content_start_s: float,
    content_end_s: float,
    head_window_len_s: float,
    tail_window_len_s: float,
    tail_offset_s: float,
) -> str | None:
    """Return a reason string if the model's boundaries are unusable, else None."""
    if not 0 <= content_start_s <= head_window_len_s:
        return f"content_start_s {content_start_s:.2f} outside head window (0-{head_window_len_s:.0f}s)"
    if not 0 <= content_end_s <= tail_window_len_s:
        return f"content_end_s {content_end_s:.2f} outside tail window (0-{tail_window_len_s:.0f}s)"
    if tail_offset_s + content_end_s <= content_start_s:
        return (
            f"content end {tail_offset_s + content_end_s:.2f}s not after "
            f"content start {content_start_s:.2f}s"
        )
    return None


def snap_head_cut(silences: list[tuple[float, float]], cut_s: float) -> float:
    """Push the head cut forward to the onset of the longest silence just past
    it (past the trailing ident fragment, before the host's inhale). Keeps the
    original cut if no silence starts within the search range."""
    eligible = [
        (onset, dur)
        for onset, dur in silences
        if cut_s - 0.02 <= onset <= cut_s + HEAD_SNAP_FORWARD_MAX_S
    ]
    if not eligible:
        return cut_s
    return max(eligible, key=lambda sd: sd[1])[0]


def snap_tail_cut(silences: list[tuple[float, float]], cut_s: float) -> float:
    """Push the tail cut forward to the next silence onset (the end of the
    host's last word plus its natural trailing breath). Keeps the original cut
    if no silence starts within the search range."""
    for onset, _ in sorted(silences):
        if cut_s - 0.05 < onset <= cut_s + TAIL_SNAP_FORWARD_MAX_S:
            return onset
    return cut_s


def detect_silences(path: Path) -> list[tuple[float, float]]:
    return audio.detect_silences(path, SILENCE_THRESHOLD_DB, SILENCE_MIN_DURATION_S)


def trim_to_breaks(
    content_start_s: float,
    content_end_s: float,
    duration_s: float,
    head_reason: str = "",
    tail_reason: str = "",
) -> list[AdBreak]:
    """Express the trim as cuts in the existing ad-breaks format — [0 → start]
    and [end → duration] — so editing, reporting, and the episode UI work
    unchanged. Zero/near-zero-length cuts are dropped."""

    def cut(start_s: float, end_s: float, source: str, reason: str) -> AdBreak:
        start, end = format_ms_to_time(int(start_s * 1000)), format_ms_to_time(int(end_s * 1000))
        return AdBreak(
            start_time=start,
            end_time=end,
            adverts=[Advert(start_time=start, end_time=end, advert_for=reason)],
            source=source,
        )

    breaks = []
    if content_start_s >= MIN_TRIM_S:
        breaks.append(cut(0.0, content_start_s, "bbc_trim_head", head_reason or "BBC intro"))
    if duration_s - content_end_s >= MIN_TRIM_S:
        breaks.append(cut(content_end_s, duration_s, "bbc_trim_tail", tail_reason or "BBC outro"))
    return breaks
