from __future__ import annotations

import time

import httpx

_SOURCE_ENDPOINTS = {
    "upcoming": "/movie/upcoming",
    "now_playing": "/movie/now_playing",
    "popular": "/movie/popular",
    "trending_day": "/trending/movie/day",
    "trending_week": "/trending/movie/week",
}

_MAX_RETRIES = 5


class TMDBClient:
    def __init__(
        self,
        token: str,
        session: httpx.Client | None = None,
        base_url: str = "https://api.themoviedb.org/3",
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self._session = session or httpx.Client(timeout=30.0)
        self._image_base: str | None = None

    def close(self) -> None:
        self._session.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "accept": "application/json"}

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        response: httpx.Response | None = None
        for _ in range(_MAX_RETRIES):
            response = self._session.get(url, headers=self._headers(), params=params)
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "1"))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            return response.json()
        assert response is not None
        response.raise_for_status()
        return response.json()

    def list_movies(
        self, source: str, region: str, language: str, pages: int = 3
    ) -> list[dict]:
        endpoint = _SOURCE_ENDPOINTS[source]
        results: list[dict] = []
        for page in range(1, pages + 1):
            data = self._get(
                endpoint,
                params={"language": language, "region": region, "page": page},
            )
            results.extend(data.get("results", []))
            if page >= data.get("total_pages", 1):
                break
        return results

    def movie_details(
        self,
        tmdb_id: int,
        language: str,
        append: tuple[str, ...] = ("videos", "release_dates", "images"),
    ) -> dict:
        return self._get(
            f"/movie/{tmdb_id}",
            params={"language": language, "append_to_response": ",".join(append)},
        )

    def image_base_url(self) -> str:
        if self._image_base is None:
            data = self._get("/configuration")
            self._image_base = data["images"]["secure_base_url"]
        return self._image_base

    def build_image_url(self, path: str, size: str) -> str:
        return f"{self.image_base_url()}{size}{path}"
