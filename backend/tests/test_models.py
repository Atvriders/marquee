from datetime import datetime, timezone

from marquee.models import (
    EnrichedMovie,
    ErrorKind,
    Movie,
    MovieCandidate,
    Status,
    TrailerVideo,
)


def test_status_and_errorkind_values():
    assert Status.READY.value == "ready"
    assert Status.EXPIRED.value == "expired"
    assert ErrorKind.NO_TRAILER.value == "no_trailer"
    assert ErrorKind.BOT_CHECK.value == "bot_check"


def test_trailer_youtube_url():
    tv = TrailerVideo(
        key="abc123",
        site="YouTube",
        type="Trailer",
        official=True,
        size=1080,
        iso_639_1="en",
        published_at="",
    )
    assert tv.youtube_url == "https://www.youtube.com/watch?v=abc123"


def test_candidate_construction():
    c = MovieCandidate(
        tmdb_id=1,
        title="A",
        year=2026,
        overview="ov",
        popularity=9.9,
        poster_path="/p.jpg",
        backdrop_path=None,
        source="upcoming",
        release_date="2026-01-01",
    )
    assert c.tmdb_id == 1 and c.source == "upcoming"


def test_enriched_defaults():
    em = EnrichedMovie(
        tmdb_id=1,
        title="T",
        year=2026,
        overview="",
        popularity=1.0,
        source="upcoming",
        poster_path=None,
        backdrop_path=None,
        runtime=None,
    )
    assert em.genres == []
    assert em.studios == []
    assert em.digital_date_source == "none"
    assert em.trailer is None
    assert em.youtube_key is None


def test_movie_construction():
    now = datetime.now(timezone.utc)
    m = Movie(
        tmdb_id=1,
        title="T",
        year=2026,
        overview="",
        runtime=100,
        genres=["Action"],
        studios=["Studio"],
        certification="PG-13",
        premiere_date="2026-01-01",
        digital_date=None,
        digital_date_source="none",
        region="US",
        popularity=1.0,
        poster_path=None,
        backdrop_path=None,
        youtube_key=None,
        status=Status.QUEUED,
        file_path=None,
        folder=None,
        jellyfin_item_id=None,
        pinned=False,
        added_at=now,
        expires_at=None,
        last_checked=None,
        error_kind=None,
        error_msg=None,
    )
    assert m.status is Status.QUEUED
    assert m.genres == ["Action"]
    assert m.pinned is False
