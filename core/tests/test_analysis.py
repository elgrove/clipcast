import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from core.models import (
    AIModel,
    AnalysisReport,
    Config,
    PodcastEpisode,
    PodcastEpisodeAdvert,
    PodcastEpisodeAdverts,
    PodcastShow,
    Provider,
    Transcription,
    TranscriptionSegment,
)
from core.services.analysis import analyse_episode
from core.services.providers import GeminiProvider, get_ai_provider


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
        title="My Great Episode",
        published_at=datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC),
        source_audio_url="https://example.com/episode.mp3",
    )


@pytest.fixture
def transcribed_episode(episode):
    episode.transcription = [
        TranscriptionSegment(start_time=0.0, end_time=10.0, text="Welcome to the show"),
        TranscriptionSegment(
            start_time=10.0,
            end_time=60.0,
            text="This episode is brought to you by Acme Corp",
        ),
        TranscriptionSegment(start_time=60.0, end_time=120.0, text="Now back to the show"),
    ]
    episode.save()
    episode.mp3_path.parent.mkdir(parents=True, exist_ok=True)
    return episode


class MockAnalysisProvider:
    def __init__(self, adverts: PodcastEpisodeAdverts | None = None):
        self.adverts = adverts or PodcastEpisodeAdverts(
            adverts=[
                PodcastEpisodeAdvert(
                    start_time="10.0",
                    end_time="60.0",
                    advert_for="Acme Corp",
                    front_text="This episode is brought to you by Acme Corp",
                    tail_text="Now back to the show",
                )
            ]
        )

    def analyse_adverts(self, transcription, report=None):
        return self.adverts


class TestAnalyseEpisode:
    def test_saves_adverts_to_database(self, transcribed_episode):
        provider = MockAnalysisProvider()
        report = AnalysisReport()
        analyse_episode(transcribed_episode, report, provider)

        transcribed_episode.refresh_from_db()
        assert len(transcribed_episode.ads) == 1
        assert transcribed_episode.ads[0].advert_for == "Acme Corp"

    def test_writes_json_file(self, transcribed_episode):
        provider = MockAnalysisProvider()
        report = AnalysisReport()
        analyse_episode(transcribed_episode, report, provider)

        assert transcribed_episode.ads_path.exists()
        json_content = json.loads(transcribed_episode.ads_path.read_text())
        assert len(json_content["adverts"]) == 1
        assert json_content["adverts"][0]["advert_for"] == "Acme Corp"

    def test_raises_if_no_transcription(self, episode):
        provider = MockAnalysisProvider()
        report = AnalysisReport()

        with pytest.raises(ValueError, match="has no transcription"):
            analyse_episode(episode, report, provider)


class TestGetAnalysisProvider:
    def test_returns_gemini_provider(self, db):
        ai_model = AIModel.objects.create(
            name="gemini-2.0-flash",
            provider=Provider.GEMINI.value,
        )
        config = Config.get_instance()
        config.analysis_model = ai_model
        config.gemini_api_key = "test-api-key"
        config.save()

        provider = get_ai_provider("analysis")
        assert isinstance(provider, GeminiProvider)

    def test_raises_for_whisper(self, db):
        ai_model = AIModel.objects.create(
            name="whisper.cpp",
            provider=Provider.WHISPER.value,
            host="http://localhost:8080",
        )
        config = Config.get_instance()
        config.analysis_model = ai_model
        config.save()

        with pytest.raises(ValueError, match="does not support analysis"):
            get_ai_provider("analysis")

    def test_raises_if_no_model_configured(self, db):
        config = Config.get_instance()
        config.analysis_model = None
        config.save()

        with pytest.raises(ValueError, match="No analysis model configured"):
            get_ai_provider("analysis")


class TestGeminiProviderAnalysis:
    def test_calls_api_with_correct_params(self, db):
        ai_model = AIModel.objects.create(
            name="gemini-2.0-flash",
            provider=Provider.GEMINI.value,
        )
        config = Config.get_instance()
        config.analysis_model = ai_model
        config.gemini_api_key = "test-api-key"
        config.save()

        transcription = Transcription(
            segments=[
                TranscriptionSegment(start_time=0.0, end_time=10.0, text="Hello world"),
            ]
        )

        mock_response = MagicMock()
        mock_response.text = '{"adverts": []}'

        with patch("core.services.providers.genai.Client") as mock_genai:
            mock_client = MagicMock()
            mock_genai.return_value = mock_client
            mock_client.models.generate_content.return_value = mock_response

            provider = GeminiProvider()
            result = provider.analyse_adverts(transcription)

            assert result == PodcastEpisodeAdverts(adverts=[])
            mock_client.models.generate_content.assert_called_once()
