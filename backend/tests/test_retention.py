from datetime import datetime, timedelta

import responses
from sqlmodel import select

from app.models import ClippingReport, ClipSource, PodcastEpisode, PodcastShow
from app.tasks import _cleanup_podcast_episodes


def _itunes_result(collection_id=123456, feed_url="https://example.com/feed.xml"):
    return {
        "resultCount": 1,
        "results": [
            {
                "collectionId": collection_id,
                "collectionName": "Test Podcast",
                "artistName": "Test Artist",
                "feedUrl": feed_url,
                "artworkUrl600": "https://example.com/image.jpg",
                "primaryGenreName": "Technology",
            }
        ],
    }


@responses.activate
def test_add_podcast_defaults_to_mixed(client):
    responses.add(
        responses.GET,
        "https://itunes.apple.com/lookup",
        json=_itunes_result(901),
    )
    response = client.post("/api/podcasts", json={"itunes_id": "901"})
    assert response.status_code == 201
    data = response.json()
    assert data["keep_manual_clips"] is True
    assert data["cleanup_keep_count"] == 5
    assert data["cleanup_keep_days"] is None


@responses.activate
def test_add_podcast_archive_disables_cleanup(client):
    responses.add(
        responses.GET,
        "https://itunes.apple.com/lookup",
        json=_itunes_result(902),
    )
    response = client.post(
        "/api/podcasts",
        json={
            "itunes_id": "902",
            "cleanup_keep_count": None,
            "cleanup_keep_days": None,
            "keep_manual_clips": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["cleanup_keep_count"] is None
    assert data["cleanup_keep_days"] is None


def _make_podcast(
    session,
    title="Test Show",
    keep_count=5,
    keep_days=None,
    keep_manual=True,
):
    podcast = PodcastShow(
        title=title,
        itunes_id=title,
        source_rss_url=f"https://example.com/{title}.xml",
        path_directory=f"dir_{title}",
        clip_mode="ai",
        cleanup_keep_count=keep_count,
        cleanup_keep_days=keep_days,
        keep_manual_clips=keep_manual,
    )
    session.add(podcast)
    session.commit()
    session.refresh(podcast)
    return podcast


def _make_episode(session, podcast, idx, clip_source, days_old):
    episode = PodcastEpisode(
        podcast_id=podcast.id,
        guid=f"guid-{idx}",
        title=f"Episode {idx}",
        published_at=datetime.utcnow() - timedelta(days=days_old),
        source_audio_url="https://example.com/audio.mp3",
        clip_source=clip_source,
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)
    report = ClippingReport(episode_id=episode.id, edited_at=datetime.utcnow())
    session.add(report)
    session.commit()
    return episode


def test_mixed_preserves_manual_and_keeps_newest_automatic(session):
    podcast = _make_podcast(session, keep_count=2, keep_manual=True)
    # 2 manual (oldest and newest) + 3 automatic
    _make_episode(session, podcast, 1, ClipSource.AUTOMATIC, days_old=10)
    _make_episode(session, podcast, 2, ClipSource.AUTOMATIC, days_old=9)
    _make_episode(session, podcast, 3, ClipSource.AUTOMATIC, days_old=8)
    _make_episode(session, podcast, 4, ClipSource.MANUAL, days_old=30)
    manual_new = _make_episode(session, podcast, 5, ClipSource.MANUAL, days_old=1)

    cleaned = _cleanup_podcast_episodes(session, podcast)

    assert cleaned == 1
    remaining = session.exec(
        select(PodcastEpisode).where(
            PodcastEpisode.podcast_id == podcast.id,
            PodcastEpisode.cleaned_at.is_(None),
        )
    ).all()
    remaining_guids = {ep.guid for ep in remaining}
    # Newest 2 automatic kept, oldest automatic cleaned, both manual kept
    assert "guid-1" not in remaining_guids
    assert {"guid-2", "guid-3", "guid-4", "guid-5"} == remaining_guids
    assert manual_new.cleaned_at is None


def test_mixed_manual_does_not_consume_slot(session):
    podcast = _make_podcast(session, title="Mixed Slots", keep_count=2, keep_manual=True)
    # Newest episode overall is manual — it must not consume an automatic slot.
    _make_episode(session, podcast, 1, ClipSource.AUTOMATIC, days_old=5)
    _make_episode(session, podcast, 2, ClipSource.AUTOMATIC, days_old=4)
    _make_episode(session, podcast, 3, ClipSource.AUTOMATIC, days_old=3)
    _make_episode(session, podcast, 4, ClipSource.MANUAL, days_old=1)

    cleaned = _cleanup_podcast_episodes(session, podcast)

    assert cleaned == 1
    remaining = session.exec(
        select(PodcastEpisode).where(
            PodcastEpisode.podcast_id == podcast.id,
            PodcastEpisode.cleaned_at.is_(None),
        )
    ).all()
    assert {ep.guid for ep in remaining} == {"guid-2", "guid-3", "guid-4"}


def test_live_includes_manual_in_retention(session):
    podcast = _make_podcast(session, title="Live Show", keep_count=2, keep_manual=False)
    _make_episode(session, podcast, 1, ClipSource.AUTOMATIC, days_old=10)
    _make_episode(session, podcast, 2, ClipSource.MANUAL, days_old=9)
    _make_episode(session, podcast, 3, ClipSource.AUTOMATIC, days_old=8)

    cleaned = _cleanup_podcast_episodes(session, podcast)

    assert cleaned == 1
    remaining = session.exec(
        select(PodcastEpisode).where(
            PodcastEpisode.podcast_id == podcast.id,
            PodcastEpisode.cleaned_at.is_(None),
        )
    ).all()
    assert {ep.guid for ep in remaining} == {"guid-2", "guid-3"}


def test_archive_removes_nothing(session):
    podcast = _make_podcast(
        session, title="Archive Show", keep_count=None, keep_days=None, keep_manual=True
    )
    _make_episode(session, podcast, 1, ClipSource.AUTOMATIC, days_old=100)
    _make_episode(session, podcast, 2, ClipSource.MANUAL, days_old=200)

    assert _cleanup_podcast_episodes(session, podcast) == 0


def test_count_and_days_combine_with_or(session):
    podcast = _make_podcast(
        session,
        title="Or Rules",
        keep_count=1,
        keep_days=7,
        keep_manual=False,
    )
    _make_episode(session, podcast, 1, ClipSource.AUTOMATIC, days_old=30)
    _make_episode(session, podcast, 2, ClipSource.AUTOMATIC, days_old=20)
    _make_episode(session, podcast, 3, ClipSource.AUTOMATIC, days_old=1)

    cleaned = _cleanup_podcast_episodes(session, podcast)

    # guid-3 kept by both rules; guid-1 and guid-2 match neither rule.
    assert cleaned == 2
