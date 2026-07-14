# tests/test_jellyfin.py
import httpx
import pytest
import respx

from marquee.jellyfin import JellyfinClient

URL = "http://jelly:8096"

CANONICAL_KEY_AUTH = (
    'MediaBrowser Token="APIKEY", Client="Marquee", Device="Marquee", '
    'DeviceId="marquee-01", Version="1.0.0"'
)
CANONICAL_ADMIN_AUTH = (
    'MediaBrowser Token="ADMIN123", Client="Marquee", Device="Marquee", '
    'DeviceId="marquee-01", Version="1.0.0"'
)


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
    assert route.calls.last.request.headers["Authorization"] == CANONICAL_KEY_AUTH


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
    assert route.calls.last.request.headers["Authorization"] == CANONICAL_KEY_AUTH


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
    assert route.calls.last.request.headers["Authorization"] == CANONICAL_ADMIN_AUTH


def test_authenticate_requires_creds():
    with pytest.raises(RuntimeError):
        make_client(username=None, password=None).authenticate()


def test_close_closes_underlying_session():
    client = make_client()
    assert client._session.is_closed is False
    client.close()
    assert client._session.is_closed is True


@respx.mock
def test_system_info():
    route = respx.get(f"{URL}/System/Info").mock(
        return_value=httpx.Response(200, json={"Version": "10.11.0"})
    )
    assert make_client().system_info() == {"Version": "10.11.0"}
    assert route.calls.last.request.headers["Authorization"] == CANONICAL_KEY_AUTH


@respx.mock
def test_virtual_folders():
    payload = [{"Name": "Movies", "ItemId": "LIB1", "CollectionType": "movies"}]
    route = respx.get(f"{URL}/Library/VirtualFolders").mock(
        return_value=httpx.Response(200, json=payload)
    )
    assert make_client().virtual_folders() == payload
    assert route.calls.last.request.headers["Authorization"] == CANONICAL_KEY_AUTH


@respx.mock
def test_server_configuration():
    payload = {"MetadataOptions": [{"ItemType": "Movie"}]}
    route = respx.get(f"{URL}/System/Configuration").mock(
        return_value=httpx.Response(200, json=payload)
    )
    assert make_client().server_configuration() == payload
    assert route.calls.last.request.headers["Authorization"] == CANONICAL_KEY_AUTH


@respx.mock
def test_plugins():
    payload = [{"Name": "Cinema Mode", "Id": "5fcefe1b-df1f-4596-ac57-f2f939c294c5"}]
    route = respx.get(f"{URL}/Plugins").mock(
        return_value=httpx.Response(200, json=payload)
    )
    assert make_client().plugins() == payload
    assert route.calls.last.request.headers["Authorization"] == CANONICAL_KEY_AUTH


@respx.mock
def test_plugin_configuration_found():
    plugin_id = "5fcefe1b-df1f-4596-ac57-f2f939c294c5"
    payload = {"NumberOfTrailers": 2, "TrailerPreRollsLibrary": "-"}
    route = respx.get(f"{URL}/Plugins/{plugin_id}/Configuration").mock(
        return_value=httpx.Response(200, json=payload)
    )
    assert make_client().plugin_configuration(plugin_id) == payload
    assert route.calls.last.request.headers["Authorization"] == CANONICAL_KEY_AUTH


@respx.mock
def test_plugin_configuration_404_returns_none():
    plugin_id = "not-installed"
    respx.get(f"{URL}/Plugins/{plugin_id}/Configuration").mock(
        return_value=httpx.Response(404)
    )
    assert make_client().plugin_configuration(plugin_id) is None


@respx.mock
def test_admin_user_id_picks_administrator_and_caches():
    payload = [
        {"Id": "USER-REGULAR", "Policy": {"IsAdministrator": False}},
        {"Id": "USER-ADMIN", "Policy": {"IsAdministrator": True}},
    ]
    route = respx.get(f"{URL}/Users").mock(
        return_value=httpx.Response(200, json=payload)
    )
    c = make_client()
    assert c.admin_user_id() == "USER-ADMIN"
    assert c.admin_user_id() == "USER-ADMIN"
    assert route.call_count == 1  # cached
    assert route.calls.last.request.headers["Authorization"] == CANONICAL_KEY_AUTH


@respx.mock
def test_admin_user_id_none_when_no_administrator():
    payload = [{"Id": "USER-REGULAR", "Policy": {"IsAdministrator": False}}]
    respx.get(f"{URL}/Users").mock(return_value=httpx.Response(200, json=payload))
    assert make_client().admin_user_id() is None


@respx.mock
def test_library_items_without_user_id():
    route = respx.get(f"{URL}/Items").mock(
        return_value=httpx.Response(200, json={"Items": [{"Id": "M1"}]})
    )
    result = make_client().library_items("LIB1")
    assert result == [{"Id": "M1"}]
    request = route.calls.last.request
    assert request.headers["Authorization"] == CANONICAL_KEY_AUTH
    params = httpx.QueryParams(request.url.query.decode())
    assert params["parentId"] == "LIB1"
    assert params["recursive"] == "true"
    assert params["includeItemTypes"] == "Movie"
    assert params["fields"] == "ProviderIds,UserData"
    assert "userId" not in params


@respx.mock
def test_library_items_with_user_id_includes_user_data():
    route = respx.get(f"{URL}/Items").mock(
        return_value=httpx.Response(
            200,
            json={"Items": [{"Id": "M1", "UserData": {"PlayCount": 3}}]},
        )
    )
    result = make_client().library_items("LIB1", user_id="USER-ADMIN")
    assert result == [{"Id": "M1", "UserData": {"PlayCount": 3}}]
    params = httpx.QueryParams(route.calls.last.request.url.query.decode())
    assert params["userId"] == "USER-ADMIN"


@respx.mock
def test_intros_returns_items():
    route = respx.get(f"{URL}/Items/ITEM1/Intros").mock(
        return_value=httpx.Response(200, json={"Items": [{"Id": "TRAILER1"}]})
    )
    result = make_client().intros("ITEM1", "USER-ADMIN")
    assert result == [{"Id": "TRAILER1"}]
    request = route.calls.last.request
    assert request.headers["Authorization"] == CANONICAL_KEY_AUTH
    params = httpx.QueryParams(request.url.query.decode())
    assert params["userId"] == "USER-ADMIN"


@respx.mock
def test_intros_empty_when_nothing_would_play():
    respx.get(f"{URL}/Items/ITEM1/Intros").mock(
        return_value=httpx.Response(200, json={"Items": []})
    )
    assert make_client().intros("ITEM1", "USER-ADMIN") == []
