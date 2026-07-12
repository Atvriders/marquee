import os

import httpx
import respx

from marquee.models import EnrichedMovie
from marquee.library.writer import LibraryWriter, WrittenMovie


class FakeClient:
    def build_image_url(self, path: str, size: str) -> str:
        return f"https://image.tmdb.org/t/p/{size}{path}"


def make_movie(**over):
    base = dict(
        tmdb_id=1234567,
        title="Dune: Part Three",
        year=2026,
        overview="The saga concludes.",
        popularity=99.0,
        source="upcoming",
        poster_path="/p.jpg",
        backdrop_path="/b.jpg",
        runtime=166,
        genres=["Science Fiction", "Adventure"],
        studios=["Legendary Pictures"],
        certification="PG-13",
        premiere_date="2026-12-18",
        digital_date=None,
        digital_date_source="none",
        youtube_key="yt123",
        trailer=None,
    )
    base.update(over)
    return EnrichedMovie(**base)


def test_sanitize_strips_illegal_and_collapses():
    assert LibraryWriter.sanitize("Dune: Part Three") == "Dune Part Three"
    assert LibraryWriter.sanitize('A/B\\C:D?E*F') == "A B C D E F"
    assert LibraryWriter.sanitize("Trailing dots...") == "Trailing dots"


def test_folder_name():
    w = LibraryWriter("/library", FakeClient())
    assert (
        w.folder_name("Dune: Part Three", 2026, 1234567)
        == "Dune Part Three (2026) [tmdbid-1234567]"
    )
    assert w.folder_name("No Year", None, 5) == "No Year [tmdbid-5]"


def test_render_nfo_matches_golden():
    w = LibraryWriter("/library", FakeClient())
    golden = open(
        os.path.join(os.path.dirname(__file__), "..", "golden", "movie.nfo")
    ).read()
    assert w.render_nfo(make_movie()) == golden


@respx.mock
def test_write_movie(tmp_path):
    respx.get("https://image.tmdb.org/t/p/w500/p.jpg").mock(
        return_value=httpx.Response(200, content=b"POSTERBYTES")
    )
    respx.get("https://image.tmdb.org/t/p/w1280/b.jpg").mock(
        return_value=httpx.Response(200, content=b"BACKBYTES")
    )
    src = tmp_path / "raw.mkv"
    src.write_bytes(b"VIDEO")
    w = LibraryWriter(str(tmp_path / "lib"), FakeClient())
    written = w.write_movie(make_movie(), str(src))
    assert isinstance(written, WrittenMovie)
    folder_base = "Dune Part Three (2026) [tmdbid-1234567]"
    assert os.path.basename(written.folder) == folder_base
    assert os.path.basename(written.video_path) == folder_base + ".mkv"
    assert not src.exists()  # moved, not copied
    assert open(written.nfo_path).read().startswith("<?xml")
    assert open(written.poster_path, "rb").read() == b"POSTERBYTES"
    assert open(written.backdrop_path, "rb").read() == b"BACKBYTES"


@respx.mock
def test_write_movie_no_backdrop(tmp_path):
    respx.get("https://image.tmdb.org/t/p/w500/p.jpg").mock(
        return_value=httpx.Response(200, content=b"P")
    )
    src = tmp_path / "raw.mkv"
    src.write_bytes(b"V")
    w = LibraryWriter(str(tmp_path / "lib"), FakeClient())
    written = w.write_movie(make_movie(backdrop_path=None), str(src))
    assert written.backdrop_path is None


def test_delete_movie(tmp_path):
    folder = tmp_path / "lib" / "x"
    folder.mkdir(parents=True)
    (folder / "a.txt").write_text("hi")
    w = LibraryWriter(str(tmp_path / "lib"), FakeClient())
    w.delete_movie(str(folder))
    assert not folder.exists()
    w.delete_movie(str(folder))  # idempotent, no raise
