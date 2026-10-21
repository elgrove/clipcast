from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app import tasks
from app.models import (
    AdBreak,
    AnalysisReport,
    ClippingReport,
    PodcastEpisode,
    PodcastShow,
    TranscriptionReport,
)
from app.routers.episodes import list_episodes
from app.services import acast, audio, checkpoints, feed, rss
from app.services.checkpoints import CheckpointProvider
from app.services.providers import Transcription


def make_episodes(session, count=1):
    podcast = PodcastShow(
        title="Efficiency",
        itunes_id="efficiency",
        source_rss_url="https://example.test/rss",
        path_directory="efficiency",
        initial_sync_completed=True,
    )
    session.add(podcast)
    episodes = [
        PodcastEpisode(
            podcast_id=podcast.id,
            guid=str(i),
            title=f"Episode {i}",
            transcription_json='[{"start_time":0,"end_time":1,"text":"hello"}]',
        )
        for i in range(count)
    ]
    session.add_all(episodes)
    session.commit()
    return podcast, episodes


def test_episode_list_uses_four_queries_without_loading_transcripts(session):
    podcast, episodes = make_episodes(session, 50)
    session.add_all([ClippingReport(episode_id=ep.id) for ep in episodes])
    session.commit()
    podcast_id = podcast.id
    statements = []
    engine = session.get_bind()

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        with Session(engine) as fresh:
            result = list_episodes(podcast_id, 1, 50, "all", fresh)
            assert len(result["episodes"]) == 50
            assert all(ep.has_transcription for ep in result["episodes"])
            assert all(
                "transcription_json" not in ep.__dict__
                for ep in fresh.identity_map.values()
                if isinstance(ep, PodcastEpisode)
            )
        assert len(statements) == 4
    finally:
        event.remove(engine, "before_cursor_execute", record)
    with engine.connect() as conn:
        plans = conn.exec_driver_sql(
            "EXPLAIN QUERY PLAN SELECT * FROM podcast_episodes WHERE podcast_id='x' ORDER BY published_at DESC LIMIT 50"
        ).all()
        assert any("ix_episode_podcast_published" in str(row) for row in plans)


def test_batch_status_uses_latest_report_and_omits_logs(client, session):
    _, episodes = make_episodes(session, 2)
    old = ClippingReport(
        episode_id=episodes[0].id, queued_at=datetime.utcnow() - timedelta(days=1), logs="large"
    )
    new = ClippingReport(episode_id=episodes[0].id, active=False, exceptions_json='["failed"]')
    session.add_all([old, new])
    session.commit()
    response = client.post(
        "/api/episodes/statuses", json={"episode_ids": [ep.id for ep in episodes]}
    )
    assert response.json() == {episodes[0].id: {"id": new.id, "status": "failed"}}
    assert (
        client.post(
            "/api/episodes/statuses", json={"episode_ids": [str(i) for i in range(201)]}
        ).status_code
        == 422
    )


def test_only_one_pipeline_is_submitted(session, monkeypatch):
    _, episodes = make_episodes(session)
    pipeline = Mock()
    pipeline.apply_async.return_value.id = "queued-task"
    factory = Mock(return_value=pipeline)
    monkeypatch.setattr(tasks, "chain", factory)
    first = tasks.queue_episode_for_clipping(session, episodes[0])
    second = tasks.queue_episode_for_clipping(session, episodes[0])
    assert first.id == second.id
    assert pipeline.apply_async.call_count == 1
    with Session(session.get_bind()) as other:
        other.add(ClippingReport(episode_id=episodes[0].id, active=True))
        with pytest.raises(IntegrityError):
            other.commit()


def test_claim_released_on_publish_failure(session, monkeypatch):
    _, episodes = make_episodes(session)
    pipeline = Mock()
    pipeline.apply_async.side_effect = RuntimeError("broker unavailable")
    monkeypatch.setattr(tasks, "chain", Mock(return_value=pipeline))
    with pytest.raises(RuntimeError):
        tasks.queue_episode_for_clipping(session, episodes[0])
    report = session.exec(select(ClippingReport)).one()
    assert not report.active
    assert report.status == "failed"


def test_download_completion_releases_claim_without_marking_clipped(session, monkeypatch):
    _, episodes = make_episodes(session)
    report = ClippingReport(
        episode_id=episodes[0].id, active=True, download_only=True, downloaded_at=datetime.utcnow()
    )
    session.add(report)
    session.commit()
    monkeypatch.setattr(tasks, "engine", session.get_bind())
    tasks.release_completed_job(
        sender=SimpleNamespace(name="app.tasks.task_download"),
        args=[episodes[0].id, report.id],
        state="SUCCESS",
    )
    session.refresh(report)
    assert not report.active
    assert report.edited_at is None
    assert report.status == "completed"


def test_sync_fetches_feed_once(session, monkeypatch):
    podcast, _ = make_episodes(session)
    podcast.clip_mode = "off"
    session.add(podcast)
    session.commit()
    data = rss.RSSPodcast(
        title="Efficiency",
        description="",
        artwork_url=None,
        episodes=[
            rss.RSSEpisode(
                guid="0",
                title="Changed",
                description="",
                published_at=None,
                duration=None,
                audio_url="https://example.test/audio",
            )
        ],
    )
    fetch = Mock(return_value=data)
    monkeypatch.setattr(tasks, "parse_rss_feed", fetch)
    monkeypatch.setattr(tasks, "engine", session.get_bind())
    assert tasks.sync_and_process_new_episodes() == {podcast.id: 0}
    assert fetch.call_count == 1
    session.expire_all()
    assert session.exec(select(PodcastEpisode)).one().title == "Changed"


def test_checkpoint_reuses_transcription_and_successful_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(checkpoints, "settings", SimpleNamespace(podcasts_path=tmp_path))
    provider = Mock()
    provider.transcribe.return_value = Transcription(segments=[])
    provider.analyse_ads.side_effect = [
        [AdBreak(start_time="0", end_time="1")],
        RuntimeError("temporary"),
        [],
    ]
    cached = CheckpointProvider(provider, "report")
    audio_path = tmp_path / "audio.mp3"
    audio_path.write_bytes(b"audio")
    transcript = cached.transcribe(audio_path, TranscriptionReport())
    cached.transcribe(audio_path, TranscriptionReport())
    assert provider.transcribe.call_count == 1
    cached.analyse_ads(transcript, "first", AnalysisReport())
    with pytest.raises(RuntimeError):
        cached.analyse_ads(transcript, "second", AnalysisReport())
    # A new wrapper represents a task retry in another worker process.
    retry = CheckpointProvider(provider, "report")
    assert len(retry.analyse_ads(transcript, "first", AnalysisReport())) == 1
    assert retry.analyse_ads(transcript, "second", AnalysisReport()) == []
    assert provider.analyse_ads.call_count == 3
    audio_path.write_bytes(b"new audio")
    retry.transcribe(audio_path, TranscriptionReport())
    assert provider.transcribe.call_count == 2


def test_ident_across_block_boundary_matches_whole_input(tmp_path, monkeypatch):
    rng = np.random.default_rng(42)
    ident = rng.normal(size=200).astype(np.float32)
    samples = rng.normal(scale=0.02, size=4000).astype(np.float32)
    samples[950:1150] = ident
    samples[2600:2800] = ident
    monkeypatch.setattr(acast, "_load_mono_16k", lambda path: ident)
    monkeypatch.setattr(audio, "iter_mono_blocks", lambda *args: iter([samples.copy()]))
    expected = acast.detect_idents(tmp_path / "unused")
    monkeypatch.setattr(
        audio,
        "iter_mono_blocks",
        lambda *args: iter([samples[i : i + 1000].copy() for i in range(0, len(samples), 1000)]),
    )
    assert acast.detect_idents(tmp_path / "unused") == expected
    assert len(expected[0]) == 2


def test_feed_cache_and_conditional_response(client, session, monkeypatch):
    podcast, _ = make_episodes(session)
    feed._feed_cache.clear()
    generate = Mock(return_value=b"<rss/>")
    monkeypatch.setattr(feed, "generate_podcast_feed", generate)
    first = client.get(f"/feed/{podcast.itunes_id}")
    second = client.get(
        f"/feed/{podcast.itunes_id}", headers={"If-None-Match": first.headers["etag"]}
    )
    assert first.status_code == 200
    assert second.status_code == 304
    assert not second.content
    assert generate.call_count == 1


def test_clipping_during_download_returns_conflict(client, session):
    _, episodes = make_episodes(session)
    session.add(
        ClippingReport(
            episode_id=episodes[0].id,
            active=True,
            download_only=True,
            lease_until=datetime.utcnow() + timedelta(hours=1),
        )
    )
    session.commit()
    response = client.post(f"/api/episodes/{episodes[0].id}/clip")
    assert response.status_code == 409
    assert "Download in progress" in response.json()["detail"]


def test_expired_job_is_replaced_and_old_task_cannot_run(session, monkeypatch):
    _, episodes = make_episodes(session)
    old = ClippingReport(
        episode_id=episodes[0].id, active=True, lease_until=datetime.utcnow() - timedelta(seconds=1)
    )
    session.add(old)
    session.commit()
    monkeypatch.setattr(tasks, "engine", session.get_bind())
    pipeline = Mock()
    pipeline.apply_async.return_value.id = "replacement"
    monkeypatch.setattr(tasks, "chain", Mock(return_value=pipeline))
    new = tasks.queue_episode_for_clipping(session, episodes[0])
    assert new.id != old.id
    with pytest.raises(tasks.Ignore):
        tasks.renew_job_claim(old.id)
    tasks.renew_job_claim(new.id)
    session.refresh(new)
    assert new.lease_until > datetime.utcnow() + timedelta(hours=5)
    assert new.active


def test_retry_retains_claim_and_terminal_failure_releases_it(session, monkeypatch):
    _, episodes = make_episodes(session)
    report = ClippingReport(
        episode_id=episodes[0].id, active=True, lease_until=datetime.utcnow() + timedelta(hours=1)
    )
    session.add(report)
    session.commit()
    monkeypatch.setattr(tasks, "engine", session.get_bind())
    sender = SimpleNamespace(name="app.tasks.task_download")
    tasks.release_completed_job(sender=sender, args=[episodes[0].id, report.id], state="RETRY")
    session.refresh(report)
    assert report.active
    tasks.release_failed_job(
        sender=sender, args=[episodes[0].id, report.id], exception=RuntimeError("failed")
    )
    session.refresh(report)
    assert not report.active
    assert report.status == "failed"


def test_all_task_time_limits_fit_running_lease():
    for name in (
        "task_download",
        "task_transcribe",
        "task_analyse",
        "task_refine_boundaries",
        "task_edit",
        "task_detect_acast_ads",
        "task_scan_acast_ads",
        "task_trim_scan",
    ):
        assert getattr(tasks, name).time_limit < tasks.RUNNING_JOB_LEASE.total_seconds()
