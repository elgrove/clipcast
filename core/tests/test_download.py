from datetime import UTC, datetime

import pytest
import responses

from core.models import PodcastEpisode, PodcastShow
from core.services.download import download_episode


@pytest.fixture
def podcast(db, tmp_path, settings):
    settings.BASE_DIR = tmp_path
    settings.PODCASTS_DIR = tmp_path / "podcasts"
    return PodcastShow.objects.create(
        title="Test Podcast",
        itunes_id="12345",
        source_rss_url="https://example.com/feed.xml",
        path_directory="test-podcast",
        has_ads=True,
    )


@pytest.fixture
def episode(podcast):
    return PodcastEpisode.objects.create(
        podcast=podcast,
        guid="episode-guid-123",
        title="My Great Episode Title Here",
        published_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
        source_audio_url="https://example.com/episode.mp3",
    )


class TestPodcastEpisodeFilePaths:
    def test_mp3_path(self, episode, tmp_path):
        path = episode.mp3_path
        expected = (
            tmp_path / "podcasts" / "test-podcast" / "20250115_My_Great_Episode_Title_Here.mp3"
        )
        assert path == expected

    def test_related_paths(self, episode):
        assert episode.srt_path.name == "20250115_My_Great_Episode_Title_Here.mp3.srt"
        assert episode.ads_path.name == "20250115_My_Great_Episode_Title_Here.mp3.json"
        assert episode.raw_path.name == "20250115_My_Great_Episode_Title_Here.mp3.raw"


class TestDownloadEpisode:
    @responses.activate
    def test_downloads_file_to_correct_path(self, episode):
        responses.add(
            responses.GET,
            "https://example.com/episode.mp3",
            body=b"fake mp3 content",
            status=200,
        )

        download_episode(episode)

        assert episode.mp3_path.exists()
        assert episode.mp3_path.read_bytes() == b"fake mp3 content"
