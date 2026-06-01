from datetime import datetime

import responses

from app.models import (
    AdBreak,
    Advert,
    ClippingReport,
    PodcastEpisode,
    PodcastShow,
    TranscriptionSegment,
)
from app.services import rss


def _make_episode(session, image_url="https://example.com/ep1.jpg"):
    podcast = PodcastShow(
        title="Test Show",
        itunes_id="ep-test",
        source_rss_url="https://example.com/feed.xml",
        path_directory="Test_Show",
    )
    session.add(podcast)
    session.commit()
    session.refresh(podcast)

    episode = PodcastEpisode(
        podcast_id=podcast.id,
        guid="guid-1",
        title="Episode One",
        description="<p>Hello <b>world</b></p>",
        source_audio_url="https://example.com/ep1.mp3",
        image_url=image_url,
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)
    return podcast, episode


def test_get_episode_detail(client, session):
    _, episode = _make_episode(session)
    episode.ad_breaks = [
        AdBreak(
            start_time="00:01:00.000",
            end_time="00:02:30.000",
            adverts=[Advert(start_time="00:01:00.000", end_time="00:02:30.000", advert_for="Acme")],
        )
    ]
    episode.transcription = [TranscriptionSegment(start_time=0.0, end_time=2.0, text="hi")]
    session.add(episode)
    session.commit()

    response = client.get(f"/api/episodes/{episode.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Episode One"
    assert data["podcast_title"] == "Test Show"
    assert data["image_url"] == "https://example.com/ep1.jpg"
    assert data["podcast_image_url"] is None
    assert data["audio_url"] is None
    assert data["has_transcription"] is True
    assert data["ad_break_count"] == 1
    assert len(data["ad_breaks"]) == 1
    assert data["ad_breaks"][0]["adverts"][0]["advert_for"] == "Acme"
    assert data["report"] is None


def test_get_episode_not_found(client):
    assert client.get("/api/episodes/does-not-exist").status_code == 404


def test_get_episode_includes_report(client, session):
    _, episode = _make_episode(session)
    report = ClippingReport(episode_id=episode.id, downloaded_at=datetime.utcnow())
    session.add(report)
    session.commit()

    data = client.get(f"/api/episodes/{episode.id}").json()
    assert data["report"] is not None
    assert data["report"]["episode_id"] == episode.id
    assert data["report"]["status"] == data["clipping_status"]


def test_episode_transcript(client, session):
    _, episode = _make_episode(session)
    episode.transcription = [
        TranscriptionSegment(start_time=0.0, end_time=2.5, text="hello"),
        TranscriptionSegment(start_time=2.5, end_time=5.0, text="world"),
    ]
    session.add(episode)
    session.commit()

    response = client.get(f"/api/episodes/{episode.id}/transcript")
    assert response.status_code == 200
    segments = response.json()
    assert len(segments) == 2
    assert segments[0]["text"] == "hello"
    assert segments[0]["start_time"] == 0.0


def test_episode_transcript_empty(client, session):
    _, episode = _make_episode(session)
    response = client.get(f"/api/episodes/{episode.id}/transcript")
    assert response.status_code == 200
    assert response.json() == []


def test_episode_transcript_not_found(client):
    assert client.get("/api/episodes/nope/transcript").status_code == 404


def test_episode_status_includes_refined_at(client, session):
    _, episode = _make_episode(session)
    report = ClippingReport(episode_id=episode.id, downloaded_at=datetime.utcnow())
    session.add(report)
    session.commit()

    response = client.get(f"/api/episodes/{episode.id}/status")
    assert response.status_code == 200
    data = response.json()
    assert data["episode_id"] == episode.id
    assert "refined_at" in data
    assert data["refined_at"] is None


def test_entry_artwork_url_extraction():
    assert rss._get_entry_artwork_url({"itunes_image": "https://x/a.jpg"}) == "https://x/a.jpg"
    assert (
        rss._get_entry_artwork_url({"itunes_image": {"href": "https://x/b.jpg"}})
        == "https://x/b.jpg"
    )
    assert rss._get_entry_artwork_url({"image": {"href": "https://x/c.jpg"}}) == "https://x/c.jpg"
    assert rss._get_entry_artwork_url({"image": {"url": "https://x/d.jpg"}}) == "https://x/d.jpg"
    assert (
        rss._get_entry_artwork_url({"media_thumbnail": [{"url": "https://x/e.jpg"}]})
        == "https://x/e.jpg"
    )
    assert rss._get_entry_artwork_url({}) is None


@responses.activate
def test_parse_rss_feed_extracts_episode_artwork():
    feed = """<?xml version="1.0"?>
    <rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
      <channel>
        <title>Show</title>
        <item>
          <title>Ep 1</title>
          <guid>guid-1</guid>
          <enclosure url="https://example.com/ep1.mp3" type="audio/mpeg" length="1"/>
          <media:thumbnail url="https://example.com/ep1-art.jpg"/>
        </item>
      </channel>
    </rss>"""
    responses.add(
        responses.GET,
        "https://example.com/feed.xml",
        body=feed,
        content_type="application/rss+xml",
    )

    result = rss.parse_rss_feed("https://example.com/feed.xml")
    assert len(result.episodes) == 1
    assert result.episodes[0].artwork_url == "https://example.com/ep1-art.jpg"
