from fastapi.testclient import TestClient

from marquee.config import Config
from marquee.store import Store
from marquee.api.sse import Broadcaster
from marquee.api.app import AppContext, create_app


class FakeScheduler:
    def status(self):
        return {"next_refresh": None, "next_reap": None, "running": False}


class FakeWatchdog:
    def __init__(self, last=None):
        self._last = last
        self.run_calls = 0

    def get_last(self):
        return self._last

    def run(self):
        self.run_calls += 1
        self._last = {"ok": True, "checks": [], "checked_at": "2026-07-13T00:00:00+00:00"}
        return self._last


def build(tmp_path, watchdog=None):
    store = Store(str(tmp_path / "s.db"))
    cfg = Config(tmdb_token="x", sources=["upcoming"], config_dir=str(tmp_path),
                 library_dir=str(tmp_path / "lib"))
    ctx = AppContext(store=store, scheduler=FakeScheduler(), reaper=None, config=cfg,
                      broadcaster=Broadcaster(), watchdog=watchdog)
    return TestClient(create_app(ctx))


def test_get_watchdog_returns_persisted_result_without_running(tmp_path):
    wd = FakeWatchdog(last={"ok": True, "checks": [{"id": "x"}], "checked_at": "t"})
    client = build(tmp_path, watchdog=wd)

    resp = client.get("/api/watchdog")

    assert resp.status_code == 200
    assert resp.json() == wd._last
    assert wd.run_calls == 0


def test_get_watchdog_runs_when_no_persisted_result(tmp_path):
    wd = FakeWatchdog(last=None)
    client = build(tmp_path, watchdog=wd)

    resp = client.get("/api/watchdog")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert wd.run_calls == 1


def test_post_watchdog_run_always_runs(tmp_path):
    wd = FakeWatchdog(last={"ok": False, "checks": [], "checked_at": "old"})
    client = build(tmp_path, watchdog=wd)

    resp = client.post("/api/watchdog/run")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert wd.run_calls == 1


def test_watchdog_routes_503_when_not_configured(tmp_path):
    client = build(tmp_path, watchdog=None)

    assert client.get("/api/watchdog").status_code == 503
    assert client.post("/api/watchdog/run").status_code == 503
