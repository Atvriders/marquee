from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from .models import Movie, Status

_COLUMNS = [
    "tmdb_id",
    "title",
    "year",
    "overview",
    "runtime",
    "genres",
    "studios",
    "certification",
    "premiere_date",
    "digital_date",
    "digital_date_source",
    "region",
    "popularity",
    "poster_path",
    "backdrop_path",
    "youtube_key",
    "status",
    "file_path",
    "folder",
    "jellyfin_item_id",
    "pinned",
    "added_at",
    "expires_at",
    "last_checked",
    "error_kind",
    "error_msg",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS movies (
    tmdb_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    year INTEGER,
    overview TEXT,
    runtime INTEGER,
    genres TEXT,
    studios TEXT,
    certification TEXT,
    premiere_date TEXT,
    digital_date TEXT,
    digital_date_source TEXT,
    region TEXT,
    popularity REAL,
    poster_path TEXT,
    backdrop_path TEXT,
    youtube_key TEXT,
    status TEXT,
    file_path TEXT,
    folder TEXT,
    jellyfin_item_id TEXT,
    pinned INTEGER,
    added_at TEXT,
    expires_at TEXT,
    last_checked TEXT,
    error_kind TEXT,
    error_msg TEXT
);
CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT,
    event TEXT,
    tmdb_id INTEGER,
    message TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


def _dt_to_str(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def _str_to_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _serialize_field(value):
    if isinstance(value, Status):
        return value.value
    if isinstance(value, datetime):
        return _dt_to_str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value)
    if isinstance(value, bool):
        return 1 if value else 0
    return value


class Store:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ----- movies -----
    def _movie_to_row(self, m: Movie) -> dict:
        return {
            "tmdb_id": m.tmdb_id,
            "title": m.title,
            "year": m.year,
            "overview": m.overview,
            "runtime": m.runtime,
            "genres": json.dumps(m.genres),
            "studios": json.dumps(m.studios),
            "certification": m.certification,
            "premiere_date": m.premiere_date,
            "digital_date": _dt_to_str(m.digital_date),
            "digital_date_source": m.digital_date_source,
            "region": m.region,
            "popularity": m.popularity,
            "poster_path": m.poster_path,
            "backdrop_path": m.backdrop_path,
            "youtube_key": m.youtube_key,
            "status": m.status.value,
            "file_path": m.file_path,
            "folder": m.folder,
            "jellyfin_item_id": m.jellyfin_item_id,
            "pinned": 1 if m.pinned else 0,
            "added_at": _dt_to_str(m.added_at),
            "expires_at": _dt_to_str(m.expires_at),
            "last_checked": _dt_to_str(m.last_checked),
            "error_kind": m.error_kind,
            "error_msg": m.error_msg,
        }

    def _row_to_movie(self, row: sqlite3.Row) -> Movie:
        return Movie(
            tmdb_id=row["tmdb_id"],
            title=row["title"],
            year=row["year"],
            overview=row["overview"],
            runtime=row["runtime"],
            genres=json.loads(row["genres"] or "[]"),
            studios=json.loads(row["studios"] or "[]"),
            certification=row["certification"],
            premiere_date=row["premiere_date"],
            digital_date=_str_to_dt(row["digital_date"]),
            digital_date_source=row["digital_date_source"],
            region=row["region"],
            popularity=row["popularity"],
            poster_path=row["poster_path"],
            backdrop_path=row["backdrop_path"],
            youtube_key=row["youtube_key"],
            status=Status(row["status"]),
            file_path=row["file_path"],
            folder=row["folder"],
            jellyfin_item_id=row["jellyfin_item_id"],
            pinned=bool(row["pinned"]),
            added_at=_str_to_dt(row["added_at"]),
            expires_at=_str_to_dt(row["expires_at"]),
            last_checked=_str_to_dt(row["last_checked"]),
            error_kind=row["error_kind"],
            error_msg=row["error_msg"],
        )

    def upsert_movie(self, m: Movie) -> None:
        row = self._movie_to_row(m)
        cols = ",".join(_COLUMNS)
        placeholders = ",".join("?" for _ in _COLUMNS)
        self._conn.execute(
            f"INSERT OR REPLACE INTO movies ({cols}) VALUES ({placeholders})",
            [row[c] for c in _COLUMNS],
        )
        self._conn.commit()

    def get_movie(self, tmdb_id: int) -> Movie | None:
        cur = self._conn.execute("SELECT * FROM movies WHERE tmdb_id = ?", [tmdb_id])
        row = cur.fetchone()
        return self._row_to_movie(row) if row else None

    def list_movies(self, statuses: list[Status] | None = None) -> list[Movie]:
        if statuses:
            marks = ",".join("?" for _ in statuses)
            cur = self._conn.execute(
                f"SELECT * FROM movies WHERE status IN ({marks}) ORDER BY popularity DESC",
                [s.value for s in statuses],
            )
        else:
            cur = self._conn.execute("SELECT * FROM movies ORDER BY popularity DESC")
        return [self._row_to_movie(r) for r in cur.fetchall()]

    def set_status(self, tmdb_id: int, status: Status, **fields) -> None:
        sets = ["status = ?"]
        params: list = [status.value]
        for key, value in fields.items():
            if key not in _COLUMNS:
                raise ValueError(f"unknown movie column: {key}")
            sets.append(f"{key} = ?")
            params.append(_serialize_field(value))
        params.append(tmdb_id)
        self._conn.execute(
            f"UPDATE movies SET {', '.join(sets)} WHERE tmdb_id = ?", params
        )
        self._conn.commit()

    def set_pinned(self, tmdb_id: int, pinned: bool) -> None:
        self._conn.execute(
            "UPDATE movies SET pinned = ? WHERE tmdb_id = ?",
            [1 if pinned else 0, tmdb_id],
        )
        self._conn.commit()

    def delete_movie(self, tmdb_id: int) -> None:
        self._conn.execute("DELETE FROM movies WHERE tmdb_id = ?", [tmdb_id])
        self._conn.commit()

    # ----- activity -----
    def log(self, level: str, event: str, message: str, tmdb_id: int | None = None) -> None:
        self._conn.execute(
            "INSERT INTO activity_log (ts, level, event, tmdb_id, message) VALUES (?,?,?,?,?)",
            [datetime.now(timezone.utc).isoformat(), level, event, tmdb_id, message],
        )
        self._conn.commit()

    def recent_activity(self, limit: int = 200) -> list[dict]:
        cur = self._conn.execute(
            "SELECT id, ts, level, event, tmdb_id, message FROM activity_log "
            "ORDER BY id DESC LIMIT ?",
            [limit],
        )
        return [dict(r) for r in cur.fetchall()]

    # ----- settings -----
    def get_setting(self, key: str) -> str | None:
        cur = self._conn.execute("SELECT value FROM settings WHERE key = ?", [key])
        row = cur.fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", [key, value]
        )
        self._conn.commit()

    def all_settings(self) -> dict[str, str]:
        cur = self._conn.execute("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in cur.fetchall()}
