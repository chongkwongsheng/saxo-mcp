# tests/test_resolve.py
from saxo_mcp.orders import UicCache, resolve_stock_uic


SEARCH = "/ref/v1/instruments"


def test_resolves_exact_symbol_match(fake_client):
    fake_client.queue("GET", SEARCH, {"Data": [
        {"Symbol": "GMED:xnys", "Identifier": 111, "AssetType": "Stock"},
        {"Symbol": "GME:xnys", "Identifier": 222, "AssetType": "Stock"},
    ]})
    assert resolve_stock_uic("GME", client=fake_client) == 222
    # exact-match guard: prefix lookalike GMED must not win
    method, path, params = fake_client.calls[0]
    assert params == {"Keywords": "GME", "AssetTypes": "Stock"}


def test_strips_exchange_and_yahoo_suffixes(fake_client):
    fake_client.queue("GET", SEARCH, {"Data": [
        {"Symbol": "ES3:xses", "Identifier": 333, "AssetType": "Stock"},
    ]})
    assert resolve_stock_uic("es3.SI", client=fake_client) == 333
    assert fake_client.calls[0][2]["Keywords"] == "ES3"


def test_no_match_returns_none(fake_client):
    fake_client.queue("GET", SEARCH, {"Data": []})
    assert resolve_stock_uic("ZZZQ", client=fake_client) is None


def test_cache_hit_skips_network(fake_client):
    cache = UicCache()
    cache.put("GME", 222)
    assert resolve_stock_uic("GME", client=fake_client, cache=cache) == 222
    assert fake_client.calls == []   # no API call made


def test_api_error_returns_none(fake_client):
    fake_client.queue("GET", SEARCH, (500, {"Message": "boom"}))
    assert resolve_stock_uic("GME", client=fake_client) is None
