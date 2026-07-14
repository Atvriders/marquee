import os
from types import SimpleNamespace

import pytest

import marquee.__main__ as m


class FakePipeline:
    def __init__(self):
        self.runs = 0

    def run(self):
        self.runs += 1


class FakeReaper:
    def __init__(self):
        self.expired = []

    def find_expired(self, movies):
        return list(movies)

    def expire(self, movie):
        self.expired.append(movie)


class FakeStore:
    def __init__(self, movies):
        self._movies = movies

    def list_movies(self, statuses=None):
        return list(self._movies)


def fake_components(pipeline=None, reaper=None, store=None):
    return m.Components(
        store=store or FakeStore([]),
        client=object(),
        downloader=object(),
        writer=object(),
        jellyfin=None,
        reaper=reaper or FakeReaper(),
        pipeline=pipeline or FakePipeline(),
        scheduler=object(),
        broadcaster=object(),
        config=object(),
        watchdog=object(),
    )


def test_main_run_invokes_pipeline(monkeypatch):
    pipeline = FakePipeline()
    comps = fake_components(pipeline=pipeline)
    monkeypatch.setattr(m, "build_components", lambda config: comps)
    monkeypatch.setattr(m, "load_config", lambda env, overrides=None: object())
    m.main(["run"])
    assert pipeline.runs == 1


def test_main_reap_invokes_reaper(monkeypatch):
    reaper = FakeReaper()
    store = FakeStore([SimpleNamespace(tmdb_id=1)])
    comps = fake_components(reaper=reaper, store=store)
    monkeypatch.setattr(m, "build_components", lambda config: comps)
    monkeypatch.setattr(m, "load_config", lambda env, overrides=None: object())
    m.main(["reap"])
    assert len(reaper.expired) == 1


def test_build_components_materializes_pasted_cookies(tmp_path):
    from marquee.config import Config

    cfg = Config(
        tmdb_token="t",
        sources=["upcoming"],
        config_dir=str(tmp_path),
        library_dir=str(tmp_path / "lib"),
        ytdlp_cookies_text=".youtube.com TRUE / TRUE 0 SID abc",
    )
    comps = m.build_components(cfg)
    try:
        cookies = tmp_path / "cookies.txt"
        assert cookies.is_file()
        assert cfg.ytdlp_cookies == str(cookies)
        content = cookies.read_text()
        assert "# Netscape HTTP Cookie File" in content and "\t" in content
    finally:
        comps.store.close()
        comps.client.close()


def test_build_components_succeeds_when_data_dirs_writable(tmp_path):
    from marquee.config import Config

    cfg = Config(
        tmdb_token="t",
        sources=["upcoming"],
        config_dir=str(tmp_path / "config"),
        library_dir=str(tmp_path / "lib"),
    )
    comps = m.build_components(cfg)
    try:
        assert os.path.isdir(cfg.config_dir)
        assert os.path.isdir(cfg.library_dir)
        assert os.path.isdir(os.path.join(cfg.config_dir, "tmp"))
    finally:
        comps.store.close()
        comps.client.close()


def test_build_components_raises_when_config_dir_not_writable(tmp_path):
    # Verified live failure: a bind-mounted /config owned by a different
    # uid/gid than the container process. Must fail fast with a clear
    # RuntimeError, not limp along until a cryptic yt-dlp error mid-download.
    from marquee.config import Config

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_dir.chmod(0o500)  # r-x: cannot create files inside as the owner
    cfg = Config(
        tmdb_token="t",
        sources=["upcoming"],
        config_dir=str(config_dir),
        library_dir=str(tmp_path / "lib"),
    )
    try:
        with pytest.raises(RuntimeError) as excinfo:
            m.build_components(cfg)
        message = str(excinfo.value)
        assert str(config_dir) in message
        assert f"uid={os.getuid()}" in message
        assert f"gid={os.getgid()}" in message
    finally:
        config_dir.chmod(0o700)


def test_build_components_raises_when_library_dir_not_writable(tmp_path):
    from marquee.config import Config

    library_dir = tmp_path / "lib"
    library_dir.mkdir()
    library_dir.chmod(0o500)
    cfg = Config(
        tmdb_token="t",
        sources=["upcoming"],
        config_dir=str(tmp_path / "config"),
        library_dir=str(library_dir),
    )
    try:
        with pytest.raises(RuntimeError) as excinfo:
            m.build_components(cfg)
        assert str(library_dir) in str(excinfo.value)
    finally:
        library_dir.chmod(0o700)
