# tests/test_bracket.py
import pytest

from saxo_mcp.orders import attach_bracket_oco


ORDERS = "/trade/v2/orders"


@pytest.fixture(autouse=True)
def _enable_writes(monkeypatch):
    # attach_bracket_oco self-gates on SAXO_WRITES_ENABLED (FIX 2); these tests
    # exercise the on-the-wire behaviour, so enable the SIM write gate.
    monkeypatch.setenv("SAXO_ENV", "sim")
    monkeypatch.setenv("SAXO_WRITES_ENABLED", "1")


def test_oco_placed_with_ids(fake_client):
    fake_client.queue("POST", ORDERS,
                      {"Orders": [{"OrderId": "71"}, {"OrderId": "72"}]})
    res = attach_bracket_oco("AbC==", 222, 82, tp_price=30.06, sl_price=22.13,
                             client=fake_client)
    assert res.status == "PLACED_OCO"
    assert (res.tp_order_id, res.sl_order_id) == ("71", "72")
    body = fake_client.calls[0][2]
    legs = body["Orders"]
    assert len(legs) == 2 and "OrderRelation" not in body
    tp, sl = legs
    assert tp["OrderType"] == "Limit" and tp["OrderPrice"] == 30.06
    assert sl["OrderType"] == "StopIfTraded" and sl["OrderPrice"] == 22.13
    for leg in legs:
        assert leg["BuySell"] == "Sell"
        assert leg["OrderDuration"] == {"DurationType": "GoodTillCancel"}
        assert "ToOpenClose" not in leg        # stock legs: no ToOpenClose


def test_oco_binds_ids_by_external_reference_not_position(fake_client):
    # REGRESSION (C1): Saxo may echo the Orders array in any order. The TP leg
    # (Limit) carries an "...-tp-..." ExternalReference and the SL leg
    # (StopIfTraded) an "...-sl-..." ref. Return them REVERSED [sl, tp] and
    # assert ids bind by ref, NOT by array position (a positional bind here
    # would cancel the wrong leg later).
    fake_client.queue("POST", ORDERS, {"Orders": [
        {"OrderId": "SL999", "ExternalReference": "sa-bracket-sl-222"},
        {"OrderId": "TP111", "ExternalReference": "sa-bracket-tp-222"},
    ]})
    res = attach_bracket_oco("AbC==", 222, 82, tp_price=30.06, sl_price=22.13,
                             client=fake_client)
    assert res.status == "PLACED_OCO"
    assert res.tp_order_id == "TP111"   # bound by -tp- ref, not ids[0]
    assert res.sl_order_id == "SL999"   # bound by -sl- ref, not ids[1]


def test_oco_falls_back_to_position_when_refs_absent(fake_client):
    # If the broker omits ExternalReference, fall back to request order
    # (TP was sent first, SL second) so behaviour degrades gracefully.
    fake_client.queue("POST", ORDERS,
                      {"Orders": [{"OrderId": "71"}, {"OrderId": "72"}]})
    res = attach_bracket_oco("AbC==", 222, 82, tp_price=30.06, sl_price=22.13,
                             client=fake_client)
    assert res.status == "PLACED_OCO"
    assert (res.tp_order_id, res.sl_order_id) == ("71", "72")


def test_oco_2xx_without_ids_is_on_book(fake_client):
    fake_client.queue("POST", ORDERS, {})      # 200 but empty body
    res = attach_bracket_oco("AbC==", 222, 82, tp_price=30.0, sl_price=22.0,
                             client=fake_client)
    assert res.status == "PLACED_OCO_NO_ID"    # do NOT re-place!


def test_oco_4xx_rejected(fake_client):
    fake_client.queue("POST", ORDERS, (400, {"Message": "bad leg"}))
    res = attach_bracket_oco("AbC==", 222, 82, tp_price=30.0, sl_price=22.0,
                             client=fake_client)
    assert res.status == "OCO_REJECTED"


def test_oco_5xx_ambiguous(fake_client):
    fake_client.queue("POST", ORDERS, (502, {"Message": "gateway"}))
    res = attach_bracket_oco("AbC==", 222, 82, tp_price=30.0, sl_price=22.0,
                             client=fake_client)
    assert res.status == "OCO_AMBIGUOUS"       # reconcile before retrying


def test_option_legs_carry_toclose(fake_client):
    fake_client.queue("POST", ORDERS,
                      {"Orders": [{"OrderId": "81"}, {"OrderId": "82"}]})
    res = attach_bracket_oco("AbC==", 333, 1, tp_price=17.85, sl_price=2.98,
                             asset_type="StockOption", to_open_close="ToClose",
                             client=fake_client)
    assert res.status == "PLACED_OCO"
    for leg in fake_client.calls[0][2]["Orders"]:
        assert leg["ToOpenClose"] == "ToClose"
