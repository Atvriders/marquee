from datetime import UTC, datetime, timedelta

from marquee.config import Config
from marquee.models import Movie, Status
from marquee.store import Store
from marquee.watchdog import Watchdog

CINEMA_MODE_ID = "5fcefe1b-df1f-4596-ac57-f2f939c294c5"

COMING_SOON_LIB = {
    "Name": "Coming Soon",
    "ItemId": "LIB-CS",
    "CollectionType": "movies",
    "Locations": ["/library"],
    "LibraryOptions": {
        "TypeOptions": [
            {"Type": "Movie", "MetadataFetchers": ["Nfo"], "ImageFetchers": []}
        ],
        "LocalMetadataReaderOrder": ["Nfo"],
        "DisabledLocalMetadataReaders": [],
    },
}

OTHER_LIB = {
    "Name": "Movies",
    "ItemId": "LIB-MAIN",
    "CollectionType": "movies",
    "Locations": ["/data/movies"],
    "LibraryOptions": {},
}

PLUGIN_ACTIVE = {
    "Name": "Cinema Mode",
    "Id": CINEMA_MODE_ID,
    "Version": "1.2.3",
    "Status": "Active",
}


class FakeJellyfin:
    def __init__(
        self,
        *,
        info=None,
        folders=None,
        server_config=None,
        plugin_list=None,
        admin_id="ADMIN1",
        items_by_lib=None,
        intros_result=None,
        raise_on=None,
    ):
        self.info = {"Version": "10.11.0"} if info is None else info
        self.folders = [COMING_SOON_LIB, OTHER_LIB] if folders is None else folders
        self.server_config = {} if server_config is None else server_config
        self.plugin_list = [PLUGIN_ACTIVE] if plugin_list is None else plugin_list
        self.admin_id = admin_id
        self.items_by_lib = items_by_lib or {}
        self.intros_result = [{"Id": "ITEM-1"}] if intros_result is None else intros_result
        self.raise_on = raise_on or set()
        self.calls: list[str] = []

    def _maybe_raise(self, name):
        self.calls.append(name)
        if name in self.raise_on:
            raise RuntimeError(f"{name} failed")

    def system_info(self):
        self._maybe_raise("system_info")
        return self.info

    def virtual_folders(self):
        self._maybe_raise("virtual_folders")
        return self.folders

    def server_configuration(self):
        self._maybe_raise("server_configuration")
        return self.server_config

    def plugins(self):
        self._maybe_raise("plugins")
        return self.plugin_list

    def admin_user_id(self):
        self._maybe_raise("admin_user_id")
        return self.admin_id

    def library_items(self, library_item_id, user_id=None):
        self._maybe_raise("library_items")
        return self.items_by_lib.get(library_item_id, [])

    def intros(self, item_id, user_id):
        self._maybe_raise("intros")
        return self.intros_result


def make_config(tmp_path, **over):
    base = dict(
        tmdb_token="x", sources=["upcoming"], config_dir=str(tmp_path),
        library_dir="/library", tz="UTC", jellyfin_library_name="Coming Soon",
    )
    base.update(over)
    return Config(**base)


def mkmovie(tmdb_id=1, **over):
    base = dict(
        tmdb_id=tmdb_id, title="M", year=2026, overview="", runtime=1, genres=[],
        studios=[], certification=None, premiere_date=None, digital_date=None,
        digital_date_source="none", region="US", popularity=1.0, poster_path=None,
        backdrop_path=None, youtube_key="k", status=Status.READY, file_path=None,
        folder=None, jellyfin_item_id="ITEM-1", pinned=False,
        added_at=datetime(2026, 1, 1, tzinfo=UTC), expires_at=None, last_checked=None,
        error_kind=None, error_msg=None,
    )
    base.update(over)
    return Movie(**base)


def build(tmp_path, jf, store=None, **cfg_over):
    store = store or Store(str(tmp_path / "s.db"))
    config = make_config(tmp_path, **cfg_over)
    return Watchdog(store, jf, config), store


def by_id(result, check_id):
    return next(c for c in result["checks"] if c["id"] == check_id)


def _ready_movie_with_trailer(tmp_path, tmdb_id=1):
    folder = tmp_path / "movie1"
    trailers = folder / "trailers"
    trailers.mkdir(parents=True)
    (trailers / "movie1-trailer.mkv").write_text("x")
    return mkmovie(tmdb_id, folder=str(folder))


def test_all_good(tmp_path):
    movie = _ready_movie_with_trailer(tmp_path)
    now_iso = datetime.now(UTC).isoformat()
    jf = FakeJellyfin(
        items_by_lib={
            "LIB-CS": [
                {
                    "Id": "ITEM-1",
                    "ProviderIds": {"Tmdb": "1"},
                    "UserData": {"PlayCount": 5, "LastPlayedDate": now_iso},
                }
            ],
            "LIB-MAIN": [{"Id": "OTHER-ITEM"}],
        },
        intros_result=[{"Id": "ITEM-1"}],
    )
    wd, store = build(tmp_path, jf)
    store.upsert_movie(movie)

    result = wd.run()

    assert result["ok"] is True
    assert "checked_at" in result
    statuses = {c["id"]: c["status"] for c in result["checks"]}
    assert statuses == {
        "jellyfin_reachable": "ok",
        "library_found": "ok",
        "library_metadata_safe": "ok",
        "items_visible": "ok",
        "cinema_plugin": "ok",
        "trailer_extras_present": "ok",
        "cinema_mode_plays_trailers": "ok",
        "playback_evidence": "ok",
    }
    # persisted for later GET /api/watchdog
    assert wd.get_last() == result


def test_jellyfin_unreachable_skips_everything(tmp_path):
    jf = FakeJellyfin(raise_on={"system_info"})
    wd, store = build(tmp_path, jf)

    result = wd.run()

    assert result["ok"] is False
    assert by_id(result, "jellyfin_reachable")["status"] == "fail"
    for check_id in (
        "library_found", "library_metadata_safe", "items_visible", "cinema_plugin",
        "trailer_extras_present", "cinema_mode_plays_trailers", "playback_evidence",
    ):
        assert by_id(result, check_id)["status"] == "skip"
    # only System/Info was ever attempted
    assert jf.calls == ["system_info"]


def test_jellyfin_none_skips_everything(tmp_path):
    wd, store = build(tmp_path, None)
    result = wd.run()
    assert result["ok"] is False
    assert by_id(result, "jellyfin_reachable")["status"] == "fail"
    assert by_id(result, "library_found")["status"] == "skip"


def test_tmdb_fetcher_enabled_fails(tmp_path):
    lib = {
        **COMING_SOON_LIB,
        "LibraryOptions": {
            "TypeOptions": [
                {"Type": "Movie", "MetadataFetchers": ["TheMovieDb", "Nfo"], "ImageFetchers": []}
            ],
            "LocalMetadataReaderOrder": ["Nfo"],
            "DisabledLocalMetadataReaders": [],
        },
    }
    jf = FakeJellyfin(folders=[lib, OTHER_LIB])
    wd, store = build(tmp_path, jf)

    result = wd.run()

    check = by_id(result, "library_metadata_safe")
    assert check["status"] == "fail"
    assert "TheMovieDb" in check["detail"]
    assert result["ok"] is False


def test_empty_type_options_falls_back_to_server_defaults_which_enable_tmdb(tmp_path):
    # The trap: no Movie TypeOptions entry at all -> Jellyfin uses server
    # defaults (TMDb enabled) unless explicitly disabled server-wide.
    lib = {
        **COMING_SOON_LIB,
        "LibraryOptions": {
            "TypeOptions": [],
            "LocalMetadataReaderOrder": ["Nfo"],
            "DisabledLocalMetadataReaders": [],
        },
    }
    jf = FakeJellyfin(
        folders=[lib, OTHER_LIB],
        server_config={"MetadataOptions": [{"ItemType": "Movie"}]},  # nothing disabled
    )
    wd, store = build(tmp_path, jf)

    result = wd.run()

    check = by_id(result, "library_metadata_safe")
    assert check["status"] == "fail"
    assert "server-wide defaults" in check["detail"]


def test_empty_type_options_but_server_disables_tmdb_is_safe(tmp_path):
    lib = {
        **COMING_SOON_LIB,
        "LibraryOptions": {
            "TypeOptions": [],
            "LocalMetadataReaderOrder": ["Nfo"],
            "DisabledLocalMetadataReaders": [],
        },
    }
    jf = FakeJellyfin(
        folders=[lib, OTHER_LIB],
        server_config={
            "MetadataOptions": [
                {
                    "ItemType": "Movie",
                    "DisabledMetadataFetchers": ["TheMovieDb", "The Open Movie Database"],
                    "DisabledImageFetchers": ["TheMovieDb", "The Open Movie Database"],
                }
            ]
        },
    )
    wd, store = build(tmp_path, jf)

    result = wd.run()

    assert by_id(result, "library_metadata_safe")["status"] == "ok"


def test_jellyfin_sees_zero_items_fails(tmp_path):
    movie = mkmovie(1)
    jf = FakeJellyfin(items_by_lib={"LIB-CS": [], "LIB-MAIN": [{"Id": "X"}]})
    wd, store = build(tmp_path, jf)
    store.upsert_movie(movie)

    result = wd.run()

    check = by_id(result, "items_visible")
    assert check["status"] == "fail"
    assert "0 items" in check["detail"]
    assert result["ok"] is False


def test_plugin_missing_fails(tmp_path):
    jf = FakeJellyfin(plugin_list=[{"Name": "Something Else", "Id": "other-id"}])
    wd, store = build(tmp_path, jf)

    result = wd.run()

    check = by_id(result, "cinema_plugin")
    assert check["status"] == "fail"
    assert result["ok"] is False
    # self-diagnosing: the names of the plugins that WERE found are surfaced
    assert "Something Else" in check["detail"]


def test_plugin_present_but_not_active_warns(tmp_path):
    jf = FakeJellyfin(plugin_list=[{**PLUGIN_ACTIVE, "Status": "Disabled"}])
    wd, store = build(tmp_path, jf)

    result = wd.run()

    check = by_id(result, "cinema_plugin")
    assert check["status"] == "warn"
    assert result["ok"] is True  # warn doesn't flip overall ok


def test_plugin_found_when_guid_is_dashless(tmp_path):
    # VERIFIED against the user's live Jellyfin: GET /Plugins returns GUIDs
    # WITHOUT dashes. This is the real-world case the exact-match bug missed.
    dashless = {**PLUGIN_ACTIVE, "Id": CINEMA_MODE_ID.replace("-", "")}
    jf = FakeJellyfin(plugin_list=[dashless])
    wd, store = build(tmp_path, jf)

    result = wd.run()

    check = by_id(result, "cinema_plugin")
    assert check["status"] == "ok"
    assert result["ok"] is True


def test_plugin_found_when_guid_is_dashed(tmp_path):
    dashed = {**PLUGIN_ACTIVE, "Id": CINEMA_MODE_ID}
    jf = FakeJellyfin(plugin_list=[dashed])
    wd, store = build(tmp_path, jf)

    result = wd.run()

    check = by_id(result, "cinema_plugin")
    assert check["status"] == "ok"


def test_plugin_found_by_name_when_guid_does_not_match(tmp_path):
    # A fork/rebuild with a different GUID must still be detected by name.
    forked = {**PLUGIN_ACTIVE, "Id": "deadbeefdeadbeefdeadbeefdeadbeef", "Name": "Cinema Mode Fork"}
    jf = FakeJellyfin(plugin_list=[forked])
    wd, store = build(tmp_path, jf)

    result = wd.run()

    check = by_id(result, "cinema_plugin")
    assert check["status"] == "ok"
    assert "name" in check["detail"].lower()


def test_plugin_list_call_raises_reports_fail_not_not_installed(tmp_path):
    jf = FakeJellyfin(raise_on={"plugins"})
    wd, store = build(tmp_path, jf)

    result = wd.run()

    check = by_id(result, "cinema_plugin")
    assert check["status"] == "fail"
    assert "could not list plugins" in check["detail"]
    assert "not installed" not in check["detail"]


def test_intros_empty_fails(tmp_path):
    jf = FakeJellyfin(
        items_by_lib={"LIB-MAIN": [{"Id": "OTHER-ITEM"}]},
        intros_result=[],
    )
    wd, store = build(tmp_path, jf)

    result = wd.run()

    check = by_id(result, "cinema_mode_plays_trailers")
    assert check["status"] == "fail"
    assert "empty" in check["detail"].lower()
    assert result["ok"] is False


def test_intros_skips_when_only_one_movies_library(tmp_path):
    jf = FakeJellyfin(folders=[COMING_SOON_LIB])
    wd, store = build(tmp_path, jf)

    result = wd.run()

    assert by_id(result, "cinema_mode_plays_trailers")["status"] == "skip"


def test_no_playback_warns(tmp_path):
    jf = FakeJellyfin(
        items_by_lib={
            "LIB-CS": [{"Id": "ITEM-1", "UserData": {"PlayCount": 0}}],
            "LIB-MAIN": [{"Id": "OTHER-ITEM"}],
        },
    )
    wd, store = build(tmp_path, jf)

    result = wd.run()

    check = by_id(result, "playback_evidence")
    assert check["status"] == "warn"
    assert result["ok"] is True


def test_stale_playback_warns(tmp_path):
    stale = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    jf = FakeJellyfin(
        items_by_lib={
            "LIB-CS": [
                {"Id": "ITEM-1", "UserData": {"PlayCount": 3, "LastPlayedDate": stale}}
            ],
            "LIB-MAIN": [{"Id": "OTHER-ITEM"}],
        },
    )
    wd, store = build(tmp_path, jf, watchdog_stale_play_days=7)

    result = wd.run()

    check = by_id(result, "playback_evidence")
    assert check["status"] == "warn"
    assert "stale" in check["detail"].lower() or "older than" in check["detail"]


def test_trailer_extra_disabled_warns(tmp_path):
    movie = mkmovie(1, folder=str(tmp_path / "movie1"))
    jf = FakeJellyfin(items_by_lib={"LIB-CS": [], "LIB-MAIN": [{"Id": "X"}]})
    wd, store = build(tmp_path, jf, trailer_extra=False)
    store.upsert_movie(movie)

    result = wd.run()

    check = by_id(result, "trailer_extras_present")
    assert check["status"] == "warn"
    assert "TRAILER_EXTRA" in check["hint"]


def test_library_not_found_fails_and_skips_rest(tmp_path):
    jf = FakeJellyfin()
    wd, store = build(tmp_path, jf, jellyfin_library_name="Does Not Exist")

    result = wd.run()

    assert by_id(result, "library_found")["status"] == "fail"
    assert by_id(result, "items_visible")["status"] == "skip"
    assert result["ok"] is False


def test_library_found_warns_on_wrong_collection_type(tmp_path):
    lib = {**COMING_SOON_LIB, "CollectionType": "tvshows"}
    jf = FakeJellyfin(folders=[lib, OTHER_LIB])
    wd, store = build(tmp_path, jf)

    result = wd.run()

    assert by_id(result, "library_found")["status"] == "warn"


def test_state_change_from_ok_to_fail_emits_activity_log(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    good_jf = FakeJellyfin(plugin_list=[PLUGIN_ACTIVE])
    wd, _ = build(tmp_path, good_jf, store=store)
    first = wd.run()
    assert by_id(first, "cinema_plugin")["status"] == "ok"

    before = len(store.recent_activity())

    bad_jf = FakeJellyfin(plugin_list=[{"Name": "Other", "Id": "nope"}])
    wd2, _ = build(tmp_path, bad_jf, store=store)
    second = wd2.run()
    assert by_id(second, "cinema_plugin")["status"] == "fail"

    after = store.recent_activity()
    assert len(after) > before
    assert any(row["event"] == "watchdog_regression" and row["level"] == "error" for row in after)


def test_no_regression_log_when_already_failing(tmp_path):
    store = Store(str(tmp_path / "s.db"))
    bad_jf = FakeJellyfin(plugin_list=[{"Name": "Other", "Id": "nope"}])
    wd, _ = build(tmp_path, bad_jf, store=store)
    wd.run()
    before = len(store.recent_activity())
    wd.run()
    after = store.recent_activity()
    assert len(after) == before  # still failing, not a *new* regression


def test_get_last_none_before_first_run(tmp_path):
    jf = FakeJellyfin()
    wd, store = build(tmp_path, jf)
    assert wd.get_last() is None


def test_basename_match_used_when_no_name_and_no_tmdb_overlap(tmp_path):
    lib_a = {**COMING_SOON_LIB, "Name": "A", "Locations": ["/library"]}
    lib_b = {**OTHER_LIB, "Name": "B", "Locations": ["/somewhere/else"]}
    jf = FakeJellyfin(folders=[lib_a, lib_b], items_by_lib={})
    wd, store = build(
        tmp_path, jf, jellyfin_library_name=None, library_dir="/library"
    )

    result = wd.run()

    check = by_id(result, "library_found")
    assert check["status"] == "ok"
    assert "LIB-CS" in check["detail"]
