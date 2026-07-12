import os
from unittest.mock import MagicMock

import pytest

from marquee.config import Config
from marquee.models import ErrorKind
from marquee.downloader import (
    TrailerDownloader,
    DownloadResult,
    ProbeResult,
    DownloadFailed,
)


def make_config(tmp_path, **over):
    base = dict(
        tmdb_token="x",
        sources=["upcoming"],
        config_dir=str(tmp_path),
        library_dir=str(tmp_path / "lib"),
        container="mkv",
        max_height=1080,
    )
    base.update(over)
    return Config(**base)


def _fake_ydl(**attrs):
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    for k, v in attrs.items():
        setattr(fake.extract_info, k, v)
    return fake


def test_build_options_exact(tmp_path):
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    opts = dl._build_options(str(tmp_path / "dest"))
    assert opts["format"] == "bv*[height<=1080]+ba/b[height<=1080]/b"
    assert opts["merge_output_format"] == "mkv"
    assert opts["outtmpl"] == "%(title)s [%(id)s].%(ext)s"
    assert opts["paths"] == {
        "home": str(tmp_path / "dest"),
        "temp": os.path.join(str(tmp_path), "tmp"),
    }
    assert opts["restrictfilenames"] is True
    assert opts["extractor_args"] == {
        "youtube": {"player_client": ["default", "tv", "web_safari"]}
    }
    assert "cookiefile" not in opts
    assert "proxy" not in opts
    assert opts["download_archive"] == os.path.join(str(tmp_path), "download_archive.txt")
    assert dl._progress_hook in opts["progress_hooks"]
    assert dl._pp_hook in opts["postprocessor_hooks"]


def test_build_options_cookies_proxy_and_maxheight(tmp_path):
    cfg = make_config(
        tmp_path,
        max_height=720,
        container="mp4",
        ytdlp_cookies="/config/cookies.txt",
        ytdlp_proxy="http://p:8080",
    )
    opts = TrailerDownloader(cfg)._build_options(str(tmp_path / "d"))
    assert opts["format"] == "bv*[height<=720]+ba/b[height<=720]/b"
    assert opts["merge_output_format"] == "mp4"
    assert opts["cookiefile"] == "/config/cookies.txt"
    assert opts["proxy"] == "http://p:8080"


def test_download_success(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = _fake_ydl(
        return_value={
            "id": "abc",
            "title": "Trailer",
            "duration": 90,
            "requested_downloads": [{"filepath": str(tmp_path / "Trailer [abc].mkv")}],
        }
    )
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    res = dl.download("https://youtu.be/abc", str(tmp_path), 7)
    assert isinstance(res, DownloadResult)
    assert res.path == str(tmp_path / "Trailer [abc].mkv")
    assert res.video_id == "abc"
    assert res.title == "Trailer"
    assert res.duration == 90
    assert res.ext == "mkv"


def test_download_missing_requested_downloads(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = _fake_ydl(return_value={"id": "abc", "title": "T"})
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    with pytest.raises(DownloadFailed) as ei:
        dl.download("u", str(tmp_path), 1)
    assert ei.value.kind == ErrorKind.ERROR


@pytest.mark.parametrize(
    "msg,kind",
    [
        ("ERROR: Sign in to confirm you're not a bot", ErrorKind.BOT_CHECK),
        (
            "Sign in to confirm your age. This video may be inappropriate for some users.",
            ErrorKind.AGE_GATED,
        ),
        ("Video unavailable. This video is private", ErrorKind.UNAVAILABLE),
        ("Requested format is not available", ErrorKind.NO_FORMAT),
        ("Some other weird error", ErrorKind.ERROR),
    ],
)
def test_download_classifies(monkeypatch, tmp_path, msg, kind):
    from yt_dlp.utils import DownloadError

    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    fake.extract_info.side_effect = DownloadError(msg)
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    with pytest.raises(DownloadFailed) as ei:
        dl.download("u", str(tmp_path), 1)
    assert ei.value.kind == kind
    assert ei.value.message == msg


def test_download_georestricted(monkeypatch, tmp_path):
    from yt_dlp.utils import GeoRestrictedError

    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = MagicMock()
    fake.__enter__.return_value = fake
    fake.__exit__.return_value = False
    fake.extract_info.side_effect = GeoRestrictedError("blocked in your country")
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    with pytest.raises(DownloadFailed) as ei:
        dl.download("u", str(tmp_path), 1)
    assert ei.value.kind == ErrorKind.REGION_BLOCKED


def test_probe_ok(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = _fake_ydl(
        return_value={
            "id": "abc",
            "title": "T",
            "duration": 120,
            "is_live": False,
            "availability": "public",
            "formats": [{"height": 720, "vcodec": "vp9"}],
        }
    )
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    res = dl.probe("https://youtu.be/abc")
    assert isinstance(res, ProbeResult)
    assert res.ok is True
    assert res.has_maxheight is True
    assert res.duration == 120
    assert res.availability == "public"
    _, kwargs = fake.extract_info.call_args
    assert kwargs["download"] is False


def test_probe_live_not_ok(monkeypatch, tmp_path):
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg)
    fake = _fake_ydl(
        return_value={"id": "a", "is_live": True, "formats": [{"height": 720, "vcodec": "vp9"}]}
    )
    monkeypatch.setattr(
        "marquee.downloader.yt_dlp.YoutubeDL", MagicMock(return_value=fake)
    )
    assert dl.probe("u").ok is False


def test_progress_hook_reports(tmp_path):
    seen = []
    cfg = make_config(tmp_path)
    dl = TrailerDownloader(cfg, on_progress=lambda *a: seen.append(a))
    dl._current_tmdb_id = 42
    dl._progress_hook(
        {"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100, "speed": 10.0, "eta": 5}
    )
    assert seen == [(42, 50.0, 10.0, 5)]
