from datetime import datetime, timezone

from marquee.models import MovieCandidate
from marquee.tmdb.curator import (
    discover,
    enrich,
    extract_digital_date,
    pick_best_trailer,
    rank_trailers,
)


class FakeClient:
    def __init__(self, lists=None, details=None):
        self._lists = lists or {}
        self._details = details or {}

    def list_movies(self, source, region, language, pages=3):
        return self._lists.get(source, [])

    def movie_details(self, tmdb_id, language, append=("videos", "release_dates", "images")):
        return self._details[tmdb_id]


def _video(key, vtype="Trailer", official=True, size=1080, lang="en", published="2026-01-01T00:00:00.000Z"):
    return {
        "key": key,
        "site": "YouTube",
        "type": vtype,
        "official": official,
        "size": size,
        "iso_639_1": lang,
        "published_at": published,
    }


# ---- pick_best_trailer ordering ----

def test_trailer_preferred_over_teaser():
    videos = [_video("teaser", vtype="Teaser", size=1080), _video("trailer", size=720)]
    assert pick_best_trailer(videos, "en-US").key == "trailer"


def test_official_preferred_over_unofficial():
    videos = [_video("unoff", official=False, size=1080), _video("off", official=True, size=720)]
    assert pick_best_trailer(videos, "en-US").key == "off"


def test_language_match_preferred():
    videos = [_video("fr", lang="fr", size=1080), _video("en", lang="en", size=720)]
    assert pick_best_trailer(videos, "en-US").key == "en"


def test_larger_size_preferred_then_newer():
    videos = [
        _video("small", size=720, published="2026-05-01T00:00:00.000Z"),
        _video("big", size=1080, published="2026-01-01T00:00:00.000Z"),
    ]
    assert pick_best_trailer(videos, "en-US").key == "big"


def test_newest_published_breaks_tie():
    videos = [
        _video("old", published="2026-01-01T00:00:00.000Z"),
        _video("new", published="2026-03-01T00:00:00.000Z"),
    ]
    assert pick_best_trailer(videos, "en-US").key == "new"


def test_vimeo_is_included_as_candidate():
    # Vimeo used to be silently discarded. It's free extra coverage now, so
    # a Vimeo-only video list must still yield a pick.
    vimeo = {
        "key": "v",
        "site": "Vimeo",
        "type": "Trailer",
        "official": True,
        "size": 1080,
        "iso_639_1": "en",
        "published_at": "",
    }
    assert pick_best_trailer([vimeo], "en-US").key == "v"


def test_unsupported_site_still_filtered_out():
    other = {
        "key": "o",
        "site": "SomeOtherSite",
        "type": "Trailer",
        "official": True,
        "size": 1080,
        "iso_639_1": "en",
        "published_at": "",
    }
    assert pick_best_trailer([other], "en-US") is None


def test_no_videos_returns_none():
    assert pick_best_trailer([], "en-US") is None


# ---- rank_trailers: full candidate list ----


def test_rank_trailers_returns_full_ordered_list():
    videos = [_video("teaser", vtype="Teaser", size=1080), _video("trailer", size=720)]
    ranked = rank_trailers(videos, "en-US")
    assert [v.key for v in ranked] == ["trailer", "teaser"]


def test_rank_trailers_official_first():
    videos = [_video("unoff", official=False, size=1080), _video("off", official=True, size=720)]
    ranked = rank_trailers(videos, "en-US")
    assert [v.key for v in ranked] == ["off", "unoff"]


def test_rank_trailers_larger_size_first():
    videos = [_video("small", size=720), _video("big", size=1080)]
    ranked = rank_trailers(videos, "en-US")
    assert [v.key for v in ranked] == ["big", "small"]


def test_rank_trailers_includes_vimeo_candidate():
    vimeo = {
        "key": "v",
        "site": "Vimeo",
        "type": "Trailer",
        "official": True,
        "size": 1080,
        "iso_639_1": "en",
        "published_at": "2026-01-01T00:00:00.000Z",
    }
    yt = _video("yt", size=720)
    ranked = rank_trailers([vimeo, yt], "en-US")
    assert {v.key for v in ranked} == {"v", "yt"}
    # bigger size wins the top slot regardless of site
    assert ranked[0].key == "v"
    assert ranked[0].site == "Vimeo"


def test_rank_trailers_empty_for_no_candidates():
    assert rank_trailers([], "en-US") == []


def test_pick_best_trailer_returns_top_of_rank_trailers():
    videos = [_video("teaser", vtype="Teaser", size=1080), _video("trailer", size=720)]
    assert pick_best_trailer(videos, "en-US").key == rank_trailers(videos, "en-US")[0].key
    assert pick_best_trailer(videos, "en-US").key == "trailer"


# ---- extract_digital_date full fallback chain ----

def _rd(country, entries):
    return {"iso_3166_1": country, "release_dates": entries}


def _entry(vtype, date, certification=None):
    e = {"type": vtype, "release_date": date}
    if certification is not None:
        e["certification"] = certification
    return e


def test_digital_region_takes_priority():
    rd = [
        _rd("US", [_entry(3, "2026-01-01T00:00:00.000Z"), _entry(4, "2026-03-15T00:00:00.000Z")]),
        _rd("GB", [_entry(4, "2026-02-01T00:00:00.000Z")]),
    ]
    dt, src = extract_digital_date(rd, "US")
    assert src == "region"
    assert dt == datetime(2026, 3, 15, tzinfo=timezone.utc)


def test_digital_falls_back_to_us():
    rd = [_rd("US", [_entry(4, "2026-05-01T00:00:00.000Z")])]
    dt, src = extract_digital_date(rd, "DE")
    assert src == "us"
    assert dt == datetime(2026, 5, 1, tzinfo=timezone.utc)


def test_digital_falls_back_to_global_earliest():
    rd = [
        _rd("FR", [_entry(4, "2026-06-10T00:00:00.000Z")]),
        _rd("JP", [_entry(4, "2026-06-01T00:00:00.000Z")]),
    ]
    dt, src = extract_digital_date(rd, "US")
    assert src == "global"
    assert dt == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_digital_falls_back_to_physical():
    rd = [_rd("US", [_entry(5, "2026-07-01T00:00:00.000Z")])]
    dt, src = extract_digital_date(rd, "US")
    assert src == "physical"
    assert dt == datetime(2026, 7, 1, tzinfo=timezone.utc)


def test_digital_falls_back_to_tv():
    rd = [_rd("US", [_entry(6, "2026-08-01T00:00:00.000Z")])]
    dt, src = extract_digital_date(rd, "US")
    assert src == "tv"
    assert dt == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_digital_none_keeps():
    rd = [_rd("US", [_entry(3, "2026-01-01T00:00:00.000Z")])]
    dt, src = extract_digital_date(rd, "US")
    assert dt is None
    assert src == "none"


# ---- discover ----

def test_discover_dedupes_and_ranks_top_n():
    lists = {
        "upcoming": [
            {"id": 1, "title": "A", "popularity": 10, "release_date": "2026-01-01", "overview": "a"},
            {"id": 2, "title": "B", "popularity": 50, "release_date": "2026-02-01", "overview": "b"},
        ],
        "now_playing": [
            {"id": 2, "title": "B", "popularity": 50, "release_date": "2026-02-01", "overview": "b"},
            {"id": 3, "title": "C", "popularity": 30, "release_date": "2026-03-01", "overview": "c"},
        ],
    }
    cands = discover(FakeClient(lists), ["upcoming", "now_playing"], "US", "en-US", count=2)
    assert [c.tmdb_id for c in cands] == [2, 3]
    assert cands[0].year == 2026
    assert cands[0].source == "upcoming"  # first source that surfaced id=2


# ---- enrich ----

def test_enrich_maps_all_fields():
    details = {
        5: {
            "id": 5,
            "title": "Movie Five",
            "overview": "ov",
            "popularity": 42.0,
            "runtime": 120,
            "release_date": "2026-04-01",
            "poster_path": "/p.jpg",
            "backdrop_path": "/b.jpg",
            "genres": [{"name": "Action"}, {"name": "Drama"}],
            "production_companies": [{"name": "Studio X"}],
            "videos": {"results": [_video("yt5")]},
            "release_dates": {
                "results": [
                    _rd("US", [_entry(4, "2026-06-01T00:00:00.000Z", certification="PG-13")])
                ]
            },
        }
    }
    cand = MovieCandidate(
        tmdb_id=5,
        title="Movie Five",
        year=2026,
        overview="ov",
        popularity=42.0,
        poster_path="/p.jpg",
        backdrop_path="/b.jpg",
        source="upcoming",
        release_date="2026-04-01",
    )
    em = enrich(FakeClient(details=details), cand, "US", "en-US")
    assert em.youtube_key == "yt5"
    assert em.trailer is not None and em.trailer.key == "yt5"
    assert [c.key for c in em.trailer_candidates] == ["yt5"]
    assert em.digital_date == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert em.digital_date_source == "region"
    assert em.genres == ["Action", "Drama"]
    assert em.studios == ["Studio X"]
    assert em.certification == "PG-13"
    assert em.runtime == 120
    assert em.premiere_date == "2026-04-01"
    assert em.source == "upcoming"


def test_enrich_no_trailer_leaves_youtube_key_none():
    details = {
        6: {
            "id": 6,
            "title": "No Trailer",
            "overview": "",
            "popularity": 1.0,
            "runtime": None,
            "release_date": "2026-04-01",
            "genres": [],
            "production_companies": [],
            "videos": {"results": []},
            "release_dates": {"results": []},
        }
    }
    cand = MovieCandidate(
        tmdb_id=6,
        title="No Trailer",
        year=2026,
        overview="",
        popularity=1.0,
        poster_path=None,
        backdrop_path=None,
        source="popular",
        release_date="2026-04-01",
    )
    em = enrich(FakeClient(details=details), cand, "US", "en-US")
    assert em.youtube_key is None
    assert em.trailer is None
    assert em.trailer_candidates == []
    assert em.digital_date is None
    assert em.digital_date_source == "none"
