# tests/test_place.py
import pytest

from saxo_mcp.orders import get_account_key, place_market, precheck_ok


ACCTS = "/port/v1/accounts/me"
ORDERS = "/trade/v2/orders"
PRECHECK = "/trade/v2/orders/precheck"


@pytest.fixture(autouse=True)
def _enable_writes(monkeypatch):
    # place_market self-gates on SAXO_WRITES_ENABLED (FIX 2); these tests
    # exercise placement, so enable the SIM write gate. Individual tests that
    # assert the gate itself delenv() it to override this.
    monkeypatch.setenv("SAXO_ENV", "sim")
    monkeypatch.setenv("SAXO_WRITES_ENABLED", "1")


def test_get_account_key(fake_client):
    fake_client.queue("GET", ACCTS, {"Data": [{"AccountKey": "AbC123=="}]})
    assert get_account_key(client=fake_client) == "AbC123=="


def test_get_account_key_no_accounts(fake_client):
    fake_client.queue("GET", ACCTS, {"Data": []})
    assert get_account_key(client=fake_client) is None


def test_precheck_ok_true_on_ok(fake_client):
    fake_client.queue("POST", PRECHECK, {"PreCheckResult": "Ok",
                                         "EstimatedCashRequired": 1983.0})
    ok, detail = precheck_ok("AbC==", 222, "Buy", 82, client=fake_client)
    assert ok is True
    body = fake_client.calls[0][2]
    assert body["Uic"] == 222 and body["AssetType"] == "Stock"
    assert body["BuySell"] == "Buy" and body["Amount"] == 82
    assert body["ManualOrder"] is False
    assert "ToOpenClose" not in body          # stocks must NOT carry it


def test_precheck_ok_false_on_error(fake_client):
    fake_client.queue("POST", PRECHECK, {"PreCheckResult": "Error",
                                         "ErrorInfo": {"Message": "nope"}})
    ok, detail = precheck_ok("AbC==", 222, "Buy", 82, client=fake_client)
    assert ok is False and "nope" in detail


def test_place_market_placed(fake_client):
    fake_client.queue("POST", ORDERS, {"OrderId": "5038999"})
    res = place_market("AbC==", 222, "Buy", 82, client=fake_client)
    assert res.status == "PLACED" and res.order_id == "5038999"


def test_place_market_rejected_4xx(fake_client):
    fake_client.queue("POST", ORDERS, (400, {"Message": "bad params"}))
    res = place_market("AbC==", 222, "Buy", 82, client=fake_client)
    assert res.status == "REJECTED" and "bad params" in res.detail


def test_place_market_ambiguous_5xx(fake_client):
    fake_client.queue("POST", ORDERS, (502, {"Message": "gateway"}))
    res = place_market("AbC==", 222, "Buy", 82, client=fake_client)
    assert res.status == "ERROR"   # may or may not be on book — caller reconciles


def test_precheck_missing_field_fails_closed(fake_client):
    fake_client.queue("POST", PRECHECK, {})          # 200 but no PreCheckResult
    ok, detail = precheck_ok("AbC==", 222, "Buy", 82, client=fake_client)
    assert ok is False and "no PreCheckResult" in detail


def test_place_market_self_gates_when_writes_disabled(monkeypatch, fake_client):
    # H-2: defense-in-depth. With the write gate UNSET, place_market must
    # fail CLOSED (REJECTED) WITHOUT ever calling the client (no POST sent).
    monkeypatch.delenv("SAXO_WRITES_ENABLED", raising=False)
    res = place_market("AbC==", 222, "Buy", 82, client=fake_client)
    assert res.status == "REJECTED"
    assert "writes disabled" in res.detail
    assert fake_client.calls == []          # never hit the wire
