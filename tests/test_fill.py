# tests/test_fill.py
from saxo_mcp.orders import wait_for_fill


WORK = "/port/v1/orders/me"
POS = "/port/v1/positions/me"


def test_fill_detected_when_order_leaves_working_list(fake_client):
    fake_client.queue("GET", WORK,
        {"Data": [{"OrderId": "111"}]},   # poll 1: still working
        {"Data": []},                      # poll 2: gone -> filled
    )
    fake_client.queue("GET", POS, {"Data": [
        {"PositionBase": {"Uic": 222, "OpenPrice": 24.21}},
    ]})
    res = wait_for_fill("111", 222, timeout_s=1.0, poll_interval_s=0.01,
                        client=fake_client)
    assert res.filled is True
    assert res.fill_price == 24.21


def test_timeout_returns_unfilled(fake_client):
    fake_client.queue("GET", WORK, *([{"Data": [{"OrderId": "111"}]}] * 50))
    res = wait_for_fill("111", 222, timeout_s=0.05, poll_interval_s=0.01,
                        client=fake_client)
    assert res.filled is False
    assert "timeout" in res.detail


def test_fill_without_position_price(fake_client):
    fake_client.queue("GET", WORK, {"Data": []})
    fake_client.queue("GET", POS, {"Data": []})
    res = wait_for_fill("111", 222, timeout_s=1.0, poll_interval_s=0.01,
                        client=fake_client)
    assert res.filled is True and res.fill_price is None


def test_fill_with_errored_position_read_flags_detail(fake_client):
    fake_client.queue("GET", WORK, {"Data": []})
    fake_client.queue("GET", POS, (500, {"Message": "boom"}))
    res = wait_for_fill("111", 222, timeout_s=1.0, poll_interval_s=0.01,
                        client=fake_client)
    assert res.filled is True and res.fill_price is None
    assert "position read errored" in res.detail
