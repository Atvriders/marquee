from datetime import UTC, datetime

import pytest

from marquee.config import Config
from marquee.store import Store
from marquee.models import Movie, Status
from marquee.scheduler import Scheduler


def make_config(tmp_path):
    return Config(tmdb_token="x", sources=["upcoming"], config_dir=str(tmp_path),
                  library_dir=str(tmp_path / "lib"), tz="UTC")


class FakePipeline:
    def __init__(self):
        self.runs = 0

    def run(self):
        self.runs += 1


class FlakyPipeline:
    """Raises on its first run, succeeds on subsequent runs."""

    def __init__(self):
        self.calls = 0

    def run(self):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("boom")


class FakeReaper:
    def __init__(self):
        self.expired = []

    def find_expired(self, movies):
        return list(movies)

    def expire(self, m):
        self.expired.append(m.tmdb_id)


def mkmovie(tmdb_id=1):
    return Movie(
        tmdb_id=tmdb_id, title="M", year=2026, overview="", runtime=1, genres=[],
        studios=[], certification=None, premiere_date=None, digital_date=None,
        digital_date_source="none", region="US", popularity=1.0, poster_path=None,
        backdrop_path=None, youtube_key="k", status=Status.READY, file_path=None,
        folder="/lib/M", jellyfin_item_id=None, pinned=False,
        added_at=datetime(2026, 1, 1, tzinfo=UTC), expires_at=None, last_checked=None,
        error_kind=None, error_msg=None,
    )


def build(tmp_path):
    cfg = make_config(tmp_path)
    store = Store(str(tmp_path / "s.db"))
    pipeline = FakePipeline()
    reaper = FakeReaper()
    return Scheduler(pipeline, reaper, store, cfg), pipeline, reaper, store


def test_trigger_refresh_runs_pipeline(tmp_path):
    sch, pipeline, reaper, store = build(tmp_path)
    sch.trigger_refresh()
    assert pipeline.runs == 1


def test_single_flight_skips_when_locked(tmp_path):
    sch, pipeline, reaper, store = build(tmp_path)
    assert sch._lock.acquire(blocking=False)
    try:
        sch.trigger_refresh()  # lock held -> must skip
        assert pipeline.runs == 0
    finally:
        sch._lock.release()
    sch.trigger_refresh()
    assert pipeline.runs == 1


def test_cross_exclusion_reap_skipped_while_refresh_lock_held(tmp_path):
    sch, pipeline, reaper, store = build(tmp_path)
    store.upsert_movie(mkmovie(1))
    # Simulate a refresh in flight by holding the single shared lock.
    assert sch._lock.acquire(blocking=False)
    try:
        sch.trigger_reap()  # shared lock held -> reap must skip, not run
        assert reaper.expired == []
    finally:
        sch._lock.release()
    # Lock is free again -> reap now proceeds normally.
    sch.trigger_reap()
    assert reaper.expired == [1]


def test_lock_released_after_pipeline_exception(tmp_path):
    cfg = make_config(tmp_path)
    store = Store(str(tmp_path / "s.db"))
    pipeline = FlakyPipeline()
    reaper = FakeReaper()
    sch = Scheduler(pipeline, reaper, store, cfg)

    with pytest.raises(RuntimeError):
        sch.trigger_refresh()
    assert pipeline.calls == 1

    # The `finally` block must have released the lock despite the exception,
    # so a subsequent trigger is not skipped.
    sch.trigger_refresh()
    assert pipeline.calls == 2


def test_trigger_reap_expires_ready(tmp_path):
    sch, pipeline, reaper, store = build(tmp_path)
    store.upsert_movie(mkmovie(1))
    sch.trigger_reap()
    assert reaper.expired == [1]


def test_status_reports_after_start(tmp_path):
    sch, pipeline, reaper, store = build(tmp_path)
    sch.start()
    try:
        st = sch.status()
        assert set(st) == {"next_refresh", "next_reap", "running"}
        assert st["running"] is False
    finally:
        sch.stop()
