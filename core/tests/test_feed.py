import pytest
from django.test import RequestFactory

from core.models import ClippingReport, PodcastEpisode, PodcastShow
from core.services.feed import generate_podcast_feed


@pytest.mark.django_db
class TestGeneratePodcastFeed:
    def test_generates_valid_rss_feed(self, tmp_path):
        podcast = PodcastShow.objects.create(
            title="Test Podcast",
            description="A test podcast",
            itunes_id="12345",
            source_rss_url="https://example.com/feed.xml",
            path_directory=str(tmp_path / "test_podcast"),
            has_ads=True,
        )
        podcast.directory.mkdir(parents=True, exist_ok=True)

        factory = RequestFactory()
        request = factory.get("/")

        feed_xml = generate_podcast_feed(podcast, request)

        assert b"Test Podcast (Ad-Free)" in feed_xml
        assert b"A test podcast" in feed_xml
        assert b"rss" in feed_xml
        assert b"channel" in feed_xml

    def test_includes_only_clipped_episodes(self, tmp_path):
        podcast = PodcastShow.objects.create(
            title="Test Podcast",
            itunes_id="12345",
            source_rss_url="https://example.com/feed.xml",
            path_directory=str(tmp_path / "test_podcast"),
            has_ads=True,
        )
        podcast.directory.mkdir(parents=True, exist_ok=True)

        # Create an episode with a clipping report that has been edited
        clipped_episode = PodcastEpisode.objects.create(
            podcast=podcast,
            guid="clipped-episode",
            title="Clipped Episode",
            description="This episode has been clipped",
        )
        clipped_episode.mp3_path.parent.mkdir(parents=True, exist_ok=True)
        clipped_episode.mp3_path.write_text("fake audio data")

        report = ClippingReport.objects.create(episode=clipped_episode)
        from django.utils import timezone

        report.edited_at = timezone.now()
        report.save()

        # Create an episode without a clipping report
        PodcastEpisode.objects.create(
            podcast=podcast,
            guid="unclipped-episode",
            title="Unclipped Episode",
        )

        factory = RequestFactory()
        request = factory.get("/")

        feed_xml = generate_podcast_feed(podcast, request)

        assert b"Clipped Episode" in feed_xml
        assert b"Unclipped Episode" not in feed_xml

    def test_excludes_episodes_without_audio_files(self, tmp_path):
        podcast = PodcastShow.objects.create(
            title="Test Podcast",
            itunes_id="12345",
            source_rss_url="https://example.com/feed.xml",
            path_directory=str(tmp_path / "test_podcast"),
            has_ads=True,
        )
        podcast.directory.mkdir(parents=True, exist_ok=True)

        # Create an episode with a clipping report but no audio file
        episode = PodcastEpisode.objects.create(
            podcast=podcast,
            guid="no-audio-episode",
            title="No Audio Episode",
        )

        report = ClippingReport.objects.create(episode=episode)
        from django.utils import timezone

        report.edited_at = timezone.now()
        report.save()

        factory = RequestFactory()
        request = factory.get("/")

        feed_xml = generate_podcast_feed(podcast, request)

        assert b"No Audio Episode" not in feed_xml
