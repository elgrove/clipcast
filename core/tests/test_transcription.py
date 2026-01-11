from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
import responses

from core.models import (
    AIModel,
    Config,
    PodcastEpisode,
    PodcastShow,
    Provider,
    Transcription,
    TranscriptionReport,
    TranscriptionSegment,
)
from core.services.providers import (
    GeminiProvider,
    WhisperProvider,
)
from core.services.transcription import transcribe_episode


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
def downloaded_episode(episode):
    episode.mp3_path.parent.mkdir(parents=True, exist_ok=True)
    episode.mp3_path.write_bytes(b"fake mp3 content")
    return episode


class MockProvider:
    def __init__(self, transcription: Transcription | None = None):
        self.transcription = transcription or Transcription(
            segments=[
                TranscriptionSegment(start_time=0.0, end_time=5.0, text="Hello world"),
                TranscriptionSegment(start_time=5.0, end_time=10.0, text="This is a test"),
            ]
        )

    def transcribe(self, audio_path, report=None):
        return self.transcription


class TestTranscribeEpisode:
    def test_saves_transcription_to_database(self, downloaded_episode):
        provider = MockProvider()
        report = TranscriptionReport()
        transcribe_episode(downloaded_episode, report, provider)

        downloaded_episode.refresh_from_db()
        assert len(downloaded_episode.transcription) == 2
        assert downloaded_episode.transcription[0].text == "Hello world"

    def test_writes_srt_file(self, downloaded_episode):
        provider = MockProvider()
        report = TranscriptionReport()
        transcribe_episode(downloaded_episode, report, provider)

        assert downloaded_episode.srt_path.exists()
        srt_content = downloaded_episode.srt_path.read_text()
        assert "Hello world" in srt_content
        assert "00:00:00,000 --> 00:00:05,000" in srt_content

    def test_raises_if_no_audio_file(self, episode):
        provider = MockProvider()
        report = TranscriptionReport()

        with pytest.raises(ValueError, match="has no downloaded audio file"):
            transcribe_episode(episode, report, provider)


class TestTranscriptionToSrt:
    def test_formats_correctly(self):
        transcription = Transcription(
            segments=[
                TranscriptionSegment(start_time=0.0, end_time=5.5, text="First segment"),
                TranscriptionSegment(start_time=5.5, end_time=12.25, text="Second segment"),
            ]
        )

        srt = transcription.to_srt()

        assert "00:00:00,000 --> 00:00:05,500" in srt
        assert "First segment" in srt
        assert "00:00:05,500 --> 00:00:12,250" in srt
        assert "Second segment" in srt

    def test_handles_hours(self):
        transcription = Transcription(
            segments=[
                TranscriptionSegment(start_time=3661.5, end_time=3665.0, text="After an hour"),
            ]
        )

        srt = transcription.to_srt()

        assert "01:01:01,500 --> 01:01:05,000" in srt


class TestWhisperProvider:
    @responses.activate
    def test_parses_verbose_json_response(self, db, tmp_path):
        ai_model = AIModel.objects.create(
            name="whisper.cpp",
            provider=Provider.WHISPER.value,
            host="http://localhost:8080",
        )
        config = Config.get_instance()
        config.transcription_model = ai_model
        config.save()

        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake audio data")

        responses.add(
            responses.POST,
            "http://localhost:8080/inference",
            json={
                "segments": [
                    {"start": 0.0, "end": 5.0, "text": "Hello"},
                    {"start": 5.0, "end": 10.0, "text": "World"},
                ]
            },
            status=200,
        )

        provider = WhisperProvider()
        result = provider.transcribe(audio_path)

        assert len(result.segments) == 2
        assert result.segments[0].text == "Hello"
        assert result.segments[0].start_time == 0.0


class TestGeminiProvider:
    def test_parses_json_response(self, db, tmp_path):
        ai_model = AIModel.objects.create(
            name="gemini-2.0-flash",
            provider=Provider.GEMINI.value,
        )
        config = Config.get_instance()
        config.transcription_model = ai_model
        config.gemini_api_key = "test-api-key"
        config.save()

        audio_path = tmp_path / "test.mp3"
        audio_path.write_bytes(b"fake audio data")

        mock_file = MagicMock()
        mock_response = MagicMock()
        mock_response.text = '[{"start_time": 0.0, "end_time": 5.0, "text": "Gemini transcript"}]'

        with patch("core.services.providers.genai.Client") as mock_genai:
            mock_client = MagicMock()
            mock_genai.return_value = mock_client
            mock_client.files.upload.return_value = mock_file
            mock_client.models.generate_content.return_value = mock_response

            provider = GeminiProvider()
            result = provider.transcribe(audio_path)

            assert len(result.segments) == 1
            assert result.segments[0].text == "Gemini transcript"
