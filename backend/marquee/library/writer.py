from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from xml.sax.saxutils import escape

import httpx

from marquee.models import EnrichedMovie

_ILLEGAL = '<>:"/\\|?*'


@dataclass
class WrittenMovie:
    folder: str
    video_path: str
    nfo_path: str
    poster_path: str | None
    backdrop_path: str | None
    trailer_extra_path: str | None = None


class LibraryWriter:
    def __init__(self, library_dir: str, client, trailer_extra: bool = True):
        self.library_dir = library_dir
        self.client = client
        self.trailer_extra = trailer_extra

    @staticmethod
    def sanitize(name: str) -> str:
        cleaned = "".join(" " if c in _ILLEGAL else c for c in name)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned.rstrip(". ")

    def folder_name(self, title: str, year: int | None, tmdb_id: int) -> str:
        safe = self.sanitize(title)
        if year:
            return f"{safe} ({year}) [tmdbid-{tmdb_id}]"
        return f"{safe} [tmdbid-{tmdb_id}]"

    @staticmethod
    def _plot(m: EnrichedMovie) -> str:
        parts = ["COMING SOON."]
        if m.overview:
            parts.append(m.overview)
        if m.premiere_date:
            parts.append(f"In theaters {m.premiere_date}.")
        return " ".join(parts)

    def render_nfo(self, m: EnrichedMovie) -> str:
        lines = [
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
            "<movie>",
            f"  <title>{escape(m.title)}</title>",
            f"  <originaltitle>{escape(m.title)}</originaltitle>",
            f"  <sorttitle>{escape(m.title)}</sorttitle>",
            f"  <plot>{escape(self._plot(m))}</plot>",
        ]
        if m.runtime is not None:
            lines.append(f"  <runtime>{m.runtime}</runtime>")
        if m.year is not None:
            lines.append(f"  <year>{m.year}</year>")
        if m.premiere_date:
            lines.append(f"  <premiered>{escape(m.premiere_date)}</premiered>")
            lines.append(f"  <releasedate>{escape(m.premiere_date)}</releasedate>")
        if m.certification:
            lines.append(f"  <mpaa>{escape(m.certification)}</mpaa>")
        for g in m.genres:
            lines.append(f"  <genre>{escape(g)}</genre>")
        for s in m.studios:
            lines.append(f"  <studio>{escape(s)}</studio>")
        lines.append("  <tag>Coming Soon</tag>")
        lines.append("  <tag>Trailer</tag>")
        lines.append(
            f'  <uniqueid type="tmdb" default="true">{m.tmdb_id}</uniqueid>'
        )
        lines.append(f"  <tmdbid>{m.tmdb_id}</tmdbid>")
        if m.poster_path:
            lines.append('  <thumb aspect="poster">poster.jpg</thumb>')
        if m.backdrop_path:
            lines.append("  <fanart>")
            lines.append("    <thumb>backdrop.jpg</thumb>")
            lines.append("  </fanart>")
        lines.append("</movie>")
        return "\n".join(lines) + "\n"

    def _fetch(self, url: str) -> bytes:
        resp = httpx.get(url, timeout=30.0)
        resp.raise_for_status()
        return resp.content

    def write_movie(self, m: EnrichedMovie, source_video: str) -> WrittenMovie:
        name = self.folder_name(m.title, m.year, m.tmdb_id)
        folder = os.path.join(self.library_dir, name)
        os.makedirs(folder, exist_ok=True)

        ext = os.path.splitext(source_video)[1].lstrip(".") or "mkv"
        video_path = os.path.join(folder, f"{name}.{ext}")
        shutil.move(source_video, video_path)

        trailer_extra_path = None
        if self.trailer_extra:
            trailers_dir = os.path.join(folder, "trailers")
            os.makedirs(trailers_dir, exist_ok=True)
            trailer_extra_path = os.path.join(trailers_dir, f"{name}-trailer.{ext}")
            try:
                os.link(video_path, trailer_extra_path)
            except OSError:
                shutil.copy2(video_path, trailer_extra_path)

        nfo_path = os.path.join(folder, "movie.nfo")
        with open(nfo_path, "w", encoding="utf-8") as fh:
            fh.write(self.render_nfo(m))

        poster_path = None
        if m.poster_path:
            poster_path = os.path.join(folder, "poster.jpg")
            with open(poster_path, "wb") as fh:
                fh.write(self._fetch(self.client.build_image_url(m.poster_path, "w500")))

        backdrop_path = None
        if m.backdrop_path:
            backdrop_path = os.path.join(folder, "backdrop.jpg")
            with open(backdrop_path, "wb") as fh:
                fh.write(
                    self._fetch(self.client.build_image_url(m.backdrop_path, "w1280"))
                )

        return WrittenMovie(
            folder=folder,
            video_path=video_path,
            nfo_path=nfo_path,
            poster_path=poster_path,
            backdrop_path=backdrop_path,
            trailer_extra_path=trailer_extra_path,
        )

    def delete_movie(self, folder: str) -> None:
        if os.path.isdir(folder):
            shutil.rmtree(folder)
