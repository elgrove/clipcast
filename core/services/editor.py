import os
import shutil
import tempfile
from pathlib import Path

from pydub import AudioSegment

from core.models import PodcastEpisode


def parse_time_to_ms(time_str: str) -> int:
    parts = time_str.split(":")
    if len(parts) == 3:
        h, m, s = parts
        seconds = int(h) * 3600 + int(m) * 60 + float(s)
    elif len(parts) == 2:
        m, s = parts
        seconds = int(m) * 60 + float(s)
    else:
        seconds = float(time_str)
    return int(seconds * 1000)


def edit_episode(episode: PodcastEpisode, force: bool = False) -> None:
    if not episode.mp3_path.exists():
        raise ValueError(f"Episode {episode.title} has no downloaded MP3")

    if not episode.ads:
        return

    if episode.raw_path.exists() and not force:
        return

    temp_fd, temp_path_str = tempfile.mkstemp(suffix=".mp3")
    temp_path = Path(temp_path_str)
    os.close(temp_fd)

    try:
        shutil.copy(episode.mp3_path, temp_path)

        audio = AudioSegment.from_mp3(episode.mp3_path)

        ad_segments = []
        for ad in episode.ads:
            start_ms = parse_time_to_ms(ad.start_time)
            end_ms = parse_time_to_ms(ad.end_time)
            ad_segments.append((start_ms, end_ms))

        ad_segments.sort(key=lambda x: x[0])

        segments_to_keep = []
        current_pos = 0

        for start_ms, end_ms in ad_segments:
            if start_ms > current_pos:
                segments_to_keep.append(audio[current_pos:start_ms])
            current_pos = max(current_pos, end_ms)

        if current_pos < len(audio):
            segments_to_keep.append(audio[current_pos:])

        if not segments_to_keep:
            return

        result = segments_to_keep[0]
        for segment in segments_to_keep[1:]:
            result += segment

        result.export(episode.mp3_path, format="mp3")

        shutil.move(temp_path, episode.raw_path)

    finally:
        if temp_path.exists():
            temp_path.unlink()
