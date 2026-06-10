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


def test_order_left_list_but_no_position_is_not_filled(fake_client):
    # H2: leaving the working list means filled OR cancelled/rejected. If no
    # same-UIC position is observable, do NOT claim filled=True.
    fake_client.queue("GET", WORK, {"Data": []})
    fake_client.queue("GET", POS, {"Data": []})
    res = wait_for_fill("111", 222, timeout_s=1.0, poll_interval_s=0.01,
                        client=fake_client)
    assert res.filled is False
    assert res.fill_price is None
    assert "no fill observed" in res.detail
    assert "cancelled" in res.detail or "rejected" in res.detail


def test_order_left_list_but_different_uic_position_is_not_filled(fake_client):
    # H2: a position for a DIFFERENT uic must not be mistaken for this fill.
    fake_client.queue("GET", WORK, {"Data": []})
    fake_client.queue("GET", POS, {"Data": [
        {"PositionBase": {"Uic": 999, "OpenPrice": 11.0}},
    ]})
    res = wait_for_fill("111", 222, timeout_s=1.0, poll_interval_s=0.01,
                        client=fake_client)
    assert res.filled is False
    assert res.fill_price is None
    assert "no fill observed" in res.detail


def test_fill_with_errored_position_read_flags_detail(fake_client):
    # Distinct from clean no-fill: the order left the list AND a same-uic
    # position exists, but the position READ errored -> fill_price unknown,
    # not absent. This path stays filled=True (we know it left as a fill).
    fake_client.queue("GET", WORK, {"Data": []})
    fake_client.queue("GET", POS, (500, {"Message": "boom"}))
    res = wait_for_fill("111", 222, timeout_s=1.0, poll_interval_s=0.01,
                        client=fake_client)
    assert res.filled is True and res.fill_price is None
    assert "position read errored" in res.detail


def test_exception_then_timeout_exits_promptly(monkeypatch, fake_client):
    # H3: re-check the monotonic deadline AFTER the exception-path sleep, so a
    # persistently erroring endpoint cannot overrun timeout_s by a full extra
    # iteration. A fake clock is advanced by sleep_fn; the working-list GET
    # always errors, so the loop only exits via the deadline.
    from saxo_mcp import orders

    clock = {"t": 0.0}
    monkeypatch.setattr(orders.time, "monotonic", lambda: clock["t"])

    def fake_sleep(dt):
        clock["t"] += dt

    # WORK always errors (500) -> exception path every poll.
    fake_client.queue("GET", WORK, *([(500, {"Message": "down"})] * 100))

    res = wait_for_fill("111", 222, timeout_s=1.0, poll_interval_s=0.4,
                        client=fake_client, sleep_fn=fake_sleep)
    assert res.filled is False
    assert "timeout" in res.detail
    # With deadline re-checked after the exception sleep, the loop stops as
    # soon as the clock passes 1.0s: polls at t=0.0, 0.4, 0.8 then 1.2 > 1.0
    # exits -> at most 4 GETs. The old top-of-loop-only code would waste an
    # extra poll. Bound generously but tight enough to catch a full overrun.
    work_calls = [c for c in fake_client.calls if c[1] == WORK]
    assert len(work_calls) <= 4
