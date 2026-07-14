from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Status(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


class ErrorKind(str, Enum):
    BOT_CHECK = "bot_check"
    AGE_GATED = "age_gated"
    REGION_BLOCKED = "region_blocked"
    UNAVAILABLE = "unavailable"
    NO_FORMAT = "no_format"
    NO_TRAILER = "no_trailer"
    DRM = "drm"
    ERROR = "error"


@dataclass
class MovieCandidate:
    tmdb_id: int
    title: str
    year: int | None
    overview: str
    popularity: float
    poster_path: str | None
    backdrop_path: str | None
    source: str
    release_date: str | None


@dataclass
class TrailerVideo:
    key: str
    site: str
    type: str
    official: bool
    size: int
    iso_639_1: str
    published_at: str

    @property
    def url(self) -> str:
        if self.site == "Vimeo":
            return f"https://vimeo.com/{self.key}"
        return f"https://www.youtube.com/watch?v={self.key}"

    @property
    def youtube_url(self) -> str:
        return self.url


@dataclass
class EnrichedMovie:
    tmdb_id: int
    title: str
    year: int | None
    overview: str
    popularity: float
    source: str
    poster_path: str | None
    backdrop_path: str | None
    runtime: int | None
    genres: list[str] = field(default_factory=list)
    studios: list[str] = field(default_factory=list)
    certification: str | None = None
    premiere_date: str | None = None
    digital_date: datetime | None = None
    digital_date_source: str = "none"
    youtube_key: str | None = None
    trailer: TrailerVideo | None = None
    trailer_candidates: list[TrailerVideo] = field(default_factory=list)


@dataclass
class Movie:
    tmdb_id: int
    title: str
    year: int | None
    overview: str
    runtime: int | None
    genres: list[str]
    studios: list[str]
    certification: str | None
    premiere_date: str | None
    digital_date: datetime | None
    digital_date_source: str
    region: str
    popularity: float
    poster_path: str | None
    backdrop_path: str | None
    youtube_key: str | None
    status: Status
    file_path: str | None
    folder: str | None
    jellyfin_item_id: str | None
    pinned: bool
    added_at: datetime
    expires_at: datetime | None
    last_checked: datetime | None
    error_kind: str | None
    error_msg: str | None
