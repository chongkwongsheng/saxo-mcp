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


def test_request_raw_returns_401_when_refresh_raises(monkeypatch):
    # H4: request_raw must NEVER raise. On a 401 it attempts a token refresh;
    # if that refresh RAISES (expired/failed refresh chain), request_raw must
    # honour its contract and RETURN the original (401, body), not propagate.
    from saxo_mcp import auth

    def handler(request):
        return httpx.Response(401, json={"Message": "unauthorized"})

    monkeypatch.setattr(auth, "_load_tokens", lambda: {"refresh_token": "x"})

    def boom(_tokens):
        raise RuntimeError("Refresh failed (400): expired. Run saxo-mcp login.")

    monkeypatch.setattr(auth, "_refresh", boom)

    client = _make_client(handler)
    status, body = client.request_raw("POST", "/trade/v2/orders", json={})
    assert status == 401
    assert body == {"Message": "unauthorized"}


def test_request_raw_returns_401_when_retry_still_401(monkeypatch):
    # H4: if refresh SUCCEEDS but the retried request is still 401, return
    # (401, body) — callers map 4xx -> REJECTED, which is acceptable.
    from saxo_mcp import auth

    def handler(request):
        return httpx.Response(401, json={"Message": "still no"})

    monkeypatch.setattr(auth, "_load_tokens", lambda: {"refresh_token": "x"})
    monkeypatch.setattr(auth, "_refresh", lambda _t: {"access_token": "new"})

    client = _make_client(handler)
    status, body = client.request_raw("POST", "/trade/v2/orders", json={})
    assert status == 401
    assert body == {"Message": "still no"}
