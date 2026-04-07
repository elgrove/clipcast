import responses


@responses.activate
def test_search_itunes(client):
    responses.add(
        responses.GET,
        "https://itunes.apple.com/search",
        json={
            "resultCount": 2,
            "results": [
                {
                    "collectionId": 100,
                    "collectionName": "Podcast One",
                    "artistName": "Artist One",
                    "feedUrl": "https://example.com/feed1",
                    "artworkUrl600": "https://example.com/art1.jpg",
                    "primaryGenreName": "Comedy",
                },
                {
                    "collectionId": 200,
                    "collectionName": "Podcast Two",
                    "artistName": "Artist Two",
                    "feedUrl": "https://example.com/feed2",
                    "artworkUrl100": "https://example.com/art2.jpg",
                    "primaryGenreName": "News",
                },
            ],
        },
    )

    response = client.get("/api/search/itunes?q=test")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 2
    assert results[0]["title"] == "Podcast One"
    assert results[0]["itunes_id"] == "100"
    assert results[1]["artwork_url"] == "https://example.com/art2.jpg"


def test_search_itunes_empty_query(client):
    response = client.get("/api/search/itunes?q=")
    assert response.status_code == 422
