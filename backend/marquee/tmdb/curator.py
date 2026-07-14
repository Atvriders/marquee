from __future__ import annotations

from datetime import datetime, timezone

from ..models import EnrichedMovie, MovieCandidate, TrailerVideo

_TYPE_RANK = {"Trailer": 0, "Teaser": 1}


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _published_ts(value: str) -> float:
    dt = _parse_date(value)
    return dt.timestamp() if dt else 0.0


def _year_from(date_str: str | None) -> int | None:
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, TypeError):
        return None


_ALLOWED_SITES = ("YouTube", "Vimeo")


def rank_trailers(videos: list[dict], language: str) -> list[TrailerVideo]:
    """Rank every playable (YouTube or Vimeo) video candidate, best first.

    Returns the FULL ranked list — not just the winner — so callers can fall
    back to the next candidate when the top pick turns out to be dead/DRM'd
    at download time (spec: trailer candidate fallback).
    """
    lang2 = language.split("-")[0].lower()
    playable = [v for v in videos if v.get("site") in _ALLOWED_SITES and v.get("key")]
    if not playable:
        return []

    def sort_key(v: dict) -> tuple:
        return (
            _TYPE_RANK.get(v.get("type", ""), 2),
            0 if v.get("official") else 1,
            0 if v.get("iso_639_1", "").lower() == lang2 else 1,
            -int(v.get("size", 0)),
            -_published_ts(v.get("published_at", "")),
        )

    ranked = sorted(playable, key=sort_key)
    return [
        TrailerVideo(
            key=v["key"],
            site=v.get("site", "YouTube"),
            type=v.get("type", ""),
            official=bool(v.get("official", False)),
            size=int(v.get("size", 0)),
            iso_639_1=v.get("iso_639_1", ""),
            published_at=v.get("published_at", ""),
        )
        for v in ranked
    ]


def pick_best_trailer(videos: list[dict], language: str) -> TrailerVideo | None:
    ranked = rank_trailers(videos, language)
    return ranked[0] if ranked else None


def extract_digital_date(
    release_dates_results: list[dict], region: str
) -> tuple[datetime | None, str]:
    by_country: dict[str, list[dict]] = {
        r.get("iso_3166_1"): r.get("release_dates", []) for r in release_dates_results
    }

    def earliest_of_type(entries: list[dict], type_code: int) -> datetime | None:
        dates = [
            _parse_date(e.get("release_date"))
            for e in entries
            if e.get("type") == type_code
        ]
        dates = [d for d in dates if d is not None]
        return min(dates) if dates else None

    region_hit = earliest_of_type(by_country.get(region, []), 4)
    if region_hit:
        return region_hit, "region"

    if region != "US":
        us_hit = earliest_of_type(by_country.get("US", []), 4)
        if us_hit:
            return us_hit, "us"

    all_entries = [e for entries in by_country.values() for e in entries]

    global_hit = earliest_of_type(all_entries, 4)
    if global_hit:
        return global_hit, "global"

    physical_hit = earliest_of_type(all_entries, 5)
    if physical_hit:
        return physical_hit, "physical"

    tv_hit = earliest_of_type(all_entries, 6)
    if tv_hit:
        return tv_hit, "tv"

    return None, "none"


def _certification(release_dates_results: list[dict], region: str) -> str | None:
    for r in release_dates_results:
        if r.get("iso_3166_1") == region:
            for e in r.get("release_dates", []):
                cert = e.get("certification")
                if cert:
                    return cert
    return None


def discover(
    client,
    sources: list[str],
    region: str,
    language: str,
    count: int,
    pages: int = 3,
) -> list[MovieCandidate]:
    seen: dict[int, MovieCandidate] = {}
    for source in sources:
        for raw in client.list_movies(source, region, language, pages):
            tmdb_id = raw.get("id")
            if tmdb_id is None or tmdb_id in seen:
                continue
            seen[tmdb_id] = MovieCandidate(
                tmdb_id=tmdb_id,
                title=raw.get("title") or raw.get("name") or "",
                year=_year_from(raw.get("release_date")),
                overview=raw.get("overview", ""),
                popularity=float(raw.get("popularity", 0.0)),
                poster_path=raw.get("poster_path"),
                backdrop_path=raw.get("backdrop_path"),
                source=source,
                release_date=raw.get("release_date"),
            )
    ranked = sorted(seen.values(), key=lambda c: c.popularity, reverse=True)
    return ranked[:count]


def enrich(client, cand: MovieCandidate, region: str, language: str) -> EnrichedMovie:
    details = client.movie_details(cand.tmdb_id, language)
    videos = details.get("videos", {}).get("results", [])
    candidates = rank_trailers(videos, language)
    trailer = candidates[0] if candidates else None
    release_dates = details.get("release_dates", {}).get("results", [])
    digital_date, digital_date_source = extract_digital_date(release_dates, region)
    genres = [g["name"] for g in details.get("genres", []) if g.get("name")]
    studios = [s["name"] for s in details.get("production_companies", []) if s.get("name")]
    return EnrichedMovie(
        tmdb_id=cand.tmdb_id,
        title=details.get("title") or cand.title,
        year=cand.year or _year_from(details.get("release_date")),
        overview=details.get("overview") or cand.overview,
        popularity=float(details.get("popularity", cand.popularity)),
        source=cand.source,
        poster_path=details.get("poster_path") or cand.poster_path,
        backdrop_path=details.get("backdrop_path") or cand.backdrop_path,
        runtime=details.get("runtime"),
        genres=genres,
        studios=studios,
        certification=_certification(release_dates, region),
        premiere_date=details.get("release_date") or cand.release_date,
        digital_date=digital_date,
        digital_date_source=digital_date_source,
        youtube_key=trailer.key if trailer else None,
        trailer=trailer,
        trailer_candidates=candidates,
    )
