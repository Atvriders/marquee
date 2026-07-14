from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

from marquee.config import Config
from marquee.library.reaper import compute_expires_at
from marquee.models import EnrichedMovie, ErrorKind, Movie, MovieCandidate, Status
from marquee.downloader import DownloadFailed
from marquee.tmdb.curator import discover, enrich


@dataclass
class RunSummary:
    discovered: int
    downloaded: int
    skipped: int
    failed: int
    expired: int


def emit_log(store, broadcaster, level, event, message, tmdb_id=None) -> None:
    """Persist a log row AND fan it out to SSE subscribers as a contract
    `{"type":"log","entry":{...}}` event, keeping all live pipeline output
    within the SSE log|progress tagged union."""
    row = {
        "level": level,
        "event": event,
        "message": message,
        "tmdb_id": tmdb_id,
        "ts": datetime.now(UTC).isoformat(),
    }
    store.log(level, event, message, tmdb_id)
    broadcaster.publish({"type": "log", "entry": row})


def _candidate_from_movie(m: Movie) -> MovieCandidate:
    """Synthesize a MovieCandidate for a stored movie that's QUEUED but wasn't
    part of this run's fresh discover() results (e.g. a manual
    POST /api/movies/{id}/download on a movie outside the top-N), so it can
    flow through the same enrich/download path as freshly-discovered ones."""
    return MovieCandidate(
        tmdb_id=m.tmdb_id,
        title=m.title,
        year=m.year,
        overview=m.overview,
        popularity=m.popularity,
        poster_path=m.poster_path,
        backdrop_path=m.backdrop_path,
        source="queued",
        release_date=m.premiere_date,
    )


def _expires_at_for(digital_date: datetime | None, config: Config) -> datetime | None:
    if digital_date is None:
        return None
    return compute_expires_at(digital_date, config.grace_days, config.tz)


def _row(e: EnrichedMovie, config: Config, status: Status, now: datetime) -> Movie:
    return Movie(
        tmdb_id=e.tmdb_id,
        title=e.title,
        year=e.year,
        overview=e.overview,
        runtime=e.runtime,
        genres=e.genres,
        studios=e.studios,
        certification=e.certification,
        premiere_date=e.premiere_date,
        digital_date=e.digital_date,
        digital_date_source=e.digital_date_source,
        region=config.region,
        popularity=e.popularity,
        poster_path=e.poster_path,
        backdrop_path=e.backdrop_path,
        youtube_key=e.youtube_key,
        status=status,
        file_path=None,
        folder=None,
        jellyfin_item_id=None,
        pinned=False,
        added_at=now,
        expires_at=_expires_at_for(e.digital_date, config),
        last_checked=now,
        error_kind=None,
        error_msg=None,
    )


class RefreshPipeline:
    def __init__(
        self, client, downloader, writer, reaper, jellyfin, store, config, broadcaster
    ):
        self.client = client
        self.downloader = downloader
        self.writer = writer
        self.reaper = reaper
        self.jellyfin = jellyfin
        self.store = store
        self.config = config
        self.broadcaster = broadcaster

    def reconcile(self) -> int:
        """Marquee trusts its DB over the disk: if a READY movie's file has
        been deleted out from under it (e.g. manual cleanup, volume wipe),
        the DB would otherwise keep reporting it ready forever and never
        re-download it. Walk all READY movies and re-queue any whose
        file_path no longer exists on disk so the next run's download pass
        picks it back up. Returns the number of movies reconciled."""
        reconciled = 0
        for movie in self.store.list_movies([Status.READY]):
            if movie.file_path and os.path.isfile(movie.file_path):
                continue
            self.store.set_status(
                movie.tmdb_id,
                Status.QUEUED,
                file_path=None,
                folder=None,
                jellyfin_item_id=None,
            )
            emit_log(
                self.store,
                self.broadcaster,
                "warn",
                "library_file_missing",
                f"library file missing, will re-download: {movie.title}",
                movie.tmdb_id,
            )
            reconciled += 1
        return reconciled

    def run(self) -> RunSummary:
        now = datetime.now(tz=UTC)
        temp_dir = os.path.join(self.config.config_dir, "tmp")
        os.makedirs(temp_dir, exist_ok=True)

        self.reconcile()

        candidates = discover(
            self.client,
            self.config.sources,
            self.config.region,
            self.config.language,
            self.config.count,
        )
        summary = RunSummary(
            discovered=len(candidates), downloaded=0, skipped=0, failed=0, expired=0
        )
        emit_log(
            self.store,
            self.broadcaster,
            "info",
            "run_start",
            f"Refresh started: {len(candidates)} discovered",
        )

        # A movie can be QUEUED by a manual POST /api/movies/{id}/download
        # without being among this run's freshly-discovered top-N candidates
        # (e.g. it fell out of the top-N ranking). Fold any such queued
        # movies into the candidate set so they still get re-enriched and
        # downloaded through the normal path below.
        discovered_ids = {c.tmdb_id for c in candidates}
        queued_extra = [
            _candidate_from_movie(m)
            for m in self.store.list_movies([Status.QUEUED])
            if m.tmdb_id not in discovered_ids
        ]
        if queued_extra:
            candidates = candidates + queued_extra

        newly_written: list[int] = []

        for cand in candidates:
            existing = self.store.get_movie(cand.tmdb_id)
            enriched = enrich(
                self.client, cand, self.config.region, self.config.language
            )

            if enriched.youtube_key is None:
                if (
                    existing
                    and existing.status == Status.READY
                    and existing.file_path
                    and os.path.exists(existing.file_path)
                ):
                    # A re-enrich transiently returned no trailer for a movie
                    # that's already READY with a file on disk. Don't demote —
                    # keep serving what we have and retry on the next refresh.
                    emit_log(
                        self.store,
                        self.broadcaster,
                        "warn",
                        "no_trailer_transient",
                        f"No trailer for {enriched.title} on re-enrich; keeping READY",
                        enriched.tmdb_id,
                    )
                    summary.skipped += 1
                    continue
                row = _row(enriched, self.config, Status.FAILED, now)
                if existing:
                    row.pinned = existing.pinned
                    row.added_at = existing.added_at
                    row.jellyfin_item_id = existing.jellyfin_item_id
                row.error_kind = ErrorKind.NO_TRAILER.value
                row.error_msg = "no trailer found"
                self.store.upsert_movie(row)
                emit_log(
                    self.store,
                    self.broadcaster,
                    "warn",
                    "no_trailer",
                    f"No trailer for {enriched.title}",
                    enriched.tmdb_id,
                )
                summary.failed += 1
                continue

            if (
                existing
                and existing.status == Status.READY
                and existing.youtube_key == enriched.youtube_key
                and existing.file_path
                and os.path.exists(existing.file_path)
            ):
                self.store.set_status(
                    enriched.tmdb_id,
                    Status.READY,
                    popularity=enriched.popularity,
                    last_checked=now,
                )
                summary.skipped += 1
                continue

            row = _row(enriched, self.config, Status.DOWNLOADING, now)
            if existing:
                row.pinned = existing.pinned
                row.jellyfin_item_id = existing.jellyfin_item_id
                row.added_at = existing.added_at
            self.store.upsert_movie(row)
            emit_log(
                self.store,
                self.broadcaster,
                "info",
                "download_start",
                f"Downloading {enriched.title}",
                enriched.tmdb_id,
            )

            # TMDB lists many videos per movie; a single "best" pick can be
            # DRM'd, removed, or otherwise dead. Rank ALL candidates and try
            # them in order until one actually probes+downloads (spec:
            # trailer candidate fallback).
            trailer_candidates = enriched.trailer_candidates[
                : self.config.trailer_max_candidates
            ]
            if not trailer_candidates and enriched.trailer:
                trailer_candidates = [enriched.trailer]

            first_error_kind: ErrorKind | None = None
            first_error_msg: str | None = None
            # An ENVIRONMENT error (e.g. /config/tmp not writable) is a fact
            # about the host, not about any particular candidate: every
            # remaining candidate would fail the exact same way, and
            # reporting the FIRST candidate's unrelated rejection reason
            # (e.g. "this video is not available") is actively misleading.
            # Once we see one, stop probing/downloading immediately.
            env_error: tuple[ErrorKind, str] | None = None
            succeeded = False

            for candidate in trailer_candidates:
                # Pre-validate the trailer before spending a full download
                # (spec §4.5/§7).
                probe_res = self.downloader.probe(candidate.url)
                if not probe_res.ok:
                    kind = probe_res.error_kind or ErrorKind.NO_FORMAT
                    msg = (
                        probe_res.error_msg
                        or "pre-validate failed: no suitable format"
                    )
                    if first_error_kind is None:
                        first_error_kind, first_error_msg = kind, msg
                    emit_log(
                        self.store,
                        self.broadcaster,
                        "warn",
                        "trailer_rejected",
                        f"{enriched.title}: candidate {candidate.key} rejected "
                        f"({kind.value}): {msg}",
                        enriched.tmdb_id,
                    )
                    if kind == ErrorKind.ENVIRONMENT:
                        env_error = (kind, msg)
                        break
                    continue

                try:
                    result = self.downloader.download(
                        candidate.url, temp_dir, enriched.tmdb_id
                    )
                except DownloadFailed as e:
                    if first_error_kind is None:
                        first_error_kind, first_error_msg = e.kind, e.message
                    emit_log(
                        self.store,
                        self.broadcaster,
                        "warn",
                        "trailer_rejected",
                        f"{enriched.title}: candidate {candidate.key} rejected "
                        f"({e.kind.value}): {e.message}",
                        enriched.tmdb_id,
                    )
                    if e.kind == ErrorKind.ENVIRONMENT:
                        env_error = (e.kind, e.message)
                        break
                    continue

                written = self.writer.write_movie(enriched, result.path)
                self.store.set_status(
                    enriched.tmdb_id,
                    Status.READY,
                    file_path=written.video_path,
                    folder=written.folder,
                    youtube_key=candidate.key,
                    last_checked=now,
                )
                emit_log(
                    self.store,
                    self.broadcaster,
                    "info",
                    "ready",
                    f"Downloaded {enriched.title}",
                    enriched.tmdb_id,
                )
                summary.downloaded += 1
                newly_written.append(enriched.tmdb_id)
                succeeded = True
                break

            if not succeeded:
                if env_error is not None:
                    # The real cause is the host environment, not the
                    # trailer — report it as such, not as "all candidates
                    # failed" (which would surface a misleading per-video
                    # reason instead).
                    final_kind, final_msg = env_error
                    event = "environment_error"
                    log_msg = (
                        f"{enriched.title}: aborting candidate loop after an "
                        f"ENVIRONMENT error (not a bad trailer) — "
                        f"({final_kind.value}): {final_msg}"
                    )
                else:
                    final_kind = first_error_kind or ErrorKind.NO_FORMAT
                    final_msg = (
                        first_error_msg or "pre-validate failed: no suitable format"
                    )
                    event = "download_failed"
                    log_msg = (
                        f"{enriched.title}: all trailer candidates failed "
                        f"({final_kind.value}): {final_msg}"
                    )
                self.store.set_status(
                    enriched.tmdb_id,
                    Status.FAILED,
                    error_kind=final_kind.value,
                    error_msg=final_msg,
                    last_checked=now,
                )
                emit_log(
                    self.store,
                    self.broadcaster,
                    "error",
                    event,
                    log_msg,
                    enriched.tmdb_id,
                )
                summary.failed += 1

        if self.jellyfin is not None:
            self.jellyfin.refresh_library()
            self._persist_jellyfin_item_ids(newly_written)
        emit_log(
            self.store,
            self.broadcaster,
            "info",
            "run_done",
            f"Refresh complete: {summary.downloaded} downloaded, "
            f"{summary.skipped} skipped, {summary.failed} failed",
        )
        return summary

    def _persist_jellyfin_item_ids(self, tmdb_ids: list[int]) -> None:
        """After the Jellyfin library add-scan (spec §7), look each
        newly-written movie up by TMDB provider id and persist the resulting
        Jellyfin item id, so later reaper deletes don't need a fallback
        lookup. Best-effort: a lookup failure is logged, never fatal."""
        for tmdb_id in tmdb_ids:
            try:
                item_id = self.jellyfin.find_item_by_tmdb(tmdb_id)
            except Exception as e:  # noqa: BLE001
                emit_log(
                    self.store,
                    self.broadcaster,
                    "warn",
                    "jellyfin_lookup_failed",
                    f"Jellyfin lookup failed for tmdb {tmdb_id}: {e}",
                    tmdb_id,
                )
                continue
            if not item_id:
                continue
            movie = self.store.get_movie(tmdb_id)
            if movie is None:
                continue
            self.store.set_status(tmdb_id, movie.status, jellyfin_item_id=item_id)
