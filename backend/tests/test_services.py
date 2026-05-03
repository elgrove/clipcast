from app.services.editor import parse_time_to_ms


def test_parse_time_to_ms_hhmmss():
    assert parse_time_to_ms("1:30:00") == 5400000


def test_parse_time_to_ms_mmss():
    assert parse_time_to_ms("2:30") == 150000


def test_parse_time_to_ms_seconds():
    assert parse_time_to_ms("90.5") == 90500


def test_parse_time_to_ms_integer():
    assert parse_time_to_ms("60") == 60000


def test_parse_time_to_ms_hhmmss_with_ms():
    assert parse_time_to_ms("0:01:33.000") == 93000
    assert parse_time_to_ms("00:00:13.500") == 13500


# ── Pipeline chain routing ────────────────────────────────────────────────────


def _make_podcast_and_episode(session, clip_mode: str):
    from app.models import PodcastEpisode, PodcastShow

    podcast = PodcastShow(
        title="Test Show",
        itunes_id=f"test-{clip_mode}",
        source_rss_url="https://example.com/feed",
        path_directory="test_show",
        clip_mode=clip_mode,
    )
    session.add(podcast)
    session.commit()
    session.refresh(podcast)

    episode = PodcastEpisode(
        podcast_id=podcast.id,
        guid="ep-001",
        title="Episode 1",
        source_audio_url="https://example.com/ep1.mp3",
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)
    return episode


def _task_names_from_chain(report):
    """Return celery task names from the chain stored in the report's eager execution."""
    # In eager mode the pipeline runs synchronously; we inspect via the report logs
    # and the existence of the report's celery_task_id (not meaningful in eager mode).
    # Instead, patch celery chain to capture task names.
    return report


def _mock_chain(monkeypatch):
    """Return a mock chain factory that captures task names without executing."""
    captured = []

    class _FakeResult:
        id = "mock-task-id"

    class _FakeChain:
        def __init__(self, *tasks):
            for t in tasks:
                captured.append(t.task)

        def apply_async(self):
            return _FakeResult()

    monkeypatch.setattr("app.tasks.chain", lambda *tasks: _FakeChain(*tasks))
    return captured


def test_queue_acast_chain_tasks(session, monkeypatch):
    captured = _mock_chain(monkeypatch)
    episode = _make_podcast_and_episode(session, "acast")

    from app.tasks import queue_episode_for_clipping

    queue_episode_for_clipping(session, episode)

    assert captured == [
        "app.tasks.task_download",
        "app.tasks.task_detect_acast_ads",
        "app.tasks.task_edit",
    ], f"Got: {captured}"


def test_queue_ai_chain_tasks(session, monkeypatch):
    captured = _mock_chain(monkeypatch)
    episode = _make_podcast_and_episode(session, "ai")

    from app.tasks import queue_episode_for_clipping

    queue_episode_for_clipping(session, episode)

    assert captured == [
        "app.tasks.task_download",
        "app.tasks.task_transcribe",
        "app.tasks.task_analyse",
        "app.tasks.task_edit",
    ], f"Got: {captured}"
