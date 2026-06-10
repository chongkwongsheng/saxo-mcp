# tests/test_reads_cancel.py
import pytest

from saxo_mcp.orders import cancel_order, positions, working_orders


WORK = "/port/v1/orders/me"
POS = "/port/v1/positions/me"


@pytest.fixture(autouse=True)
def _enable_writes(monkeypatch):
    # cancel_order self-gates on SAXO_WRITES_ENABLED (FIX 2); the cancel tests
    # exercise the wire path, so enable the SIM write gate. The dedicated
    # gate-off test delenv()s it to override this.
    monkeypatch.setenv("SAXO_ENV", "sim")
    monkeypatch.setenv("SAXO_WRITES_ENABLED", "1")


def test_cancel_order_true_on_2xx(fake_client):
    fake_client.queue("DELETE", "/trade/v2/orders/71", {})
    assert cancel_order("71", "AbC==", client=fake_client) is True
    assert fake_client.calls[0][2] == {"AccountKey": "AbC=="}


def test_cancel_order_false_on_error(fake_client):
    fake_client.queue("DELETE", "/trade/v2/orders/71", (404, {"Message": "gone"}))
    assert cancel_order("71", "AbC==", client=fake_client) is False


def test_cancel_order_self_gates_when_writes_disabled(monkeypatch, fake_client):
    # H-2: with the write gate UNSET, cancel_order fails CLOSED (False) WITHOUT
    # calling the client. False already means "reconcile" to callers.
    monkeypatch.delenv("SAXO_WRITES_ENABLED", raising=False)
    assert cancel_order("71", "AbC==", client=fake_client) is False
    assert fake_client.calls == []          # never hit the wire


def test_working_orders_filters_by_uic(fake_client):
    fake_client.queue("GET", WORK, {"Data": [
        {"OrderId": "1", "Uic": 222}, {"OrderId": "2", "Uic": 333},
    ]})
    rows = working_orders(uic=222, client=fake_client)
    assert [r["OrderId"] for r in rows] == ["1"]


def test_positions_filters_by_uic(fake_client):
    fake_client.queue("GET", POS, {"Data": [
        {"PositionBase": {"Uic": 222, "Amount": 82}},
        {"PositionBase": {"Uic": 333, "Amount": 1}},
    ]})
    rows = positions(uic=222, client=fake_client)
    assert len(rows) == 1 and rows[0]["PositionBase"]["Amount"] == 82


def test_auth_keepalive_healthy(monkeypatch):
    from saxo_mcp import orders
    monkeypatch.setattr(orders.auth, "get_access_token", lambda: "tok")
    monkeypatch.setattr(orders.auth, "status",
                        lambda: {"access_token_expires_in_seconds": 1130})
    ok, detail = orders.auth_keepalive()
    assert ok is True and "1130" in detail


def test_auth_keepalive_failure(monkeypatch):
    from saxo_mcp import orders

    def boom():
        raise RuntimeError("Run `saxo-mcp login` to re-authenticate.")

    monkeypatch.setattr(orders.auth, "get_access_token", boom)
    ok, detail = orders.auth_keepalive()
    assert ok is False and "login" in detail
