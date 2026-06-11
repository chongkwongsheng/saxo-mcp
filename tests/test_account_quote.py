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
