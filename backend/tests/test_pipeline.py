import os
import shutil
from datetime import UTC, datetime

from marquee.config import Config
from marquee.store import Store
from marquee.models import EnrichedMovie, Movie, MovieCandidate, Status
from marquee.downloader import DownloadResult, DownloadFailed, ProbeResult
from marquee.models import ErrorKind
from marquee.library.reaper import compute_expires_at
from marquee.library.writer import WrittenMovie
from marquee import pipeline as pipeline_mod
from marquee.pipeline import RefreshPipeline, RunSummary
from marquee.api.sse import Broadcaster


def make_config(tmp_path):
    return Config(
        tmdb_token="x",
        sources=["upcoming"],
        config_dir=str(tmp_path / "config"),
        library_dir=str(tmp_path / "lib"),
        count=50,
        region="US",
        language="en-US",
    )


def make_enriched(**over):
    from marquee.models import TrailerVideo

    base = dict(
        tmdb_id=1,
        title="M",
        year=2026,
        overview="o",
        popularity=9.0,
        source="upcoming",
        poster_path="/p.jpg",
        backdrop_path=None,
        runtime=100,
        genres=[],
        studios=[],
        certification=None,
        premiere_date="2026-12-18",
        digital_date=None,
        digital_date_source="none",
        youtube_key="YT1",
        trailer=TrailerVideo(
            key="YT1",
            site="YouTube",
            type="Trailer",
            official=True,
            size=1080,
            iso_639_1="en",
            published_at="2026-06-01",
        ),
    )
    base.update(over)
    return EnrichedMovie(**base)


def _ok_probe():
    return ProbeResult(ok=True, duration=90, title="M", has_maxheight=True, availability="public")


class FakeDownloader:
    def __init__(self, probe_ok=True):
        self.calls = []
        self.probe_calls = []
        self._probe_ok = probe_ok

    def probe(self, url):
        self.probe_calls.append(url)
        return ProbeResult(
            ok=self._probe_ok, duration=90, title="M",
            has_maxheight=self._probe_ok, availability="public",
        )

    def download(self, url, dest_dir, tmdb_id):
        self.calls.append((url, tmdb_id))
        os.makedirs(dest_dir, exist_ok=True)
        p = os.path.join(dest_dir, f"{tmdb_id}.mkv")
        open(p, "wb").close()
        return DownloadResult(path=p, title="M", duration=90, ext="mkv", video_id=str(tmdb_id))


class FailingDownloader:
    def probe(self, url):
        return _ok_probe()

    def download(self, url, dest_dir, tmdb_id):
        raise DownloadFailed(ErrorKind.BOT_CHECK, "bot")


class FakeWriter:
    def __init__(self, libdir):
        self.libdir = libdir

    def write_movie(self, m, source_video):
        folder = os.path.join(self.libdir, str(m.tmdb_id))
        os.makedirs(folder, exist_ok=True)
        vp = os.path.join(folder, "movie.mkv")
        shutil.move(source_video, vp)
        return WrittenMovie(
            folder=folder, video_path=vp, nfo_path=os.path.join(folder, "movie.nfo"),
            poster_path=None, backdrop_path=None,
        )


class FakeJellyfin:
    def __init__(self, items=None):
        self.refreshed = 0
        self._items = items or {}
        self.find_calls = []

    def refresh_library(self):
        self.refreshed += 1

    def find_item_by_tmdb(self, tmdb_id):
        self.find_calls.append(tmdb_id)
        return self._items.get(tmdb_id)


class RaisingFindJellyfin(FakeJellyfin):
    def find_item_by_tmdb(self, tmdb_id):
        self.find_calls.append(tmdb_id)
        raise RuntimeError("jellyfin lookup boom")


def build(tmp_path, downloader, monkeypatch, candidates, enriched_list, jellyfin=None):
    cfg = make_config(tmp_path)
    store = Store(str(tmp_path / "state.db"))
    it = iter(enriched_list)
    monkeypatch.setattr(pipeline_mod, "discover", lambda *a, **k: candidates)
    monkeypatch.setattr(pipeline_mod, "enrich", lambda *a, **k: next(it))
    jf = jellyfin if jellyfin is not None else FakeJellyfin()
    p = RefreshPipeline(
        client=object(),
        downloader=downloader,
        writer=FakeWriter(cfg.library_dir),
        reaper=object(),
        jellyfin=jf,
        store=store,
        config=cfg,
        broadcaster=Broadcaster(),
    )
    return p, store, jf


def cand(tmdb_id=1):
    return MovieCandidate(
        tmdb_id=tmdb_id, title="M", year=2026, overview="o", popularity=9.0,
        poster_path="/p.jpg", backdrop_path=None, source="upcoming",
        release_date="2026-12-18",
    )


def test_run_downloads_and_writes(tmp_path, monkeypatch):
    dl = FakeDownloader()
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()])
    summary = p.run()
    assert isinstance(summary, RunSummary)
    assert summary.discovered == 1
    assert summary.downloaded == 1
    assert summary.failed == 0
    m = store.get_movie(1)
    assert m.status == Status.READY
    assert m.file_path and os.path.exists(m.file_path)
    assert jf.refreshed == 1
    assert dl.calls == [("https://www.youtube.com/watch?v=YT1", 1)]


def test_run_idempotent_skips_ready(tmp_path, monkeypatch):
    dl = FakeDownloader()
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()])
    p.run()
    # second pass: re-inject discover/enrich to return same movie
    monkeypatch.setattr(pipeline_mod, "discover", lambda *a, **k: [cand()])
    it = iter([make_enriched()])
    monkeypatch.setattr(pipeline_mod, "enrich", lambda *a, **k: next(it))
    summary = p.run()
    assert summary.skipped == 1
    assert summary.downloaded == 0
    assert len(dl.calls) == 1  # not re-downloaded


def test_run_no_trailer_marks_failed(tmp_path, monkeypatch):
    dl = FakeDownloader()
    p, store, jf = build(
        tmp_path, dl, monkeypatch, [cand()], [make_enriched(youtube_key=None, trailer=None)]
    )
    summary = p.run()
    assert summary.failed == 1
    assert summary.downloaded == 0
    m = store.get_movie(1)
    assert m.status == Status.FAILED
    assert m.error_kind == ErrorKind.NO_TRAILER.value


def test_run_transient_no_trailer_does_not_demote_ready_movie(tmp_path, monkeypatch):
    dl = FakeDownloader()
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()])
    summary = p.run()
    assert summary.downloaded == 1
    ready = store.get_movie(1)
    assert ready.status == Status.READY
    assert ready.file_path and os.path.exists(ready.file_path)
    original_jellyfin_item_id = ready.jellyfin_item_id

    # Second pass: re-enrich transiently comes back with no trailer at all
    # (e.g. TMDB dropped the video entry). The already-READY movie with a
    # file on disk must not be demoted to FAILED.
    monkeypatch.setattr(pipeline_mod, "discover", lambda *a, **k: [cand()])
    it = iter([make_enriched(youtube_key=None, trailer=None)])
    monkeypatch.setattr(pipeline_mod, "enrich", lambda *a, **k: next(it))
    summary = p.run()

    assert summary.failed == 0
    assert summary.skipped == 1
    m = store.get_movie(1)
    assert m.status == Status.READY
    assert m.file_path == ready.file_path
    assert m.folder == ready.folder
    assert m.jellyfin_item_id == original_jellyfin_item_id
    assert m.error_kind is None


def test_run_no_trailer_marks_failed_preserves_jellyfin_item_id(tmp_path, monkeypatch):
    dl = FakeDownloader()
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()])
    p.run()
    store.set_status(1, Status.READY, jellyfin_item_id="jf-1")

    # Re-enrich with no trailer, but the existing movie is no longer a
    # READY-with-file-on-disk case (file missing) -> falls through to the
    # normal FAILED path, which must still preserve jellyfin_item_id.
    m = store.get_movie(1)
    os.remove(m.file_path)
    monkeypatch.setattr(pipeline_mod, "discover", lambda *a, **k: [cand()])
    it = iter([make_enriched(youtube_key=None, trailer=None)])
    monkeypatch.setattr(pipeline_mod, "enrich", lambda *a, **k: next(it))
    summary = p.run()

    assert summary.failed == 1
    failed = store.get_movie(1)
    assert failed.status == Status.FAILED
    assert failed.error_kind == ErrorKind.NO_TRAILER.value
    assert failed.jellyfin_item_id == "jf-1"


def test_run_download_failure_marks_failed(tmp_path, monkeypatch):
    p, store, jf = build(tmp_path, FailingDownloader(), monkeypatch, [cand()], [make_enriched()])
    summary = p.run()
    assert summary.failed == 1
    m = store.get_movie(1)
    assert m.status == Status.FAILED
    assert m.error_kind == ErrorKind.BOT_CHECK.value


def test_run_probe_not_ok_marks_failed_and_skips_download(tmp_path, monkeypatch):
    dl = FakeDownloader(probe_ok=False)
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()])
    summary = p.run()
    assert summary.failed == 1
    assert summary.downloaded == 0
    m = store.get_movie(1)
    assert m.status == Status.FAILED
    assert m.error_kind == ErrorKind.NO_FORMAT.value
    assert dl.probe_calls == ["https://www.youtube.com/watch?v=YT1"]
    assert dl.calls == []  # download() NOT called


# ----- jellyfin_item_id persistence (spec §7) -----


def test_run_persists_jellyfin_item_id_for_newly_written_movie(tmp_path, monkeypatch):
    dl = FakeDownloader()
    jf = FakeJellyfin(items={1: "JF-ITEM-1"})
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()], jellyfin=jf)
    summary = p.run()
    assert summary.downloaded == 1
    m = store.get_movie(1)
    assert m.jellyfin_item_id == "JF-ITEM-1"
    assert m.status == Status.READY  # written using the movie's current status
    assert jf.find_calls == [1]


def test_run_does_not_look_up_jellyfin_for_skipped_or_failed_movies(tmp_path, monkeypatch):
    # Only movies actually downloaded in this run should trigger a lookup.
    dl = FakeDownloader(probe_ok=False)
    jf = FakeJellyfin(items={1: "JF-ITEM-1"})
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()], jellyfin=jf)
    summary = p.run()
    assert summary.failed == 1
    assert jf.find_calls == []
    assert store.get_movie(1).jellyfin_item_id is None


def test_run_jellyfin_lookup_exception_does_not_crash_run(tmp_path, monkeypatch):
    dl = FakeDownloader()
    jf = RaisingFindJellyfin()
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()], jellyfin=jf)
    summary = p.run()  # must not raise despite the lookup failing
    assert summary.downloaded == 1
    m = store.get_movie(1)
    assert m.status == Status.READY
    assert m.jellyfin_item_id is None
    assert jf.find_calls == [1]


def test_run_skips_jellyfin_lookup_when_no_jellyfin_configured(tmp_path, monkeypatch):
    dl = FakeDownloader()
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()], jellyfin=None)
    cfg = make_config(tmp_path)
    store2 = Store(str(tmp_path / "state2.db"))
    p2 = RefreshPipeline(
        client=object(), downloader=dl, writer=FakeWriter(cfg.library_dir),
        reaper=object(), jellyfin=None, store=store2, config=cfg, broadcaster=Broadcaster(),
    )
    monkeypatch.setattr(pipeline_mod, "discover", lambda *a, **k: [cand()])
    it2 = iter([make_enriched()])
    monkeypatch.setattr(pipeline_mod, "enrich", lambda *a, **k: next(it2))
    summary = p2.run()  # must not raise with jellyfin=None
    assert summary.downloaded == 1
    assert store2.get_movie(1).jellyfin_item_id is None


# ----- QUEUED movies outside the discovered top-N (manual download, spec §7) -----


def test_run_downloads_queued_movie_not_in_discovered_set(tmp_path, monkeypatch):
    # A movie manually queued via POST /api/movies/{id}/download that isn't
    # among this run's freshly-discovered candidates must still be
    # re-enriched and downloaded.
    dl = FakeDownloader()
    p, store, jf = build(tmp_path, dl, monkeypatch, [], [])
    queued = _movie_row(tmdb_id=42, status=Status.QUEUED)
    store.upsert_movie(queued)

    monkeypatch.setattr(pipeline_mod, "discover", lambda *a, **k: [])
    it = iter([make_enriched(tmdb_id=42)])
    monkeypatch.setattr(pipeline_mod, "enrich", lambda *a, **k: next(it))

    summary = p.run()
    assert summary.downloaded == 1
    m = store.get_movie(42)
    assert m.status == Status.READY
    assert m.file_path and os.path.exists(m.file_path)
    assert dl.calls == [("https://www.youtube.com/watch?v=YT1", 42)]


def test_run_discovered_candidates_take_priority_over_queued_duplicate(tmp_path, monkeypatch):
    # A movie that's both freshly-discovered AND already QUEUED must be
    # processed exactly once (via the discovered path), not twice.
    dl = FakeDownloader()
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand(1)], [make_enriched()])
    store.upsert_movie(_movie_row(tmdb_id=1, status=Status.QUEUED))
    summary = p.run()
    assert summary.downloaded == 1
    assert dl.calls == [("https://www.youtube.com/watch?v=YT1", 1)]  # called once


# ----- expires_at computation (spec §7 / Reaper parity) -----


def test_run_sets_expires_at_when_digital_date_present(tmp_path, monkeypatch):
    dl = FakeDownloader()
    digital = datetime(2026, 6, 1, tzinfo=UTC)
    p, store, jf = build(
        tmp_path, dl, monkeypatch, [cand()], [make_enriched(digital_date=digital)]
    )
    p.run()
    m = store.get_movie(1)
    assert m.expires_at is not None
    assert m.expires_at == compute_expires_at(digital, grace_days=0, tz="UTC")


def test_run_leaves_expires_at_none_when_no_digital_date(tmp_path, monkeypatch):
    dl = FakeDownloader()
    p, store, jf = build(tmp_path, dl, monkeypatch, [cand()], [make_enriched()])
    p.run()
    assert store.get_movie(1).expires_at is None


def _movie_row(tmdb_id=1, status=Status.QUEUED, **over):
    base = dict(
        tmdb_id=tmdb_id, title="M", year=2026, overview="o", runtime=100, genres=[],
        studios=[], certification=None, premiere_date="2026-12-18", digital_date=None,
        digital_date_source="none", region="US", popularity=9.0, poster_path="/p.jpg",
        backdrop_path=None, youtube_key=None, status=status, file_path=None, folder=None,
        jellyfin_item_id=None, pinned=False, added_at=datetime(2026, 1, 1, tzinfo=UTC),
        expires_at=None, last_checked=None, error_kind=None, error_msg=None,
    )
    base.update(over)
    return Movie(**base)
