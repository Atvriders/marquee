import sqlite3
from datetime import datetime, timezone

import pytest

from marquee.models import Movie, Status
from marquee.store import Store


def _movie(tmdb_id: int = 1, status: Status = Status.QUEUED, **kw) -> Movie:
    base = dict(
        tmdb_id=tmdb_id,
        title="T",
        year=2026,
        overview="ov",
        runtime=100,
        genres=["Action", "Drama"],
        studios=["Studio"],
        certification="PG-13",
        premiere_date="2026-01-01",
        digital_date=datetime(2026, 6, 1, tzinfo=timezone.utc),
        digital_date_source="region",
        region="US",
        popularity=9.9,
        poster_path="/p.jpg",
        backdrop_path="/b.jpg",
        youtube_key="yt",
        status=status,
        file_path=None,
        folder=None,
        jellyfin_item_id=None,
        pinned=False,
        added_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        expires_at=None,
        last_checked=None,
        error_kind=None,
        error_msg=None,
    )
    base.update(kw)
    return Movie(**base)


def test_upsert_and_get_roundtrip(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie())
    got = store.get_movie(1)
    assert got is not None
    assert got.title == "T"
    assert got.genres == ["Action", "Drama"]
    assert got.studios == ["Studio"]
    assert got.digital_date == datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert got.added_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert got.status is Status.QUEUED
    assert got.pinned is False


def test_upsert_replaces_existing(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1, popularity=1.0))
    store.upsert_movie(_movie(1, popularity=5.0))
    assert store.get_movie(1).popularity == 5.0
    assert len(store.list_movies()) == 1


def test_get_missing_returns_none(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    assert store.get_movie(999) is None


def test_list_status_filter(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1, status=Status.READY, popularity=2.0))
    store.upsert_movie(_movie(2, status=Status.FAILED, popularity=9.0))
    ready = store.list_movies([Status.READY])
    assert [m.tmdb_id for m in ready] == [1]
    all_movies = store.list_movies()
    assert [m.tmdb_id for m in all_movies] == [2, 1]  # popularity desc


def test_set_status_and_extra_fields(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1))
    store.set_status(1, Status.READY, file_path="/x.mkv", folder="/f")
    got = store.get_movie(1)
    assert got.status is Status.READY
    assert got.file_path == "/x.mkv"
    assert got.folder == "/f"


def test_set_status_serializes_datetime_field(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1))
    when = datetime(2026, 9, 9, tzinfo=timezone.utc)
    store.set_status(1, Status.READY, last_checked=when)
    assert store.get_movie(1).last_checked == when


def test_set_status_rejects_unknown_column(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1))
    with pytest.raises(ValueError, match="unknown movie column: bogus"):
        store.set_status(1, Status.READY, bogus="x")


def test_set_pinned_toggle(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1))
    store.set_pinned(1, True)
    assert store.get_movie(1).pinned is True
    store.set_pinned(1, False)
    assert store.get_movie(1).pinned is False


def test_delete_movie(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1))
    store.delete_movie(1)
    assert store.get_movie(1) is None


def test_activity_log_recent_newest_first(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.log("info", "discover", "found 5", tmdb_id=1)
    store.log("error", "download", "failed", tmdb_id=2)
    recent = store.recent_activity(limit=10)
    assert len(recent) == 2
    assert recent[0]["event"] == "download"
    assert recent[0]["tmdb_id"] == 2
    assert recent[0]["level"] == "error"


def test_close_closes_underlying_connection(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    store.upsert_movie(_movie(1))
    store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store.get_movie(1)


def test_settings_roundtrip(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    assert store.get_setting("count") is None
    store.set_setting("count", "25")
    assert store.get_setting("count") == "25"
    store.set_setting("count", "30")
    assert store.get_setting("count") == "30"
    store.set_setting("region", "GB")
    assert store.all_settings() == {"count": "30", "region": "GB"}
