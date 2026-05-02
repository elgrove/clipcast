import responses


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
def test_add_podcast_ai_mode(client, session):
    responses.add(responses.GET, "https://itunes.apple.com/lookup", json=_itunes_result())

    response = client.post("/api/podcasts", json={"itunes_id": "123456", "clip_mode": "ai"})
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Podcast"
    assert data["clip_mode"] == "ai"


@responses.activate
def test_add_podcast_off_mode(client, session):
    responses.add(responses.GET, "https://itunes.apple.com/lookup", json=_itunes_result(999))

    response = client.post("/api/podcasts", json={"itunes_id": "999", "clip_mode": "off"})
    assert response.status_code == 201
    assert response.json()["clip_mode"] == "off"


@responses.activate
def test_add_podcast_acast_mode_explicit(client, session):
    responses.add(responses.GET, "https://itunes.apple.com/lookup", json=_itunes_result(777))

    response = client.post("/api/podcasts", json={"itunes_id": "777", "clip_mode": "acast"})
    assert response.status_code == 201
    assert response.json()["clip_mode"] == "acast"


@responses.activate
def test_add_podcast_auto_upgrades_to_acast(client, session):
    """Server auto-upgrades to acast when feed is feeds.acast.com and client sent default ai."""
    responses.add(
        responses.GET,
        "https://itunes.apple.com/lookup",
        json=_itunes_result(888, feed_url="https://feeds.acast.com/public/shows/my-show"),
    )
    response = client.post("/api/podcasts", json={"itunes_id": "888"})
    assert response.status_code == 201
    assert response.json()["clip_mode"] == "acast"


@responses.activate
def test_add_duplicate_podcast(client, session):
    responses.add(responses.GET, "https://itunes.apple.com/lookup", json=_itunes_result())
    client.post("/api/podcasts", json={"itunes_id": "123456"})

    response = client.post("/api/podcasts", json={"itunes_id": "123456"})
    assert response.status_code == 409


def test_list_podcasts_empty(client):
    response = client.get("/api/podcasts")
    assert response.status_code == 200
    assert response.json() == []


@responses.activate
def test_list_podcasts(client, session):
    responses.add(
        responses.GET,
        "https://itunes.apple.com/lookup",
        json=_itunes_result(999),
    )
    client.post("/api/podcasts", json={"itunes_id": "999", "clip_mode": "off"})

    response = client.get("/api/podcasts")
    assert response.status_code == 200
    podcasts = response.json()
    assert len(podcasts) == 1
    assert podcasts[0]["title"] == "Test Podcast"
    assert podcasts[0]["clip_mode"] == "off"


@responses.activate
def test_update_podcast_clip_mode(client, session):
    responses.add(responses.GET, "https://itunes.apple.com/lookup", json=_itunes_result(111))
    create_resp = client.post("/api/podcasts", json={"itunes_id": "111", "clip_mode": "ai"})
    podcast_id = create_resp.json()["id"]

    response = client.patch(f"/api/podcasts/{podcast_id}", json={"clip_mode": "acast"})
    assert response.status_code == 200
    assert response.json()["clip_mode"] == "acast"

    response = client.patch(f"/api/podcasts/{podcast_id}", json={"clip_mode": "off"})
    assert response.status_code == 200
    assert response.json()["clip_mode"] == "off"


@responses.activate
def test_delete_podcast(client, session):
    responses.add(responses.GET, "https://itunes.apple.com/lookup", json=_itunes_result(222))
    create_resp = client.post("/api/podcasts", json={"itunes_id": "222"})
    podcast_id = create_resp.json()["id"]

    response = client.delete(f"/api/podcasts/{podcast_id}")
    assert response.status_code == 204

    response = client.get("/api/podcasts")
    assert response.json() == []


def test_clip_mode_migration(tmp_path, monkeypatch):
    """Pre-existing has_ads rows are backfilled to clip_mode correctly."""
    import sqlite3

    from sqlmodel import Session, create_engine

    from app.config import Settings

    db_path = tmp_path / "migrate.db"
    podcasts_dir = tmp_path / "podcasts"
    podcasts_dir.mkdir(exist_ok=True)

    test_settings = Settings(
        database_path=str(db_path),
        podcasts_dir=str(podcasts_dir),
        redis_url="redis://localhost:6379/15",
    )
    monkeypatch.setattr("app.config.settings", test_settings)

    # Create legacy schema (without clip_mode column) with has_ads data
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE podcast_shows ("
        "id TEXT PRIMARY KEY, title TEXT, description TEXT, itunes_id TEXT UNIQUE,"
        "source_rss_url TEXT, path_directory TEXT, has_ads INTEGER,"
        "initial_sync_completed INTEGER DEFAULT 0,"
        "cleanup_keep_days INTEGER, cleanup_keep_count INTEGER, custom_prompt TEXT DEFAULT '',"
        "created_at TEXT, updated_at TEXT"
        ")"
    )
    conn.execute(
        "INSERT INTO podcast_shows (id, title, description, itunes_id, source_rss_url,"
        " path_directory, has_ads, created_at, updated_at) VALUES"
        " ('a', 'Show A', '', '1', 'http://a', 'show_a', 1, datetime('now'), datetime('now')),"
        " ('b', 'Show B', '', '2', 'http://b', 'show_b', 0, datetime('now'), datetime('now'))"
    )
    conn.execute(
        "CREATE TABLE podcast_episodes (id TEXT PRIMARY KEY, podcast_id TEXT, guid TEXT,"
        "title TEXT, description TEXT, published_at TEXT, duration INTEGER,"
        "source_audio_url TEXT, stored_filename TEXT DEFAULT '', cleaned_at TEXT,"
        "ads TEXT DEFAULT '[]', transcription TEXT DEFAULT '[]', created_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE ai_models (id TEXT PRIMARY KEY, name TEXT UNIQUE, provider TEXT,"
        "host TEXT, is_preset INTEGER, input_price REAL, output_price REAL,"
        "created_at TEXT, updated_at TEXT)"
    )
    conn.execute(
        "CREATE TABLE config (id TEXT PRIMARY KEY, transcription_model_id TEXT,"
        "analysis_model_id TEXT, gemini_api_key TEXT DEFAULT '')"
    )
    conn.commit()
    conn.close()

    engine = create_engine(test_settings.database_url, connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.database.engine", engine)

    from app.database import init_db

    init_db()

    with Session(engine) as session:
        from sqlmodel import text

        rows = session.exec(text("SELECT id, clip_mode FROM podcast_shows ORDER BY id")).fetchall()

    assert rows[0] == ("a", "ai")  # has_ads=1 → clip_mode='ai'
    assert rows[1] == ("b", "off")  # has_ads=0 → clip_mode='off'
