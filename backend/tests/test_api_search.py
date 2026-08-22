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
    assert results[0]["ads_by_acast"] is False
    assert results[1]["ads_by_acast"] is False


@responses.activate
def test_search_itunes_acast_feed(client):
    responses.add(
        responses.GET,
        "https://itunes.apple.com/search",
        json={
            "resultCount": 1,
            "results": [
                {
                    "collectionId": 300,
                    "collectionName": "Acast Show",
                    "artistName": "Host",
                    "feedUrl": "https://feeds.acast.com/public/shows/my-show",
                    "artworkUrl600": "",
                    "primaryGenreName": "Comedy",
                }
            ],
        },
    )

    response = client.get("/api/search/itunes?q=acast")
    assert response.status_code == 200
    results = response.json()
    assert results[0]["ads_by_acast"] is True


def test_search_itunes_empty_query(client):
    response = client.get("/api/search/itunes?q=")
    assert response.status_code == 422


FEED_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <title>Feed Show</title>
  <description>From the feed</description>
  <author>Feed Host</author>
  <item><guid>ep1</guid><title>Ep 1</title>
    <enclosure url="https://example.com/ep1.mp3" type="audio/mpeg"/></item>
</channel></rss>"""


@responses.activate
def test_search_by_feed_url(client):
    responses.add(responses.GET, "https://example.com/feed.xml", body=FEED_XML)

    response = client.get("/api/search/itunes?q=https://example.com/feed.xml")
    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["title"] == "Feed Show"
    assert results[0]["itunes_id"] == ""
    assert results[0]["feed_url"] == "https://example.com/feed.xml"


@responses.activate
def test_search_by_feed_url_not_a_feed(client):
    responses.add(responses.GET, "https://example.com/page.html", body="<html></html>")

    response = client.get("/api/search/itunes?q=https://example.com/page.html")
    assert response.status_code == 200
    assert response.json() == []


@responses.activate
def test_add_podcast_by_feed_url(client):
    responses.add(responses.GET, "https://example.com/feed.xml", body=FEED_XML)

    response = client.post("/api/podcasts", json={"feed_url": "https://example.com/feed.xml"})
    assert response.status_code == 201
    podcast = response.json()
    assert podcast["title"] == "Feed Show"
    assert podcast["source_rss_url"] == "https://example.com/feed.xml"
    assert podcast["itunes_id"].startswith("rss-")

    duplicate = client.post("/api/podcasts", json={"feed_url": "https://example.com/feed.xml"})
    assert duplicate.status_code == 409
