# tests/test_client_raw.py
"""request_raw contract test against a stub transport (no network)."""
import httpx

from saxo_mcp.client import SaxoClient


def _make_client(handler) -> SaxoClient:
    c = SaxoClient.__new__(SaxoClient)  # skip __init__ (avoids auth.api_base())
    c._client = httpx.Client(
        base_url="https://unit.test", transport=httpx.MockTransport(handler)
    )
    c._headers = lambda: {}  # type: ignore[method-assign]  # no token in unit tests
    return c


def test_request_raw_returns_status_and_body_on_4xx():
    def handler(request):
        return httpx.Response(409, json={"Message": "dup"})

    client = _make_client(handler)
    status, body = client.request_raw("POST", "/trade/v2/orders", json={})
    assert status == 409
    assert body == {"Message": "dup"}


def test_request_raw_empty_body_gives_empty_dict():
    def handler(request):
        return httpx.Response(204)

    client = _make_client(handler)
    status, body = client.request_raw("DELETE", "/trade/v2/orders/1")
    assert status == 204
    assert body == {}
