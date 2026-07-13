from datetime import UTC, datetime

import httpx
import respx
from fastapi.testclient import TestClient

from marquee.config import Config
from marquee.store import Store
from marquee.models import Movie, Status
from marquee.api.sse import Broadcaster
from marquee.api.app import AppContext, create_app


class FakeScheduler:
    def __init__(self):
        self.refresh = 0
        self.reap = 0

    def trigger_refresh(self):
        self.refresh += 1

    def trigger_reap(self):
        self.reap += 1

    def status(self):
        return {"next_refresh": None, "next_reap": None, "running": False}


class FakeReaper:
    def __init__(self):
        self.expired = []

    def expire(self, m):
        self.expired.append(m.tmdb_id)


def mkmovie(tmdb_id=1, **over):
    base = dict(
        tmdb_id=tmdb_id, title="M", year=2026, overview="", runtime=1, genres=[],
        studios=[], certification=None, premiere_date=None, digital_date=None,
        digital_date_source="none", region="US", popularity=1.0, poster_path=None,
        backdrop_path=None, youtube_key="k", status=Status.READY, file_path=None,
        folder="/lib/M", jellyfin_item_id=None, pinned=False,
        added_at=datetime(2026, 1, 1, tzinfo=UTC), expires_at=None, last_checked=None,
        error_kind=None, error_msg=None,
    )
    base.update(over)
    return Movie(**base)


def build(tmp_path, static_dir=None, jellyfin_url=None):
    store = Store(str(tmp_path / "s.db"))
    cfg = Config(tmdb_token="x", sources=["upcoming"], config_dir=str(tmp_path),
                 library_dir=str(tmp_path / "lib"), jellyfin_url=jellyfin_url,
                 jellyfin_api_key="APIKEY")
    sched = FakeScheduler()
    reaper = FakeReaper()
    ctx = AppContext(store=store, scheduler=sched, reaper=reaper, config=cfg,
                     broadcaster=Broadcaster(), static_dir=static_dir)
    return TestClient(create_app(ctx)), store, sched, reaper


def test_health(tmp_path):
    client, *_ = build(tmp_path)
    assert client.get("/api/health").json() == {"status": "ok"}


def test_movies_list_and_get(tmp_path):
    client, store, *_ = build(tmp_path)
    store.upsert_movie(mkmovie(1))
    data = client.get("/api/movies").json()
    assert [m["tmdb_id"] for m in data] == [1]
    assert data[0]["status"] == "ready"
    # API-added fields present (see contract "API JSON & SSE Contract")
    assert data[0]["poster_url"] is None
    assert data[0]["backdrop_url"] is None
    assert data[0]["download_pct"] is None
    assert client.get("/api/movies/1").json()["tmdb_id"] == 1
    assert client.get("/api/movies/999").status_code == 404


def test_poster_url_built_from_path(tmp_path):
    client, store, *_ = build(tmp_path)
    store.upsert_movie(mkmovie(1, poster_path="/abc.jpg", backdrop_path="/bg.jpg"))
    m = client.get("/api/movies/1").json()
    assert m["poster_url"] == "https://image.tmdb.org/t/p/w500/abc.jpg"
    assert m["backdrop_url"] == "https://image.tmdb.org/t/p/w1280/bg.jpg"


def test_pin_toggle(tmp_path):
    client, store, *_ = build(tmp_path)
    store.upsert_movie(mkmovie(1, pinned=False))
    body = client.post("/api/movies/1/pin").json()  # returns the updated movie
    assert body["tmdb_id"] == 1
    assert body["pinned"] is True
    assert store.get_movie(1).pinned is True


def test_settings_round_trip(tmp_path):
    client, store, *_ = build(tmp_path)
    put = client.put("/api/settings", json={"count": "25"})
    assert put.status_code == 200
    assert put.json()["count"] == 25          # flat public Config, coerced to int
    got = client.get("/api/settings").json()
    assert got["count"] == 25
    assert got["tmdb_token"] == "***"         # secret masked


def test_settings_put_ignores_system_path_fields(tmp_path):
    client, store, *_ = build(tmp_path)
    before = client.get("/api/settings").json()
    put = client.put(
        "/api/settings",
        json={"library_dir": "/tmp/evil", "config_dir": "/tmp/evil-config"},
    )
    assert put.status_code == 200
    assert put.json()["library_dir"] == before["library_dir"]
    assert put.json()["config_dir"] == before["config_dir"]
    assert store.all_settings().get("library_dir") is None
    assert store.all_settings().get("config_dir") is None


def test_run_and_reap_trigger(tmp_path):
    client, store, sched, reaper = build(tmp_path)
    assert client.post("/api/run").status_code == 200
    assert client.post("/api/reap").status_code == 200
    assert sched.refresh == 1
    assert sched.reap == 1


def test_download_now_queues_and_triggers(tmp_path):
    client, store, sched, reaper = build(tmp_path)
    store.upsert_movie(mkmovie(1, status=Status.FAILED))
    assert client.post("/api/movies/1/download").status_code == 200
    assert store.get_movie(1).status == Status.QUEUED
    assert sched.refresh == 1


def test_delete_now_expires(tmp_path):
    client, store, sched, reaper = build(tmp_path)
    store.upsert_movie(mkmovie(1))
    assert client.request("DELETE", "/api/movies/1").status_code == 200
    assert reaper.expired == [1]


def test_status(tmp_path):
    client, store, *_ = build(tmp_path)
    store.upsert_movie(mkmovie(1, status=Status.READY))
    body = client.get("/api/status").json()
    assert body["running"] is False            # flat StatusSummary
    assert body["counts"]["ready"] == 1
    assert set(body["disk"]) == {"used_gb", "free_gb", "total_gb"}
    assert "ytdlp_version" in body


def test_ytdlp_update_returns_version_without_real_install(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        import subprocess as sp

        if "yt_dlp" in cmd and "--version" in cmd:
            return sp.CompletedProcess(cmd, 0, stdout="2099.01.01\n", stderr="")
        return sp.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("marquee.api.routes.subprocess.run", fake_run)
    client, *_ = build(tmp_path)
    body = client.post("/api/ytdlp/update").json()
    assert isinstance(body["version"], str)
    assert body["version"] == "2099.01.01"
    # Both the pip upgrade and the fresh version check went through the mock
    # (never a real subprocess). yt_dlp's own import machinery may also shell
    # out via the patched subprocess.run, so assert presence, not an exact count.
    assert any("pip" in c and "install" in c and "yt-dlp[default]" in c for c in calls)
    assert any("yt_dlp" in c and "--version" in c for c in calls)


@respx.mock
def test_jellyfin_test(tmp_path):
    respx.get("http://jelly:8096/System/Info").mock(
        return_value=httpx.Response(200, json={"Version": "10.11"})
    )
    client, *_ = build(tmp_path, jellyfin_url="http://jelly:8096")
    assert client.post("/api/jellyfin/test").json() == {"ok": True}


@respx.mock
def test_connections(tmp_path):
    respx.get("https://api.themoviedb.org/3/configuration").mock(
        return_value=httpx.Response(200, json={"images": {"secure_base_url": "https://img/t/p/"}})
    )
    client, *_ = build(tmp_path)  # no jellyfin configured
    body = client.get("/api/connections").json()
    assert body["tmdb"] == "ok"
    assert body["jellyfin"] == "not_configured"


@respx.mock
def test_connections_tmdb_error(tmp_path):
    respx.get("https://api.themoviedb.org/3/configuration").mock(
        return_value=httpx.Response(401, json={"status_message": "invalid token"})
    )
    client, *_ = build(tmp_path)
    body = client.get("/api/connections").json()
    assert body["tmdb"] in ("unauthorized", "error")


def test_spa_catch_all_does_not_shadow_api(tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>SPA</html>")
    client, *_ = build(tmp_path, static_dir=str(static))
    # API still works
    assert client.get("/api/health").json() == {"status": "ok"}
    # Unknown SPA route returns index
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "SPA" in r.text
    # Unknown /api path is 404, not the SPA
    assert client.get("/api/nope").status_code == 404
