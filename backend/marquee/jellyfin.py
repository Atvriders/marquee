# backend/marquee/jellyfin.py
from __future__ import annotations

import httpx

_CLIENT_INFO = 'Client="Marquee", Device="Marquee", DeviceId="marquee-01", Version="1.0.0"'

# Used only for the pre-auth AuthenticateByName call, where there is no token yet.
_LOGIN_AUTH_HEADER = f"MediaBrowser {_CLIENT_INFO}"


def _auth_header(token: str) -> str:
    """Canonical Jellyfin Authorization header. Works with an api key or a
    user access token, on 10.10/10.11/12 (X-Emby-Token is legacy-gated on 10.11)."""
    return f'MediaBrowser Token="{token}", {_CLIENT_INFO}'


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
        self._admin_user_id: str | None = None

    def close(self) -> None:
        self._session.close()

    def _key_headers(self) -> dict:
        return {"Authorization": _auth_header(self.api_key)}

    def _token_headers(self, token: str) -> dict:
        return {"Authorization": _auth_header(token)}

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
            headers={
                "Authorization": _LOGIN_AUTH_HEADER,
                "X-Emby-Authorization": _LOGIN_AUTH_HEADER,
            },
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
            f"{self.url}/Items/{item_id}", headers=self._token_headers(token)
        )
        resp.raise_for_status()

    def system_info(self) -> dict:
        resp = self._session.get(
            f"{self.url}/System/Info", headers=self._key_headers()
        )
        resp.raise_for_status()
        return resp.json()

    def virtual_folders(self) -> list[dict]:
        resp = self._session.get(
            f"{self.url}/Library/VirtualFolders", headers=self._key_headers()
        )
        resp.raise_for_status()
        return resp.json()

    def server_configuration(self) -> dict:
        resp = self._session.get(
            f"{self.url}/System/Configuration", headers=self._key_headers()
        )
        resp.raise_for_status()
        return resp.json()

    def plugins(self) -> list[dict]:
        resp = self._session.get(
            f"{self.url}/Plugins", headers=self._key_headers()
        )
        resp.raise_for_status()
        return resp.json()

    def plugin_configuration(self, plugin_id: str) -> dict | None:
        resp = self._session.get(
            f"{self.url}/Plugins/{plugin_id}/Configuration",
            headers=self._key_headers(),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    def admin_user_id(self) -> str | None:
        if self._admin_user_id is not None:
            return self._admin_user_id
        resp = self._session.get(
            f"{self.url}/Users", headers=self._key_headers()
        )
        resp.raise_for_status()
        for user in resp.json():
            if user.get("Policy", {}).get("IsAdministrator"):
                self._admin_user_id = user["Id"]
                return self._admin_user_id
        return None

    def library_items(
        self, library_item_id: str, user_id: str | None = None
    ) -> list[dict]:
        params = {
            "parentId": library_item_id,
            "recursive": "true",
            "includeItemTypes": "Movie",
            "fields": "ProviderIds,UserData",
        }
        if user_id:
            params["userId"] = user_id
        resp = self._session.get(
            f"{self.url}/Items", params=params, headers=self._key_headers()
        )
        resp.raise_for_status()
        return resp.json().get("Items", [])

    def intros(self, item_id: str, user_id: str) -> list[dict]:
        resp = self._session.get(
            f"{self.url}/Items/{item_id}/Intros",
            params={"userId": user_id},
            headers=self._key_headers(),
        )
        resp.raise_for_status()
        return resp.json().get("Items", [])
