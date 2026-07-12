import httpx
import respx

from marquee.tmdb.client import TMDBClient


@respx.mock
def test_bearer_auth_header():
    captured = {}

    def handler(request):
        captured["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"page": 1, "results": [], "total_pages": 1})

    respx.get("https://api.themoviedb.org/3/movie/popular").mock(side_effect=handler)
    TMDBClient("mytoken").list_movies("popular", "US", "en-US", pages=1)
    assert captured["auth"] == "Bearer mytoken"


@respx.mock
def test_list_movies_paginates_and_stops_at_total_pages():
    respx.get("https://api.themoviedb.org/3/movie/upcoming", params={"page": "1"}).mock(
        return_value=httpx.Response(
            200, json={"page": 1, "results": [{"id": 1}], "total_pages": 2}
        )
    )
    page2 = respx.get(
        "https://api.themoviedb.org/3/movie/upcoming", params={"page": "2"}
    ).mock(
        return_value=httpx.Response(
            200, json={"page": 2, "results": [{"id": 2}], "total_pages": 2}
        )
    )
    results = TMDBClient("t").list_movies("upcoming", "US", "en-US", pages=3)
    assert [r["id"] for r in results] == [1, 2]
    assert page2.called


@respx.mock
def test_trending_week_endpoint_mapping():
    route = respx.get("https://api.themoviedb.org/3/trending/movie/week").mock(
        return_value=httpx.Response(200, json={"page": 1, "results": [{"id": 7}], "total_pages": 1})
    )
    results = TMDBClient("t").list_movies("trending_week", "US", "en-US", pages=1)
    assert route.called
    assert results[0]["id"] == 7


@respx.mock
def test_429_retry_after_backoff():
    respx.get("https://api.themoviedb.org/3/movie/now_playing").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "0"}, json={}),
            httpx.Response(200, json={"page": 1, "results": [{"id": 9}], "total_pages": 1}),
        ]
    )
    results = TMDBClient("t").list_movies("now_playing", "US", "en-US", pages=1)
    assert [r["id"] for r in results] == [9]


@respx.mock
def test_movie_details_appends_response():
    captured = {}

    def handler(request):
        captured["append"] = request.url.params.get("append_to_response")
        captured["language"] = request.url.params.get("language")
        return httpx.Response(200, json={"id": 5, "title": "X"})

    respx.get("https://api.themoviedb.org/3/movie/5").mock(side_effect=handler)
    data = TMDBClient("t").movie_details(5, "en-US")
    assert data["title"] == "X"
    assert captured["append"] == "videos,release_dates,images"
    assert captured["language"] == "en-US"


def test_close_closes_underlying_session():
    client = TMDBClient("t")
    assert client._session.is_closed is False
    client.close()
    assert client._session.is_closed is True


@respx.mock
def test_build_image_url_uses_cached_configuration():
    cfg = respx.get("https://api.themoviedb.org/3/configuration").mock(
        return_value=httpx.Response(
            200, json={"images": {"secure_base_url": "https://image.tmdb.org/t/p/"}}
        )
    )
    client = TMDBClient("t")
    assert client.build_image_url("/abc.jpg", "w500") == "https://image.tmdb.org/t/p/w500/abc.jpg"
    client.build_image_url("/def.jpg", "w1280")
    assert cfg.call_count == 1  # /configuration fetched once and cached
