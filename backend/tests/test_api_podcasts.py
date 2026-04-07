import responses


@responses.activate
def test_add_podcast(client, session):
    responses.add(
        responses.GET,
        "https://itunes.apple.com/lookup",
        json={
            "resultCount": 1,
            "results": [
                {
                    "collectionId": 123456,
                    "collectionName": "Test Podcast",
                    "artistName": "Test Artist",
                    "feedUrl": "https://example.com/feed.xml",
                    "artworkUrl600": "https://example.com/image.jpg",
                    "primaryGenreName": "Technology",
                }
            ],
        },
    )

    response = client.post(
        "/api/podcasts",
        json={
            "itunes_id": "123456",
            "has_ads": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test Podcast"
    assert data["itunes_id"] == "123456"
    assert data["has_ads"] is True


@responses.activate
def test_add_duplicate_podcast(client, session):
    # Add first
    responses.add(
        responses.GET,
        "https://itunes.apple.com/lookup",
        json={
            "resultCount": 1,
            "results": [
                {
                    "collectionId": 123456,
                    "collectionName": "Test Podcast",
                    "artistName": "Test Artist",
                    "feedUrl": "https://example.com/feed.xml",
                    "artworkUrl600": "",
                    "primaryGenreName": "Tech",
                }
            ],
        },
    )
    client.post("/api/podcasts", json={"itunes_id": "123456", "has_ads": True})

    # Try duplicate
    response = client.post("/api/podcasts", json={"itunes_id": "123456", "has_ads": True})
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
        json={
            "resultCount": 1,
            "results": [
                {
                    "collectionId": 999,
                    "collectionName": "My Show",
                    "artistName": "Host",
                    "feedUrl": "https://example.com/rss",
                    "artworkUrl600": "",
                    "primaryGenreName": "Comedy",
                }
            ],
        },
    )
    client.post("/api/podcasts", json={"itunes_id": "999", "has_ads": False})

    response = client.get("/api/podcasts")
    assert response.status_code == 200
    podcasts = response.json()
    assert len(podcasts) == 1
    assert podcasts[0]["title"] == "My Show"
    assert podcasts[0]["has_ads"] is False


@responses.activate
def test_update_podcast_toggle_ads(client, session):
    responses.add(
        responses.GET,
        "https://itunes.apple.com/lookup",
        json={
            "resultCount": 1,
            "results": [
                {
                    "collectionId": 111,
                    "collectionName": "Toggle Test",
                    "artistName": "Host",
                    "feedUrl": "https://example.com/rss",
                    "artworkUrl600": "",
                    "primaryGenreName": "News",
                }
            ],
        },
    )
    create_resp = client.post("/api/podcasts", json={"itunes_id": "111", "has_ads": True})
    podcast_id = create_resp.json()["id"]

    response = client.patch(f"/api/podcasts/{podcast_id}", json={"has_ads": False})
    assert response.status_code == 200
    assert response.json()["has_ads"] is False


@responses.activate
def test_delete_podcast(client, session):
    responses.add(
        responses.GET,
        "https://itunes.apple.com/lookup",
        json={
            "resultCount": 1,
            "results": [
                {
                    "collectionId": 222,
                    "collectionName": "Delete Me",
                    "artistName": "Host",
                    "feedUrl": "https://example.com/rss",
                    "artworkUrl600": "",
                    "primaryGenreName": "News",
                }
            ],
        },
    )
    create_resp = client.post("/api/podcasts", json={"itunes_id": "222", "has_ads": True})
    podcast_id = create_resp.json()["id"]

    response = client.delete(f"/api/podcasts/{podcast_id}")
    assert response.status_code == 204

    response = client.get("/api/podcasts")
    assert response.json() == []
