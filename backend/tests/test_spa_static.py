from pathlib import Path

from fastapi.testclient import TestClient

from marquee.api.app import AppContext, create_app
from marquee.api.sse import Broadcaster


def _build_static(tmp_path: Path) -> Path:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(
        '<!doctype html><html><head><title>Marquee</title></head>'
        '<body><div id="root"></div></body></html>',
        encoding="utf-8",
    )
    (static / "assets" / "app.js").write_text("console.log('marquee')", encoding="utf-8")
    return static


def _client(static: Path) -> TestClient:
    # SPA routes never touch store/scheduler, so a minimal context is sufficient.
    ctx = AppContext(
        store=None, scheduler=None, reaper=None, config=None,
        broadcaster=Broadcaster(), static_dir=str(static),
    )
    return TestClient(create_app(ctx))


def test_root_serves_index_html(tmp_path: Path) -> None:
    r = _client(_build_static(tmp_path)).get("/")
    assert r.status_code == 200
    assert "<title>Marquee</title>" in r.text


def test_deep_link_falls_back_to_index(tmp_path: Path) -> None:
    r = _client(_build_static(tmp_path)).get("/movies/1234567")
    assert r.status_code == 200
    assert '<div id="root"></div>' in r.text


def test_static_assets_are_served(tmp_path: Path) -> None:
    r = _client(_build_static(tmp_path)).get("/assets/app.js")
    assert r.status_code == 200
    assert "marquee" in r.text


def test_unknown_api_path_is_404_not_spa(tmp_path: Path) -> None:
    # The catch-all must NOT serve index.html for unknown /api/* paths.
    r = _client(_build_static(tmp_path)).get("/api/nope")
    assert r.status_code == 404
