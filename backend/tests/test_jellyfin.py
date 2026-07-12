# tests/test_jellyfin.py
import httpx
import pytest
import respx

from marquee.jellyfin import JellyfinClient

URL = "http://jelly:8096"


def make_client(**over):
    base = dict(url=URL + "/", api_key="APIKEY", username="admin", password="pw")
    base.update(over)
    return JellyfinClient(**base)


@respx.mock
def test_test_ok_and_key_header():
    route = respx.get(f"{URL}/System/Info").mock(
        return_value=httpx.Response(200, json={"Version": "10.11"})
    )
    assert make_client().test() is True
    assert route.calls.last.request.headers["X-Emby-Token"] == "APIKEY"


@respx.mock
def test_test_false_on_error():
    respx.get(f"{URL}/System/Info").mock(return_value=httpx.Response(401))
    assert make_client().test() is False


@respx.mock
def test_refresh_uses_api_key():
    route = respx.post(f"{URL}/Library/Refresh").mock(
        return_value=httpx.Response(204)
    )
    make_client().refresh_library()
    assert route.calls.last.request.headers["X-Emby-Token"] == "APIKEY"


@respx.mock
def test_authenticate_caches_admin_token():
    route = respx.post(f"{URL}/Users/AuthenticateByName").mock(
        return_value=httpx.Response(200, json={"AccessToken": "ADMIN123"})
    )
    c = make_client()
    assert c.authenticate() == "ADMIN123"
    assert c.authenticate() == "ADMIN123"
    assert route.call_count == 1  # cached


@respx.mock
def test_find_item_by_tmdb():
    respx.get(f"{URL}/Items").mock(
        return_value=httpx.Response(200, json={"Items": [{"Id": "ITEM42"}]})
    )
    assert make_client().find_item_by_tmdb(1234567) == "ITEM42"


@respx.mock
def test_find_item_none():
    respx.get(f"{URL}/Items").mock(
        return_value=httpx.Response(200, json={"Items": []})
    )
    assert make_client().find_item_by_tmdb(1) is None


@respx.mock
def test_delete_uses_admin_token():
    respx.post(f"{URL}/Users/AuthenticateByName").mock(
        return_value=httpx.Response(200, json={"AccessToken": "ADMIN123"})
    )
    route = respx.delete(f"{URL}/Items/ITEM42").mock(
        return_value=httpx.Response(204)
    )
    make_client().delete_item("ITEM42")
    assert route.calls.last.request.headers["X-Emby-Token"] == "ADMIN123"


def test_authenticate_requires_creds():
    with pytest.raises(RuntimeError):
        make_client(username=None, password=None).authenticate()


def test_close_closes_underlying_session():
    client = make_client()
    assert client._session.is_closed is False
    client.close()
    assert client._session.is_closed is True
