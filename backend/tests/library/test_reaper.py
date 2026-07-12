from datetime import UTC, datetime

from marquee.models import Movie, Status
from marquee.library.reaper import Reaper


def mkmovie(**over):
    base = dict(
        tmdb_id=1,
        title="M",
        year=2026,
        overview="",
        runtime=100,
        genres=[],
        studios=[],
        certification=None,
        premiere_date=None,
        digital_date=datetime(2026, 12, 18, 0, 0, tzinfo=UTC),
        digital_date_source="region",
        region="US",
        popularity=1.0,
        poster_path=None,
        backdrop_path=None,
        youtube_key="k",
        status=Status.READY,
        file_path=None,
        folder="/lib/M",
        jellyfin_item_id=None,
        pinned=False,
        added_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=None,
        last_checked=None,
        error_kind=None,
        error_msg=None,
    )
    base.update(over)
    return Movie(**base)


class FakeWriter:
    def __init__(self):
        self.deleted = []

    def delete_movie(self, folder):
        self.deleted.append(folder)


class FakeStore:
    def __init__(self):
        self.status_calls = []
        self.logs = []

    def set_status(self, tmdb_id, status, **fields):
        self.status_calls.append((tmdb_id, status, fields))

    def log(self, level, event, message, tmdb_id=None):
        self.logs.append((level, event, message, tmdb_id))


class FakeJellyfin:
    def __init__(self, found="JELLY9"):
        self.found = found
        self.deleted = []
        self.refreshed = 0
        self.calls = []

    def find_item_by_tmdb(self, tmdb_id):
        self.calls.append(("find", tmdb_id))
        return self.found

    def delete_item(self, item_id):
        self.calls.append(("delete", item_id))
        self.deleted.append(item_id)

    def refresh_library(self):
        self.calls.append(("refresh", None))
        self.refreshed += 1


def reaper(**over):
    kw = dict(
        store=FakeStore(),
        writer=FakeWriter(),
        jellyfin=None,
        now_fn=lambda: datetime(2026, 12, 20, 12, 0, tzinfo=UTC),
        grace_days=0,
        tz="UTC",
        count=50,
    )
    kw.update(over)
    return Reaper(**kw)


def test_find_expired_passed():
    r = reaper()
    assert [m.tmdb_id for m in r.find_expired([mkmovie()])] == [1]


def test_find_expired_pinned_skipped():
    r = reaper()
    assert r.find_expired([mkmovie(pinned=True)]) == []


def test_find_expired_none_date_kept():
    r = reaper()
    assert r.find_expired([mkmovie(digital_date=None)]) == []


def test_find_expired_grace_not_yet():
    r = reaper(grace_days=5)  # expiry end of 2026-12-23, now is 12-20
    assert r.find_expired([mkmovie()]) == []


def test_find_expired_end_of_day_boundary():
    # digital date is today (2026-12-20); expiry is end-of-day, now is noon -> keep
    r = reaper()
    m = mkmovie(digital_date=datetime(2026, 12, 20, 0, 0, tzinfo=UTC))
    assert r.find_expired([m]) == []


def test_expire_no_jellyfin():
    store = FakeStore()
    writer = FakeWriter()
    r = reaper(store=store, writer=writer, jellyfin=None)
    r.expire(mkmovie())
    assert writer.deleted == ["/lib/M"]
    assert store.status_calls[0][1] == Status.EXPIRED
    assert store.logs


def test_expire_with_jellyfin_orders_folder_then_delete():
    store = FakeStore()
    writer = FakeWriter()
    jf = FakeJellyfin()
    r = reaper(store=store, writer=writer, jellyfin=jf)
    r.expire(mkmovie())
    assert writer.deleted == ["/lib/M"]  # folder deleted first
    assert jf.deleted == ["JELLY9"]
    assert jf.refreshed == 1
    assert store.status_calls[0][1] == Status.EXPIRED


def test_expire_uses_stored_item_id():
    jf = FakeJellyfin(found="SHOULD_NOT_USE")
    r = reaper(jellyfin=jf)
    r.expire(mkmovie(jellyfin_item_id="STORED1"))
    assert jf.deleted == ["STORED1"]
    assert ("find", 1) not in jf.calls
