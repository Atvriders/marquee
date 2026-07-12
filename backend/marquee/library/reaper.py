from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from marquee.models import Movie, Status


def _default_now() -> datetime:
    return datetime.now(tz=UTC)


def compute_expires_at(digital_date: datetime, grace_days: int, tz: str) -> datetime:
    """Shared expiry-time computation: end-of-day (23:59:59.999999) in the
    configured tz, `grace_days` after `digital_date`. Used by both the Reaper
    (to find expired movies) and the pipeline (to persist `expires_at` on
    each movie row), so the two stay in lockstep."""
    tzinfo = ZoneInfo(tz)
    local_date = digital_date.astimezone(tzinfo).date() + timedelta(days=grace_days)
    return datetime.combine(local_date, time(23, 59, 59, 999999), tzinfo=tzinfo)


class Reaper:
    def __init__(
        self,
        store,
        writer,
        jellyfin,
        now_fn=_default_now,
        grace_days: int = 0,
        tz: str = "UTC",
        count: int = 50,
    ):
        self.store = store
        self.writer = writer
        self.jellyfin = jellyfin
        self.now_fn = now_fn
        self.grace_days = grace_days
        self.tz = tz
        self.count = count

    def _expires_at(self, digital_date: datetime) -> datetime:
        return compute_expires_at(digital_date, self.grace_days, self.tz)

    def find_expired(self, movies: list[Movie]) -> list[Movie]:
        now = self.now_fn()
        out = []
        for m in movies:
            if m.pinned or m.digital_date is None:
                continue
            if now >= self._expires_at(m.digital_date):
                out.append(m)
        return out

    def expire(self, m: Movie) -> None:
        if m.folder:
            self.writer.delete_movie(m.folder)
        if self.jellyfin is not None:
            item_id = m.jellyfin_item_id or self.jellyfin.find_item_by_tmdb(m.tmdb_id)
            if item_id:
                self.jellyfin.delete_item(item_id)
            self.jellyfin.refresh_library()
        self.store.set_status(m.tmdb_id, Status.EXPIRED)
        # NOTE: the Reaper's contract signature has no `broadcaster` reference, so
        # expiry uses `store.log` (persist-only) rather than the pipeline's
        # `emit_log` live-fan-out helper. This is intentional: reaper runs are a
        # separate cron job whose rows surface on the next SSE backlog fetch. If a
        # future iteration wants live expiry events, add a `broadcaster` param here
        # and swap this for `emit_log(...)` — the row shape is identical.
        self.store.log("info", "expired", f"Expired {m.title}", m.tmdb_id)
