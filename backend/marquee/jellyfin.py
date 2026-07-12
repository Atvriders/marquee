# backend/marquee/jellyfin.py
from __future__ import annotations

import httpx

_AUTH_HEADER = (
    'MediaBrowser Client="Marquee", Device="Marquee", '
    'DeviceId="marquee", Version="1.0"'
)


class JellyfinClient:
    def __init__(
        self,
        url: str,
        api_key: str,
        username: str | None = None,
        password: str | None = None,
        session: httpx.Client | None = None,
    ):
        self.url = url.rstrip("/")
        self.api_key = api_key
        self.username = username
        self.password = password
        self._session = session or httpx.Client(timeout=30.0)
        self._admin_token: str | None = None

    def close(self) -> None:
        self._session.close()

    def _key_headers(self) -> dict:
        return {"X-Emby-Token": self.api_key}

    def test(self) -> bool:
        try:
            resp = self._session.get(
                f"{self.url}/System/Info", headers=self._key_headers()
            )
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    def refresh_library(self) -> None:
        resp = self._session.post(
            f"{self.url}/Library/Refresh", headers=self._key_headers()
        )
        resp.raise_for_status()

    def authenticate(self) -> str:
        if self._admin_token:
            return self._admin_token
        if not (self.username and self.password):
            raise RuntimeError("Jellyfin admin credentials not configured")
        resp = self._session.post(
            f"{self.url}/Users/AuthenticateByName",
            json={"Username": self.username, "Pw": self.password},
            headers={"Authorization": _AUTH_HEADER, "X-Emby-Authorization": _AUTH_HEADER},
        )
        resp.raise_for_status()
        self._admin_token = resp.json()["AccessToken"]
        return self._admin_token

    def find_item_by_tmdb(self, tmdb_id: int) -> str | None:
        resp = self._session.get(
            f"{self.url}/Items",
            params={
                "recursive": "true",
                "anyProviderIdEquals": f"tmdb.{tmdb_id}",
                "fields": "ProviderIds",
            },
            headers=self._key_headers(),
        )
        resp.raise_for_status()
        items = resp.json().get("Items", [])
        return items[0]["Id"] if items else None

    def delete_item(self, item_id: str) -> None:
        token = self.authenticate()
        resp = self._session.delete(
            f"{self.url}/Items/{item_id}", headers={"X-Emby-Token": token}
        )
        resp.raise_for_status()
