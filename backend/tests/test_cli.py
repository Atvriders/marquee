from marquee.__main__ import cmd_discover
from marquee.config import load_config


class FakeClient:
    def __init__(self, lists, details):
        self._lists = lists
        self._details = details

    def list_movies(self, source, region, language, pages=3):
        return self._lists.get(source, [])

    def movie_details(self, tmdb_id, language, append=("videos", "release_dates", "images")):
        return self._details[tmdb_id]


def test_cmd_discover_renders_table():
    config = load_config({"TMDB_TOKEN": "x", "COUNT": "2"})
    lists = {
        "upcoming": [
            {"id": 5, "title": "Movie Five", "popularity": 42.0, "release_date": "2026-04-01", "overview": "ov"}
        ],
        "now_playing": [],
    }
    details = {
        5: {
            "id": 5,
            "title": "Movie Five",
            "overview": "ov",
            "popularity": 42.0,
            "runtime": 120,
            "release_date": "2026-04-01",
            "genres": [{"name": "Action"}],
            "production_companies": [{"name": "Studio X"}],
            "videos": {
                "results": [
                    {
                        "key": "yt5",
                        "site": "YouTube",
                        "type": "Trailer",
                        "official": True,
                        "size": 1080,
                        "iso_639_1": "en",
                        "published_at": "2026-01-01T00:00:00.000Z",
                    }
                ]
            },
            "release_dates": {
                "results": [
                    {
                        "iso_3166_1": "US",
                        "release_dates": [
                            {"type": 4, "release_date": "2026-06-01T00:00:00.000Z"}
                        ],
                    }
                ]
            },
        }
    }
    out = cmd_discover(config, client=FakeClient(lists, details))
    assert "Movie Five" in out
    assert "2026-06-01" in out
    assert "region" in out
    assert "5" in out  # tmdb id column


def test_cmd_discover_dash_when_no_digital_date():
    config = load_config({"TMDB_TOKEN": "x", "COUNT": "1"})
    lists = {
        "upcoming": [
            {"id": 8, "title": "Theatrical Only", "popularity": 5.0, "release_date": "2026-04-01", "overview": ""}
        ],
        "now_playing": [],
    }
    details = {
        8: {
            "id": 8,
            "title": "Theatrical Only",
            "overview": "",
            "popularity": 5.0,
            "runtime": 90,
            "release_date": "2026-04-01",
            "genres": [],
            "production_companies": [],
            "videos": {"results": []},
            "release_dates": {
                "results": [
                    {"iso_3166_1": "US", "release_dates": [{"type": 3, "release_date": "2026-04-01T00:00:00.000Z"}]}
                ]
            },
        }
    }
    out = cmd_discover(config, client=FakeClient(lists, details))
    assert "Theatrical Only" in out
    assert "-" in out
    assert "none" in out
