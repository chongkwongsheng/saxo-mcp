# tests/test_orders_scaffold.py
from saxo_mcp.orders import (
    BracketResult, FillResult, PlaceResult, UicCache, writes_enabled,
)


def test_writes_enabled_sim_requires_flag(monkeypatch):
    monkeypatch.setenv("SAXO_ENV", "sim")
    monkeypatch.setenv("SAXO_WRITES_ENABLED", "")
    assert writes_enabled() is False
    monkeypatch.setenv("SAXO_WRITES_ENABLED", "1")
    assert writes_enabled() is True


def test_writes_enabled_live_requires_explicit_phrase(monkeypatch):
    monkeypatch.setenv("SAXO_ENV", "live")
    monkeypatch.setenv("SAXO_WRITES_ENABLED", "1")
    assert writes_enabled() is False
    monkeypatch.setenv("SAXO_WRITES_ENABLED", "live-i-mean-it")
    assert writes_enabled() is True


def test_uic_cache_roundtrip():
    c = UicCache()
    assert c.get("GME") is None
    c.put("GME", 12345)
    assert c.get("GME") == 12345


def test_result_dataclasses_have_declared_fields():
    p = PlaceResult(status="PLACED", order_id="1", detail="")
    f = FillResult(filled=True, fill_price=24.21, elapsed_s=3.0)
    b = BracketResult(status="PLACED_OCO", tp_order_id="2", sl_order_id="3")
    assert (p.order_id, f.fill_price, b.sl_order_id) == ("1", 24.21, "3")


def test_tools_write_uses_shared_gate(monkeypatch):
    from saxo_mcp import tools_write
    monkeypatch.setenv("SAXO_ENV", "sim")
    monkeypatch.setenv("SAXO_WRITES_ENABLED", "1")
    assert tools_write._writes_enabled() is True
