"""The Jellyfin watchdog: an end-to-end sanity check that Cinema Mode will
actually play Marquee's trailers, using verified Jellyfin API semantics
(see the checks below for the specific traps each one guards against)."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime

from marquee.models import Status

_CINEMA_MODE_PLUGIN_ID = "5fcefe1b-df1f-4596-ac57-f2f939c294c5"
_TMDB_PROVIDER_NAMES = {"TheMovieDb", "The Open Movie Database"}
_SETTINGS_KEY = "_watchdog_last"


def _norm_guid(value: str | None) -> str:
    """Jellyfin's /Plugins endpoint returns GUIDs WITHOUT dashes (verified
    against a live server), but other endpoints/config may return the dashed
    form. Never compare raw GUIDs — always normalize both sides through
    this."""
    return (value or "").replace("-", "").lower()


_LABELS: dict[str, str] = {
    "jellyfin_reachable": "Jellyfin reachable",
    "library_found": "Coming-Soon library found",
    "library_metadata_safe": "Library metadata safe from overwrite",
    "items_visible": "Items visible in Jellyfin",
    "cinema_plugin": "Cinema Mode plugin installed",
    "trailer_extras_present": "Trailer extras written",
    "cinema_mode_plays_trailers": "Cinema Mode plays trailers (ground truth)",
    "playback_evidence": "Playback evidence",
}
_ORDER: list[str] = list(_LABELS)


def _check(check_id: str, status: str, detail: str, hint: str | None = None) -> dict:
    return {
        "id": check_id,
        "label": _LABELS[check_id],
        "status": status,
        "detail": detail,
        "hint": hint,
    }


class Watchdog:
    def __init__(self, store, jellyfin, config):
        self.store = store
        self.jellyfin = jellyfin
        self.config = config

    # ----- public API -----

    def run(self) -> dict:
        checked_at = datetime.now(UTC).isoformat()
        checks: list[dict] = []

        reachable = self._check_reachable()
        checks.append(reachable)
        if reachable["status"] != "ok":
            self._skip_rest(checks, "jellyfin_reachable", reachable["detail"])
            return self._finalize(checks, checked_at)

        try:
            folders = self.jellyfin.virtual_folders()
        except Exception as e:  # noqa: BLE001
            checks.append(_check("library_found", "fail", f"error listing libraries: {e}"))
            self._skip_rest(checks, "library_found", "could not enumerate Jellyfin libraries")
            return self._finalize(checks, checked_at)

        folder, library_check = self._resolve_and_check_library(folders)
        checks.append(library_check)
        if folder is None:
            self._skip_rest(
                checks, "library_found",
                "needs the Coming-Soon library identified first (see library_found)",
            )
            return self._finalize(checks, checked_at)

        library_item_id = folder.get("ItemId")

        checks.append(self._check_metadata_safe(folder))
        checks.append(self._check_items_visible(library_item_id))
        checks.append(self._check_cinema_plugin())
        checks.append(self._check_trailer_extras())
        checks.append(self._check_cinema_mode_ground_truth(folders, folder))
        checks.append(self._check_playback_evidence(library_item_id))

        return self._finalize(checks, checked_at)

    def get_last(self) -> dict | None:
        raw = self.store.get_setting(_SETTINGS_KEY)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    # ----- checks -----

    def _check_reachable(self) -> dict:
        if self.jellyfin is None:
            return _check(
                "jellyfin_reachable", "fail", "Jellyfin is not configured",
                "Set JELLYFIN_URL and JELLYFIN_API_KEY",
            )
        try:
            info = self.jellyfin.system_info()
        except Exception as e:  # noqa: BLE001
            return _check(
                "jellyfin_reachable", "fail", f"error: {e}",
                "Check JELLYFIN_URL/JELLYFIN_API_KEY and network connectivity",
            )
        version = info.get("Version", "unknown") if isinstance(info, dict) else "unknown"
        return _check("jellyfin_reachable", "ok", f"Connected (Jellyfin {version})")

    def _resolve_and_check_library(self, folders: list[dict]) -> tuple[dict | None, dict]:
        folder, method, reason = self._resolve_library(folders)
        if folder is None:
            return None, _check(
                "library_found", "fail", reason or "No matching VirtualFolders entry found",
                "Set JELLYFIN_LIBRARY_NAME to the exact library name in Jellyfin",
            )
        detail = f"Matched '{folder.get('Name')}' (ItemId {folder.get('ItemId')}) by {method}"
        if folder.get("CollectionType") != "movies":
            return folder, _check(
                "library_found", "warn", detail,
                f"CollectionType is {folder.get('CollectionType')!r}, expected 'movies'",
            )
        return folder, _check("library_found", "ok", detail)

    def _resolve_library(
        self, folders: list[dict]
    ) -> tuple[dict | None, str | None, str | None]:
        """CONFIDENT-OR-FAIL library resolution. There is exactly one way this
        should ever pick a wrong library: never. A user's real film
        collection is very often the ONLY movies-type library Jellyfin has
        (they may not have created a Coming-Soon library yet) — so unlike a
        typical "if there's only one, it must be it" heuristic, having
        exactly one movies library is NOT evidence it's ours. Every match
        below must be positive evidence (an explicit name, Marquee's own
        content, or a deliberate path/name hint); if none apply, fail loudly
        rather than silently adopting the user's real library (verified live
        bug: watchdog adopted the user's 5361-item personal collection and
        reported false-positive "Coming-Soon library found" + trailer
        playback evidence that was actually the user watching their own
        films)."""
        movies_folders = [f for f in folders if f.get("CollectionType") == "movies"]
        names = sorted(f.get("Name") or "?" for f in movies_folders)

        if self.config.jellyfin_library_name:
            # Matched by exact configured name is checked across ALL
            # folders (not just movies-type ones): an explicit name is the
            # highest-confidence signal there is, and a CollectionType
            # mismatch on the matched folder is still surfaced (as a warn,
            # by the caller) rather than silently treated as "not found".
            wanted = self.config.jellyfin_library_name.strip().lower()
            for f in folders:
                if (f.get("Name") or "").strip().lower() == wanted:
                    return f, "configured name", None
            return (
                None, None,
                f"configured JELLYFIN_LIBRARY_NAME={self.config.jellyfin_library_name!r} "
                f"not found among Jellyfin's movies libraries: {names}",
            )

        best = self._best_tmdb_match(movies_folders)
        if best is not None:
            return best, "content tmdb-id match", None

        base = os.path.basename(os.path.normpath(self.config.library_dir))
        for f in movies_folders:
            locations = f.get("Locations") or []
            path_hit = any(
                os.path.basename(os.path.normpath(loc)) == base for loc in locations
            )
            name_hit = "coming soon" in (f.get("Name") or "").lower()
            if path_hit or name_hit:
                return f, "path-or-name hint", None

        return (
            None, None,
            f"No Coming Soon library identified in Jellyfin (found movies libraries: "
            f"{names}). Marquee writes trailers to {self.config.library_dir!r} — add "
            f"that folder to Jellyfin as a Movies library, or set JELLYFIN_LIBRARY_NAME.",
        )

    def _best_tmdb_match(self, movies_folders: list[dict]) -> dict | None:
        marquee_ids = {m.tmdb_id for m in self.store.list_movies()}
        if not marquee_ids:
            return None
        best, best_score = None, 0
        for f in movies_folders:
            item_id = f.get("ItemId")
            if not item_id:
                continue
            try:
                items = self.jellyfin.library_items(item_id)
            except Exception:  # noqa: BLE001
                continue
            ids: set[int] = set()
            for it in items:
                tmdb = (it.get("ProviderIds") or {}).get("Tmdb")
                if tmdb is None:
                    continue
                try:
                    ids.add(int(tmdb))
                except (TypeError, ValueError):
                    continue
            score = len(ids & marquee_ids)
            if score > best_score:
                best, best_score = f, score
        return best

    def _check_metadata_safe(self, folder: dict) -> dict:
        library_options = folder.get("LibraryOptions") or {}
        type_options = library_options.get("TypeOptions") or []
        movie_opts = next((t for t in type_options if t.get("Type") == "Movie"), None)

        if movie_opts is not None:
            fetchers = set(movie_opts.get("MetadataFetchers") or [])
            image_fetchers = set(movie_opts.get("ImageFetchers") or [])
            bad = (fetchers | image_fetchers) & _TMDB_PROVIDER_NAMES
            source = "this library's Movie TypeOptions"
        else:
            try:
                server_cfg = self.jellyfin.server_configuration()
            except Exception as e:  # noqa: BLE001
                return _check(
                    "library_metadata_safe", "fail",
                    f"no per-library Movie TypeOptions, and could not read server "
                    f"configuration to check the fallback defaults: {e}",
                )
            metadata_options = server_cfg.get("MetadataOptions") or []
            movie_server_opts = next(
                (m for m in metadata_options if m.get("ItemType") == "Movie"), {}
            )
            disabled_fetchers = set(movie_server_opts.get("DisabledMetadataFetchers") or [])
            disabled_images = set(movie_server_opts.get("DisabledImageFetchers") or [])
            disabled = disabled_fetchers | disabled_images
            bad = _TMDB_PROVIDER_NAMES - disabled
            source = "server-wide defaults (no per-library Movie TypeOptions entry)"

        if bad:
            # NOT a failure: Cinema Mode selects trailers by LocalTrailers (the file
            # layout), not metadata, so online fetchers cannot break playback. All
            # that's at stake is whether Marquee's NFO stays authoritative — the
            # "Coming Soon"/"Trailer" tags and the "COMING SOON…" plot framing may be
            # replaced by TMDb's own (correct, richer) metadata. That's a preference.
            return _check(
                "library_metadata_safe", "warn",
                f"TMDb-family fetchers are enabled via {source}: {sorted(bad)}. Jellyfin "
                f"may replace Marquee's 'Coming Soon'/'Trailer' tags and plot framing "
                f"with TMDb's own metadata. Cinema Mode is unaffected.",
                "Fine to leave on if you prefer richer TMDb metadata. Disable "
                "TheMovieDb / The Open Movie Database as metadata+image fetchers for "
                "this library only if you want Marquee's NFO to stay authoritative.",
            )

        local_order = library_options.get("LocalMetadataReaderOrder") or []
        disabled_local = set(library_options.get("DisabledLocalMetadataReaders") or [])
        nfo_first = bool(local_order) and local_order[0] == "Nfo" and "Nfo" not in disabled_local
        if not nfo_first:
            return _check(
                "library_metadata_safe", "warn",
                f"TMDb-family metadata is disabled via {source}, but Nfo is not the "
                f"first (enabled) local metadata reader",
                "Set Nfo first in this library's Local metadata readers",
            )
        return _check(
            "library_metadata_safe", "ok",
            f"TMDb-family metadata disabled via {source}; Nfo reads first",
        )

    def _check_items_visible(self, library_item_id: str) -> dict:
        try:
            jf_items = self.jellyfin.library_items(library_item_id)
        except Exception as e:  # noqa: BLE001
            return _check("items_visible", "fail", f"error listing library items: {e}")
        jf_count = len(jf_items)
        marquee_count = len(self.store.list_movies([Status.READY]))

        if jf_count == 0 and marquee_count > 0:
            return _check(
                "items_visible", "fail",
                f"Jellyfin sees 0 items but Marquee has {marquee_count} ready movie(s)",
                "Check the library path/mount matches LIBRARY_DIR, or trigger a library scan",
            )
        if jf_count != marquee_count:
            detail = f"Jellyfin sees {jf_count} item(s), Marquee has {marquee_count} ready"
            if jf_count > marquee_count:
                detail += " (possible ghosts left behind in Jellyfin)"
            return _check("items_visible", "warn", detail)
        return _check("items_visible", "ok", f"{jf_count} item(s) match")

    def _check_cinema_plugin(self) -> dict:
        try:
            plugins = self.jellyfin.plugins()
        except Exception as e:  # noqa: BLE001
            # This is an ENVIRONMENT/connectivity failure, not evidence the
            # plugin is absent — must not be conflated with "not installed".
            return _check("cinema_plugin", "fail", f"could not list plugins: {e}")

        target = _norm_guid(_CINEMA_MODE_PLUGIN_ID)
        plugin = next((p for p in plugins if _norm_guid(p.get("Id")) == target), None)
        matched_by_name = False
        if plugin is None:
            # A fork/rebuild may ship under a different GUID; fall back to a
            # name match so it's still detected.
            plugin = next(
                (p for p in plugins if "cinema" in (p.get("Name") or "").lower()), None
            )
            matched_by_name = plugin is not None

        if plugin is None:
            found = ", ".join(sorted(p.get("Name") or "?" for p in plugins)) or "none"
            return _check(
                "cinema_plugin", "fail",
                f"Cinema Mode plugin is not installed (plugins found: {found})",
                "Install the CherryFloors Cinema Mode plugin",
            )

        status = plugin.get("Status")
        if status != "Active":
            return _check(
                "cinema_plugin", "warn", f"Cinema Mode plugin status is {status!r}",
                "Check the plugin logs / restart Jellyfin",
            )
        detail = f"Cinema Mode v{plugin.get('Version', '?')} active"
        if matched_by_name:
            detail += " (matched by name; plugin id did not match the known GUID)"
        return _check("cinema_plugin", "ok", detail)

    def _check_trailer_extras(self) -> dict:
        ready = self.store.list_movies([Status.READY])
        if not ready:
            return _check("trailer_extras_present", "ok", "No ready movies yet")
        if not self.config.trailer_extra:
            return _check(
                "trailer_extras_present", "warn",
                "TRAILER_EXTRA is disabled; Cinema Mode can never select these movies",
                "Enable TRAILER_EXTRA",
            )
        with_extra = 0
        for m in ready:
            if not m.folder:
                continue
            trailers_dir = os.path.join(m.folder, "trailers")
            try:
                if os.path.isdir(trailers_dir) and any(os.scandir(trailers_dir)):
                    with_extra += 1
            except OSError:
                continue
        detail = f"{with_extra} of {len(ready)} ready movie(s) have a trailer extra on disk"
        if with_extra == 0:
            return _check("trailer_extras_present", "warn", detail, "Re-run a refresh")
        if with_extra < len(ready):
            return _check("trailer_extras_present", "warn", detail)
        return _check("trailer_extras_present", "ok", detail)

    def _check_cinema_mode_ground_truth(self, folders: list[dict], our_library: dict) -> dict:
        movies_folders = [f for f in folders if f.get("CollectionType") == "movies"]
        our_library_id = _norm_guid(our_library.get("ItemId"))
        other_folders = [
            f for f in movies_folders if _norm_guid(f.get("ItemId")) != our_library_id
        ]
        if not other_folders:
            return _check(
                "cinema_mode_plays_trailers", "skip",
                "Only one movies library exists; nothing to cross-check against",
            )

        admin_id = self.jellyfin.admin_user_id()
        if not admin_id:
            return _check(
                "cinema_mode_plays_trailers", "fail",
                "No administrator user found to evaluate Intros as",
            )

        test_item_id = None
        for f in other_folders:
            item_id = f.get("ItemId")
            if not item_id:
                continue
            try:
                items = self.jellyfin.library_items(item_id)
            except Exception:  # noqa: BLE001
                continue
            if items:
                test_item_id = items[0].get("Id")
                break
        if test_item_id is None:
            return _check(
                "cinema_mode_plays_trailers", "skip",
                "No movie found in another library to test Cinema Mode against",
            )

        try:
            intros = self.jellyfin.intros(test_item_id, admin_id)
        except Exception as e:  # noqa: BLE001
            return _check("cinema_mode_plays_trailers", "fail", f"error calling Intros: {e}")

        if not intros:
            return _check(
                "cinema_mode_plays_trailers", "fail",
                "Cinema Mode would play nothing before this movie (Intros is empty)",
                "Check trailer extras and the Cinema Mode plugin configuration",
            )

        our_ids = {
            _norm_guid(m.jellyfin_item_id)
            for m in self.store.list_movies([Status.READY])
            if m.jellyfin_item_id
        }
        library_dir = self.config.library_dir or ""

        def _belongs_to_marquee(item: dict) -> bool:
            if _norm_guid(item.get("Id")) in our_ids:
                return True
            path = item.get("Path") or ""
            return bool(library_dir) and path.startswith(library_dir)

        matched = any(_belongs_to_marquee(i) for i in intros)
        detail = f"Intros returned {len(intros)} item(s)"
        if matched:
            return _check(
                "cinema_mode_plays_trailers", "ok", detail + "; one belongs to Marquee's library"
            )
        return _check(
            "cinema_mode_plays_trailers", "warn",
            detail + ", but none observed belong to Marquee's library (Cinema Mode "
            "selects randomly across all local trailers, so this can be a false alarm)",
        )

    def _check_playback_evidence(self, library_item_id: str) -> dict:
        admin_id = self.jellyfin.admin_user_id()
        if not admin_id:
            return _check(
                "playback_evidence", "warn",
                "No administrator user found; cannot check playback stats",
            )
        try:
            items = self.jellyfin.library_items(library_item_id, user_id=admin_id)
        except Exception as e:  # noqa: BLE001
            return _check("playback_evidence", "warn", f"error fetching playback stats: {e}")

        total_plays = 0
        last_played: datetime | None = None
        for it in items:
            ud = it.get("UserData") or {}
            total_plays += ud.get("PlayCount") or 0
            raw = ud.get("LastPlayedDate")
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            if last_played is None or dt > last_played:
                last_played = dt

        if total_plays == 0:
            return _check(
                "playback_evidence", "warn", "No plays recorded for any Coming-Soon trailer",
                "Confirm Cinema Mode is enabled and users are watching movies",
            )

        stale_days = self.config.watchdog_stale_play_days
        now = datetime.now(UTC)
        if last_played is None or (now - last_played).days > stale_days:
            staleness = (
                f", last play {last_played.isoformat()}" if last_played else ", no play date"
            )
            return _check(
                "playback_evidence", "warn",
                f"{total_plays} total play(s), but the last one is older than "
                f"{stale_days} day(s){staleness}",
            )
        return _check(
            "playback_evidence", "ok",
            f"{total_plays} total play(s), last {last_played.isoformat()}",
        )

    # ----- persistence / alerting -----

    def _skip_rest(self, checks: list[dict], from_id: str, reason: str) -> None:
        started = False
        for cid in _ORDER:
            if cid == from_id:
                started = True
                continue
            if started:
                checks.append(_check(cid, "skip", reason))

    def _finalize(self, checks: list[dict], checked_at: str) -> dict:
        ok = not any(c["status"] == "fail" for c in checks)
        result = {"ok": ok, "checks": checks, "checked_at": checked_at}
        previous = self.get_last()
        self._alert_on_changes(previous, checks)
        self.store.set_setting(_SETTINGS_KEY, json.dumps(result))
        return result

    def _alert_on_changes(self, previous: dict | None, checks: list[dict]) -> None:
        if previous is None:
            return
        prev_by_id = {c["id"]: c for c in previous.get("checks", [])}
        for c in checks:
            prev = prev_by_id.get(c["id"])
            if prev is None or prev.get("status") != "ok":
                continue
            if c["status"] in ("warn", "fail"):
                level = "error" if c["status"] == "fail" else "warn"
                self.store.log(
                    level, "watchdog_regression", f"{c['label']}: {c['detail']}"
                )
