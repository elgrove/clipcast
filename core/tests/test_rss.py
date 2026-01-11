import responses
from django.conf import settings

from core.services.rss import (
    _parse_date,
    _parse_duration,
    lookup_itunes,
    parse_rss_feed,
    search_itunes,
)

SAMPLE_ITUNES_SEARCH_RESPONSE = {
    "resultCount": 2,
    "results": [
        {
            "collectionId": 12345,
            "collectionName": "Test Podcast",
            "artistName": "Test Artist",
            "feedUrl": "https://example.com/feed.xml",
            "artworkUrl600": "https://example.com/art.jpg",
            "primaryGenreName": "Comedy",
        },
        {
            "collectionId": 67890,
            "collectionName": "Another Podcast",
            "artistName": "Another Artist",
            "feedUrl": "https://example.com/feed2.xml",
            "artworkUrl100": "https://example.com/art2.jpg",
            "primaryGenreName": "News",
        },
    ],
}

SAMPLE_RSS_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Test Podcast</title>
    <description>A test podcast description</description>
    <itunes:image href="https://example.com/podcast-artwork.jpg"/>
    <item>
      <guid>episode-1</guid>
      <title>Episode One</title>
      <description>First episode description</description>
      <pubDate>Mon, 25 Dec 2025 10:00:00 GMT</pubDate>
      <itunes:duration>01:30:45</itunes:duration>
      <enclosure url="https://example.com/ep1.mp3" type="audio/mpeg" length="12345"/>
    </item>
    <item>
      <guid>episode-2</guid>
      <title>Episode Two</title>
      <description>Second episode description</description>
      <pubDate>Sun, 24 Dec 2025 10:00:00 GMT</pubDate>
      <itunes:duration>45:30</itunes:duration>
      <enclosure url="https://example.com/ep2.mp3" type="audio/mpeg" length="67890"/>
    </item>
  </channel>
</rss>
"""


class TestSearchItunes:
    @responses.activate
    def test_search_returns_podcasts(self):
        responses.add(
            responses.GET,
            settings.ITUNES_SEARCH_URL,
            json=SAMPLE_ITUNES_SEARCH_RESPONSE,
            status=200,
        )

        results = search_itunes("test", limit=10)

        assert len(results) == 2
        assert results[0].itunes_id == "12345"
        assert results[0].title == "Test Podcast"
        assert results[0].artist == "Test Artist"
        assert results[0].feed_url == "https://example.com/feed.xml"
        assert results[0].artwork_url == "https://example.com/art.jpg"
        assert results[0].genre == "Comedy"

    @responses.activate
    def test_search_with_missing_artwork_falls_back(self):
        responses.add(
            responses.GET,
            settings.ITUNES_SEARCH_URL,
            json=SAMPLE_ITUNES_SEARCH_RESPONSE,
            status=200,
        )

        results = search_itunes("test")

        assert results[1].artwork_url == "https://example.com/art2.jpg"

    @responses.activate
    def test_search_empty_results(self):
        responses.add(
            responses.GET,
            settings.ITUNES_SEARCH_URL,
            json={"resultCount": 0, "results": []},
            status=200,
        )

        results = search_itunes("nonexistent")

        assert results == []


class TestLookupItunes:
    @responses.activate
    def test_lookup_returns_podcast(self):
        responses.add(
            responses.GET,
            settings.ITUNES_SEARCH_URL.replace("/search", "/lookup"),
            json={
                "resultCount": 1,
                "results": [SAMPLE_ITUNES_SEARCH_RESPONSE["results"][0]],
            },
            status=200,
        )

        result = lookup_itunes("12345")

        assert result is not None
        assert result.itunes_id == "12345"
        assert result.title == "Test Podcast"

    @responses.activate
    def test_lookup_not_found_returns_none(self):
        responses.add(
            responses.GET,
            settings.ITUNES_SEARCH_URL.replace("/search", "/lookup"),
            json={"resultCount": 0, "results": []},
            status=200,
        )

        result = lookup_itunes("99999")

        assert result is None


class TestParseRssFeed:
    @responses.activate
    def test_parse_feed_extracts_episodes(self):
        responses.add(
            responses.GET,
            "https://example.com/feed.xml",
            body=SAMPLE_RSS_FEED,
            status=200,
        )

        result = parse_rss_feed("https://example.com/feed.xml")

        assert result.title == "Test Podcast"
        assert result.description == "A test podcast description"
        assert len(result.episodes) == 2

    @responses.activate
    def test_parse_feed_extracts_episode_details(self):
        responses.add(
            responses.GET,
            "https://example.com/feed.xml",
            body=SAMPLE_RSS_FEED,
            status=200,
        )

        result = parse_rss_feed("https://example.com/feed.xml")
        ep = result.episodes[0]

        assert ep.guid == "episode-1"
        assert ep.title == "Episode One"
        assert ep.description == "First episode description"
        assert ep.audio_url == "https://example.com/ep1.mp3"
        assert ep.duration == 5445  # 1:30:45 = 5445 seconds

    @responses.activate
    def test_parse_feed_extracts_artwork_url(self):
        responses.add(
            responses.GET,
            "https://example.com/feed.xml",
            body=SAMPLE_RSS_FEED,
            status=200,
        )

        result = parse_rss_feed("https://example.com/feed.xml")

        assert result.artwork_url == "https://example.com/podcast-artwork.jpg"

    @responses.activate
    def test_parse_feed_without_artwork_returns_none(self):
        feed_without_artwork = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Test Podcast</title>
    <description>A test podcast</description>
    <item>
      <guid>episode-1</guid>
      <title>Episode One</title>
      <enclosure url="https://example.com/ep1.mp3" type="audio/mpeg"/>
    </item>
  </channel>
</rss>
"""
        responses.add(
            responses.GET,
            "https://example.com/feed2.xml",
            body=feed_without_artwork,
            status=200,
        )

        result = parse_rss_feed("https://example.com/feed2.xml")

        assert result.artwork_url is None


class TestParseDuration:
    def test_hms_format(self):
        assert _parse_duration("01:30:45") == 5445

    def test_ms_format(self):
        assert _parse_duration("45:30") == 2730

    def test_seconds_only(self):
        assert _parse_duration("3600") == 3600

    def test_none_returns_none(self):
        assert _parse_duration(None) is None

    def test_invalid_returns_none(self):
        assert _parse_duration("invalid") is None


class TestParseDate:
    def test_rfc2822_format(self):
        result = _parse_date("Mon, 25 Dec 2025 10:00:00 GMT")
        assert result is not None
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 25

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_invalid_returns_none(self):
        assert _parse_date("not a date") is None
