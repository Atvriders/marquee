from __future__ import annotations

import os
from dataclasses import dataclass

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError, GeoRestrictedError

from marquee.config import Config
from marquee.models import ErrorKind


def normalize_cookies_text(text: str) -> str:
    """Normalize a pasted Netscape cookies.txt so it survives copy-paste into a
    compose/env value. Ensures the required header line, and — because pasting a
    tab-separated file often turns the tabs into spaces — repairs data lines that
    have no tabs by re-joining their whitespace-separated fields with tabs
    (Netscape rows are 7 fields; the last, the value, may itself contain spaces).
    Lines that already contain tabs are left untouched.
    """
    out: list[str] = []
    has_header = False
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("# Netscape HTTP Cookie File"):
            has_header = True
        if not stripped or (stripped.startswith("#") and not stripped.startswith("#HttpOnly_")):
            out.append(line)
            continue
        if "\t" not in line:
            parts = line.split()
            if len(parts) >= 7:
                line = "\t".join(parts[:6]) + "\t" + " ".join(parts[6:])
            elif len(parts) == 6:
                line = "\t".join(parts)
        out.append(line)
    body = "\n".join(x for x in out if x.strip() != "")
    header = "" if has_header else "# Netscape HTTP Cookie File\n"
    return header + body + "\n"


def _classify_message(msg: str) -> ErrorKind:
    m = msg.lower()
    if (
        "confirm your age" in m
        or "inappropriate for some users" in m
        or "age-restricted" in m
        or "age restricted" in m
    ):
        return ErrorKind.AGE_GATED
    if "not a bot" in m or ("sign in to confirm" in m and "bot" in m):
        return ErrorKind.BOT_CHECK
    if (
        "not available in your country" in m
        or "blocked it in your country" in m
        or "geo" in m
    ):
        return ErrorKind.REGION_BLOCKED
    if "requested format" in m or "no video formats" in m or "no formats" in m:
        return ErrorKind.NO_FORMAT
    if "drm" in m:
        return ErrorKind.DRM
    if (
        "unavailable" in m
        or "private" in m
        or "removed" in m
        or "deleted" in m
        or "terminated" in m
    ):
        return ErrorKind.UNAVAILABLE
    return ErrorKind.ERROR


def classify_download_error(exc: BaseException) -> tuple[ErrorKind, str]:
    """Classify a yt-dlp exception into an (ErrorKind, message) pair.

    Shared by download() and probe() so both surface the real failure reason
    (age-gate / bot-check / region-block / unavailable / no-format / generic)
    instead of a generic error.
    """
    msg = str(exc)
    if isinstance(exc, GeoRestrictedError):
        return ErrorKind.REGION_BLOCKED, msg
    return _classify_message(msg), msg


@dataclass
class ProbeResult:
    ok: bool
    duration: int | None
    title: str | None
    has_maxheight: bool
    availability: str | None
    error_kind: ErrorKind | None = None
    error_msg: str | None = None


@dataclass
class DownloadResult:
    path: str
    title: str | None
    duration: int | None
    ext: str
    video_id: str


class DownloadFailed(Exception):
    def __init__(self, kind: ErrorKind, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class TrailerDownloader:
    def __init__(self, config: Config, on_progress=None):
        self.config = config
        self._on_progress = on_progress
        self._current_tmdb_id: int | None = None

    def _build_options(self, dest_dir: str) -> dict:
        h = self.config.max_height
        opts: dict = {
            "format": f"bv*[height<={h}]+ba/b[height<={h}]/b",
            "merge_output_format": self.config.container,
            "outtmpl": "%(title)s [%(id)s].%(ext)s",
            "paths": {
                "home": dest_dir,
                "temp": os.path.join(self.config.config_dir, "tmp"),
            },
            "restrictfilenames": True,
            "extractor_args": {
                "youtube": {"player_client": ["default", "tv", "web_safari"]}
            },
            "retries": 10,
            "fragment_retries": 10,
            "sleep_interval": 1,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._pp_hook],
        }
        opts["download_archive"] = os.path.join(
            self.config.config_dir, "download_archive.txt"
        )
        # Only pass the cookies file if it actually exists — this lets the default
        # YTDLP_COOKIES=/config/cookies.txt be set safely before the user has pasted
        # a cookies.txt in (yt-dlp errors on a missing cookiefile otherwise).
        if self.config.ytdlp_cookies and os.path.isfile(self.config.ytdlp_cookies):
            opts["cookiefile"] = self.config.ytdlp_cookies
        if self.config.ytdlp_proxy:
            opts["proxy"] = self.config.ytdlp_proxy
        return opts

    def _progress_hook(self, d: dict) -> None:
        if self._on_progress is None:
            return
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = round(done / total * 100, 1) if total else 0.0
            self._on_progress(self._current_tmdb_id, pct, d.get("speed"), d.get("eta"))
        elif status == "finished":
            self._on_progress(self._current_tmdb_id, 100.0, None, 0)

    def _pp_hook(self, d: dict) -> None:
        if self._on_progress and d.get("status") == "finished":
            self._on_progress(self._current_tmdb_id, 100.0, None, 0)

    def probe(self, url: str) -> ProbeResult:
        opts = self._build_options(self.config.config_dir)
        opts["skip_download"] = True
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        except (DownloadError, ExtractorError) as e:
            kind, msg = classify_download_error(e)
            return ProbeResult(
                ok=False,
                duration=None,
                title=None,
                has_maxheight=False,
                availability="error",
                error_kind=kind,
                error_msg=msg,
            )
        is_live = bool(info.get("is_live"))
        formats = info.get("formats", []) or []
        has_max = any(
            (f.get("height") or 0) <= self.config.max_height
            and f.get("vcodec", "none") != "none"
            for f in formats
        )
        if is_live:
            return ProbeResult(
                ok=False,
                duration=info.get("duration"),
                title=info.get("title"),
                has_maxheight=has_max,
                availability=info.get("availability"),
                error_kind=ErrorKind.ERROR,
                error_msg="video is live, cannot download",
            )
        if not has_max:
            return ProbeResult(
                ok=False,
                duration=info.get("duration"),
                title=info.get("title"),
                has_maxheight=False,
                availability=info.get("availability"),
                error_kind=ErrorKind.NO_FORMAT,
                error_msg=(
                    f"no format with height <= {self.config.max_height} available"
                ),
            )
        return ProbeResult(
            ok=True,
            duration=info.get("duration"),
            title=info.get("title"),
            has_maxheight=has_max,
            availability=info.get("availability"),
        )

    def download(self, url: str, dest_dir: str, tmdb_id: int) -> DownloadResult:
        self._current_tmdb_id = tmdb_id
        opts = self._build_options(dest_dir)
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except (DownloadError, ExtractorError) as e:
            kind, msg = classify_download_error(e)
            raise DownloadFailed(kind, msg) from e
        requested = (info or {}).get("requested_downloads")
        if not requested:
            raise DownloadFailed(
                ErrorKind.ERROR, "no requested_downloads in yt-dlp result"
            )
        path = requested[0]["filepath"]
        ext = os.path.splitext(path)[1].lstrip(".")
        return DownloadResult(
            path=path,
            title=info.get("title"),
            duration=info.get("duration"),
            ext=ext,
            video_id=info.get("id", ""),
        )
