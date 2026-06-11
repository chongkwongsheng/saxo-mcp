# tests/test_account_quote.py
"""get_account_id + get_quote (squeeze-aimbot safety-hardening spec §2)."""
from saxo_mcp import orders


# ---- get_account_id ----

def test_get_account_id_returns_first_account_id(fake_client):
    fake_client.queue("GET", "/port/v1/accounts/me",
                      {"Data": [{"AccountKey": "k-guid-1",
                                 "AccountId": "16934518"}]})
    assert orders.get_account_id(client=fake_client) == "16934518"


def test_get_account_id_none_on_error_status(fake_client):
    fake_client.queue("GET", "/port/v1/accounts/me", (500, {"Message": "down"}))
    assert orders.get_account_id(client=fake_client) is None


def test_get_account_id_none_on_empty_accounts(fake_client):
    fake_client.queue("GET", "/port/v1/accounts/me", {"Data": []})
    assert orders.get_account_id(client=fake_client) is None


def test_get_account_id_zero_is_returned_not_dropped(fake_client):
    # falsy-but-present AccountId must not be swallowed by a truthiness check
    fake_client.queue("GET", "/port/v1/accounts/me",
                      {"Data": [{"AccountId": 0}]})
    assert orders.get_account_id(client=fake_client) == "0"


def test_get_account_id_none_when_key_absent(fake_client):
    fake_client.queue("GET", "/port/v1/accounts/me",
                      {"Data": [{"AccountKey": "k-guid-1"}]})  # no AccountId
    assert orders.get_account_id(client=fake_client) is None


# ---- get_quote ----

def test_get_quote_parses_bid_ask_mid(fake_client):
    fake_client.queue("GET", "/trade/v1/infoprices",
                      {"Quote": {"Bid": 24.10, "Ask": 24.15, "Mid": 24.125,
                                 "DelayedByMinutes": 0}})
    q = orders.get_quote(123, client=fake_client)
    assert q.bid == 24.10 and q.ask == 24.15 and q.mid == 24.125
    assert q.delayed is False
    # the request asked for the right instrument
    assert fake_client.calls[-1] == (
        "GET", "/trade/v1/infoprices", {"Uic": 123, "AssetType": "Stock"})


def test_get_quote_one_sided_keeps_other_side_none(fake_client):
    fake_client.queue("GET", "/trade/v1/infoprices",
                      {"Quote": {"Ask": 24.15, "DelayedByMinutes": 0}})
    q = orders.get_quote(123, client=fake_client)
    assert q is not None and q.bid is None and q.ask == 24.15


def test_get_quote_flags_delayed(fake_client):
    fake_client.queue("GET", "/trade/v1/infoprices",
                      {"Quote": {"Bid": 1.0, "Ask": 1.1,
                                 "DelayedByMinutes": 15}})
    assert orders.get_quote(9, client=fake_client).delayed is True


def test_get_quote_none_on_transport_error(fake_client):
    fake_client.queue("GET", "/trade/v1/infoprices", (502, {"Message": "gw"}))
    assert orders.get_quote(123, client=fake_client) is None


def test_get_quote_none_on_missing_quote_key(fake_client):
    fake_client.queue("GET", "/trade/v1/infoprices", {"NoQuote": True})
    assert orders.get_quote(123, client=fake_client) is None
