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


