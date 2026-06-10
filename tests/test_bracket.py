# tests/test_bracket.py
from saxo_mcp.orders import attach_bracket_oco


ORDERS = "/trade/v2/orders"


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
