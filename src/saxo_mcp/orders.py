# src/saxo_mcp/orders.py
"""Programmatic order primitives for the Saxo OpenAPI (SIM-first).

Adapted from regime-allocator strategy/execute.py (resolver, fill-wait,
native-OCO bracket) with its design-review fixes applied:
  - result types are declared dataclasses (asdict-safe; no dynamic attrs)
  - UIC cache is an explicit object, not a mutated module-private dict
  - NO interactive 2FA here: gating = SAXO_WRITES_ENABLED + caller policy.
    Primitives also self-gate (fail-closed); callers still own policy.
  - OCO placement is status-disciplined: 2xx=on book, 4xx=definitively
    rejected, 5xx/transport=AMBIGUOUS (caller must reconcile before retry)

Every function takes an injectable `client` (anything with get/post/delete/
request_raw — see SaxoClient) so callers can unit-test offline.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

from . import auth
from .client import get_client


def writes_enabled() -> bool:
    """Single source of truth for the write gate (tools_write re-uses this).
    SIM needs SAXO_WRITES_ENABLED=1; LIVE needs the explicit phrase."""
    env = os.getenv("SAXO_ENV", "sim").lower()
    flag = os.getenv("SAXO_WRITES_ENABLED", "")
    if env == "live":
        return flag == "live-i-mean-it"
    return flag == "1"


class UicCache:
    """Explicit per-caller UIC cache (ticker -> uic). Replaces the
    module-private _UIC_CACHE pattern the review flagged."""

    def __init__(self) -> None:
        self._d: dict[str, int | None] = {}

    def get(self, ticker: str) -> int | None:
        return self._d.get(ticker)

    def put(self, ticker: str, uic: int | None) -> None:
        self._d[ticker] = uic


@dataclass
class PlaceResult:
    status: str                  # PLACED | REJECTED | ERROR
    order_id: str | None = None
    detail: str = ""


@dataclass
class FillResult:
    filled: bool
    fill_price: float | None = None
    elapsed_s: float = 0.0
    detail: str = ""


@dataclass
class BracketResult:
    status: str                  # PLACED_OCO | PLACED_OCO_NO_ID | OCO_REJECTED | OCO_AMBIGUOUS
    tp_order_id: str | None = None
    sl_order_id: str | None = None
    detail: str = ""


@dataclass
class Quote:
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    delayed: bool = False
    detail: str = ""


def resolve_stock_uic(
    ticker: str,
    client=None,
    cache: UicCache | None = None,
) -> int | None:
    """UIC for a stock ticker via /ref/v1/instruments keyword search.
    Strips Saxo ':xnys' and Yahoo '.SI' style suffixes, requires an EXACT
    symbol match (prefix lookalikes like GMED for GME must not win).
    Returns None when unresolved (caller decides whether that's fatal)."""
    client = client or get_client()
    keyword = ticker.split(":")[0].split(".")[0].upper()
    if cache is not None:
        hit = cache.get(keyword)
        if hit is not None:
            return hit
    uic: int | None = None
    try:
        data = client.get(
            "/ref/v1/instruments",
            params={"Keywords": keyword, "AssetTypes": "Stock"},
        )
        for item in data.get("Data", []):
            if str(item.get("Symbol", "")).upper().split(":")[0] == keyword:
                ident = item.get("Identifier")
                uic = int(ident) if ident is not None else None
                break
    except Exception:
        uic = None
    if cache is not None and uic is not None:
        cache.put(keyword, uic)
    return uic


def get_account_key(client=None) -> str | None:
    """AccountKey of the first account on /port/v1/accounts/me. Accounts
    rotate on SIM — always fetch live, never hard-code."""
    client = client or get_client()
    try:
        data = client.get("/port/v1/accounts/me")
        accounts = data.get("Data", [])
        return accounts[0].get("AccountKey") if accounts else None
    except Exception:
        return None


def get_account_id(client=None) -> str | None:
    """Human-readable account NUMBER (AccountId) of the first account on
    /port/v1/accounts/me. Distinct from get_account_key (opaque GUID): the
    AccountId is what the operator reads off the Saxo UI, so it is the value
    used for last-4-digits arming challenges and trade-time identity checks.
    None on any error or empty account list (fail-closed)."""
    client = client or get_client()
    try:
        data = client.get("/port/v1/accounts/me")
        accounts = data.get("Data", [])
        aid = accounts[0].get("AccountId") if accounts else None
        return str(aid) if aid is not None else None
    except Exception:
        return None


def get_quote(uic: int, asset_type: str = "Stock", client=None) -> Quote | None:
    """Live (or delayed-flagged) prices via GET /trade/v1/infoprices.
    None on transport/shape error (fail-closed for gating callers). A response
    missing one side keeps the other side None — the CALLER decides which
    sides it needs (aimbot's drift gate needs both and blocks otherwise)."""
    client = client or get_client()
    try:
        data = client.get("/trade/v1/infoprices",
                          params={"Uic": uic, "AssetType": asset_type})
        q = data.get("Quote")
        if not isinstance(q, dict):
            return None

        def _f(key: str) -> float | None:
            v = q.get(key)
            return float(v) if v is not None else None

        return Quote(bid=_f("Bid"), ask=_f("Ask"), mid=_f("Mid"),
                     delayed=float(q.get("DelayedByMinutes", 0) or 0) > 0,
                     detail=f"DelayedByMinutes={q.get('DelayedByMinutes', 0)}")
    except Exception:
        return None


def _order_body(
    account_key: str,
    uic: int,
    side: str,
    qty: float,
    *,
    asset_type: str = "Stock",
    order_type: str = "Market",
    price: float | None = None,
    duration: str = "DayOrder",
    manual_order: bool = False,
) -> dict:
    """Canonical Saxo order body. Stocks carry NO ToOpenClose (that field is
    required for derivatives only — regime-allocator lesson: sending the
    wrong/missing value 400s option orders, but stocks reject the field)."""
    body: dict = {
        "AccountKey": account_key,
        "Uic": uic,
        "AssetType": asset_type,
        "BuySell": side,
        "Amount": qty,
        "OrderType": order_type,
        "OrderDuration": {"DurationType": duration},
        "ManualOrder": manual_order,
    }
    if price is not None:
        body["OrderPrice"] = price
    return body


def precheck_ok(
    account_key: str,
    uic: int,
    side: str,
    qty: float,
    *,
    asset_type: str = "Stock",
    order_type: str = "Market",
    price: float | None = None,
    manual_order: bool = False,
    client=None,
) -> tuple[bool, str]:
    """POST /trade/v2/orders/precheck. (ok, detail). Read-only on Saxo's side."""
    client = client or get_client()
    body = _order_body(
        account_key, uic, side, qty, asset_type=asset_type,
        order_type=order_type, price=price, manual_order=manual_order,
    )
    try:
        resp = client.post("/trade/v2/orders/precheck", json=body)
    except Exception as e:  # noqa: BLE001
        return False, f"precheck transport error: {e}"
    result = str(resp.get("PreCheckResult", ""))
    if result.lower() == "ok":
        return True, f"Ok (EstimatedCashRequired={resp.get('EstimatedCashRequired')})"
    if not result:
        # Deliberate departure from regime-allocator's precheck_clean (which
        # treats a missing PreCheckResult as acceptable): this module serves
        # AUTOMATED callers, so an unexpected precheck shape fails CLOSED.
        return False, f"no PreCheckResult in response: {resp}"
    return False, f"{result}: {resp.get('ErrorInfo', {})}"


def place_market(
    account_key: str,
    uic: int,
    side: str,
    qty: float,
    *,
    asset_type: str = "Stock",
    manual_order: bool = False,
    client=None,
) -> PlaceResult:
    """Place a market order. Status discipline:
    2xx -> PLACED; 4xx -> REJECTED (definitively not on book);
    5xx/transport -> ERROR (MAY be on book — caller must reconcile via
    working_orders()/positions() before any retry).

    Self-gates on SAXO_WRITES_ENABLED (H-2 defense-in-depth): if writes are
    disabled this returns REJECTED WITHOUT touching the client."""
    if not writes_enabled():
        return PlaceResult(status="REJECTED",
                           detail="writes disabled (SAXO_WRITES_ENABLED unset)")
    client = client or get_client()
    body = _order_body(account_key, uic, side, qty,
                       asset_type=asset_type, manual_order=manual_order)
    try:
        status, resp = client.request_raw("POST", "/trade/v2/orders", json=body)
    except Exception as e:  # noqa: BLE001
        return PlaceResult(status="ERROR", detail=f"transport: {e}")
    if 200 <= status < 300:
        oid = resp.get("OrderId")
        return PlaceResult(status="PLACED",
                           order_id=str(oid) if oid else None,
                           detail=f"HTTP {status}")
    if 400 <= status < 500:
        return PlaceResult(status="REJECTED", detail=f"HTTP {status}: {resp}")
    return PlaceResult(status="ERROR", detail=f"HTTP {status}: {resp}")


def wait_for_fill(
    order_id: str,
    uic: int,
    *,
    timeout_s: float = 60.0,
    poll_interval_s: float = 3.0,
    client=None,
    sleep_fn=time.sleep,
) -> FillResult:
    """Poll /port/v1/orders/me until order_id leaves the working list
    (= filled OR cancelled/rejected), then read the position's OpenPrice for
    the fill. Caller chooses timeout; on timeout the order may STILL fill
    later — squeeze-aimbot's heal sweeper covers that gap (the
    regime-allocator 34-unbracketed-positions lesson).

    H2: leaving the working list is ambiguous — it means filled OR
    cancelled/rejected. filled=True is returned ONLY when a same-UIC position
    is actually observed; if the order left the list but no matching position
    is visible, filled=False (possibly cancelled/rejected). A position read
    that ERRORS is distinct: filled stays True (fill_price unknown, not
    absent), because the order is known to have left as a fill candidate.

    H1 — FILL-PRICE ATTRIBUTION LIMIT: fill_price is the position-average
    OpenPrice for this UIC. If the account already holds the same UIC
    (re-entries, manual positions, netted/averaged positions), this is NOT
    necessarily this order's marginal fill price. Callers MUST NOT trust
    fill_price for averaged positions. When more than one same-UIC position is
    present at read time, detail flags it. (A proper per-order correlation is a
    tracked follow-up, not done here.)"""
    client = client or get_client()
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        if elapsed > timeout_s:
            return FillResult(filled=False, elapsed_s=elapsed,
                              detail=f"timeout after {timeout_s}s")
        try:
            working = client.get("/port/v1/orders/me").get("Data", [])
        except Exception:
            sleep_fn(poll_interval_s)
            # H3: re-check the deadline AFTER sleeping so a persistently
            # slow/erroring endpoint cannot overrun timeout_s by another poll.
            if time.monotonic() - start > timeout_s:
                return FillResult(
                    filled=False, elapsed_s=time.monotonic() - start,
                    detail=f"timeout after {timeout_s}s")
            continue
        if not any(str(w.get("OrderId")) == str(order_id) for w in working):
            break
        sleep_fn(poll_interval_s)
    fill_price: float | None = None
    matched = False
    read_errored = False
    same_uic_count = 0
    detail = f"OrderId={order_id} left working list"
    try:
        rows = client.get("/port/v1/positions/me").get("Data", [])
        for p in rows:
            pb = p.get("PositionBase", {})
            if pb.get("Uic") == uic:
                same_uic_count += 1
                matched = True
                if fill_price is None and pb.get("OpenPrice") is not None:
                    fill_price = float(pb["OpenPrice"])
    except Exception:
        read_errored = True
        fill_price = None
        detail += "; position read errored (fill_price unknown, not absent)"
    # H1: more than one same-UIC position -> fill_price is an average, not this
    # order's marginal fill. Flag it so callers don't trust the number.
    if same_uic_count > 1:
        detail += (f"; WARNING {same_uic_count} same-UIC positions present — "
                   "fill_price is position-average, not this order's fill")
    # H2: a clean read showing NO same-UIC position means this order left the
    # list without a fill (cancelled/rejected) — do NOT report filled=True.
    if not matched and not read_errored:
        return FillResult(
            filled=False, fill_price=None,
            elapsed_s=time.monotonic() - start,
            detail=detail + "; order no longer working but no fill observed "
                            "(possibly cancelled/rejected)")
    return FillResult(filled=True, fill_price=fill_price,
                      elapsed_s=time.monotonic() - start,
                      detail=detail)


def attach_bracket_oco(
    account_key: str,
    uic: int,
    qty: float,
    *,
    tp_price: float,
    sl_price: float,
    asset_type: str = "Stock",
    to_open_close: str | None = None,
    manual_order: bool = False,
    ext_ref_prefix: str = "sa-bracket",
    client=None,
) -> BracketResult:
    """SELL TP (Limit) + SELL SL (StopIfTraded) as ONE native Saxo OCO.
    A two-element Orders array IS the OCO signal — there is no
    OrderRelation field, and plain 'Stop' is rejected for OCO legs.
    Stocks omit ToOpenClose; derivatives pass to_open_close='ToClose'.

    Status discipline (regime-allocator lesson — do not soften):
      PLACED_OCO        2xx, both ids parsed -> on the book
      PLACED_OCO_NO_ID  2xx, ids missing     -> ON THE BOOK; never re-place
      OCO_REJECTED      4xx                  -> definitively NOT on book
      OCO_AMBIGUOUS     5xx/transport        -> unknown; caller MUST check
                                               working_orders() before retry

    Self-gates on SAXO_WRITES_ENABLED (H-2 defense-in-depth): if writes are
    disabled this returns OCO_REJECTED WITHOUT touching the client.
    """
    if not writes_enabled():
        return BracketResult(
            status="OCO_REJECTED",
            detail="writes disabled (SAXO_WRITES_ENABLED unset)")
    client = client or get_client()

    def _leg(order_type: str, price: float, tag: str) -> dict:
        leg = {
            "AccountKey": account_key,
            "Uic": uic,
            "AssetType": asset_type,
            "BuySell": "Sell",
            "Amount": qty,
            "OrderType": order_type,
            "OrderPrice": price,
            "OrderDuration": {"DurationType": "GoodTillCancel"},
            "ManualOrder": manual_order,
            "ExternalReference": f"{ext_ref_prefix}-{tag}-{uic}",
        }
        if to_open_close is not None:
            leg["ToOpenClose"] = to_open_close
        return leg

    body = {"Orders": [_leg("Limit", tp_price, "tp"),
                       _leg("StopIfTraded", sl_price, "sl")]}
    try:
        status, resp = client.request_raw("POST", "/trade/v2/orders", json=body)
    except Exception as e:  # noqa: BLE001
        return BracketResult(status="OCO_AMBIGUOUS", detail=f"transport: {e}")
    if 200 <= status < 300:
        # C1 fix: bind TP/SL ids by ExternalReference, NOT array position.
        # Saxo may echo the Orders array in any order; a positional bind
        # (ids[0]=tp, ids[1]=sl) would silently swap the legs and later cancel
        # the WRONG one. The legs carry "...-tp-..."/"...-sl-..." refs (see
        # _leg's tag); fall back to request order only when refs are absent.
        # Mirrors regime-allocator strategy/execute.py:3222-3236.
        by_ref: dict[str, str] = {}
        ids: list[str] = []
        for o in resp.get("Orders", []):
            oid = o.get("OrderId")
            if not oid:
                continue
            oid = str(oid)
            ids.append(oid)
            ref = o.get("ExternalReference", "") or ""
            if "-tp-" in ref:
                by_ref["tp"] = oid
            elif "-sl-" in ref:
                by_ref["sl"] = oid
        tp_id = by_ref.get("tp") or (ids[0] if ids else None)
        sl_id = by_ref.get("sl") or (ids[1] if len(ids) > 1 else None)
        if tp_id and sl_id:
            return BracketResult(status="PLACED_OCO",
                                 tp_order_id=tp_id, sl_order_id=sl_id,
                                 detail=f"HTTP {status}")
        return BracketResult(status="PLACED_OCO_NO_ID",
                             detail=f"HTTP {status}: ids missing in {resp}")
    if 400 <= status < 500:
        return BracketResult(status="OCO_REJECTED", detail=f"HTTP {status}: {resp}")
    return BracketResult(status="OCO_AMBIGUOUS", detail=f"HTTP {status}: {resp}")


def cancel_order(order_id: str, account_key: str, client=None) -> bool:
    """DELETE a working order. True on 2xx; False otherwise (already
    filled/cancelled orders 404 — callers treat False as 'reconcile').

    Self-gates on SAXO_WRITES_ENABLED (H-2 defense-in-depth): if writes are
    disabled this returns False (fail-closed; callers already treat False as
    'not confirmed -> reconcile') WITHOUT touching the client. The reason is
    surfaced via stderr since the bool contract carries no detail field."""
    if not writes_enabled():
        print("cancel_order: writes disabled (SAXO_WRITES_ENABLED unset); "
              f"refusing to cancel OrderId={order_id}", file=sys.stderr)
        return False
    client = client or get_client()
    try:
        status, _ = client.request_raw(
            "DELETE", f"/trade/v2/orders/{order_id}",
            params={"AccountKey": account_key},
        )
        return 200 <= status < 300
    except Exception:
        return False


def working_orders(uic: int | None = None, client=None) -> list[dict]:
    """Open/working orders, optionally filtered to one UIC."""
    client = client or get_client()
    try:
        rows = client.get("/port/v1/orders/me").get("Data", [])
    except Exception:
        return []
    if uic is None:
        return rows
    return [r for r in rows if r.get("Uic") == uic]


def positions(uic: int | None = None, client=None) -> list[dict]:
    """Open positions (raw Saxo rows), optionally filtered to one UIC."""
    client = client or get_client()
    try:
        rows = client.get("/port/v1/positions/me").get("Data", [])
    except Exception:
        return []
    if uic is None:
        return rows
    return [r for r in rows
            if r.get("PositionBase", {}).get("Uic") == uic]


def auth_keepalive() -> tuple[bool, str]:
    """Proactively refresh the Saxo token chain. Long-running callers MUST
    invoke this on a timer (~10 min): Saxo SIM refresh tokens are ~1h
    ROLLING, and get_access_token() refreshes only on demand — a process
    with no Saxo traffic for >1h silently loses the chain and the next
    call fails needing interactive `saxo-mcp login`. Each successful
    refresh rolls the refresh token, keeping the chain alive indefinitely
    while the caller keeps calling. Returns (healthy, detail)."""
    try:
        auth.get_access_token()
    except Exception as e:  # noqa: BLE001
        return False, f"keepalive failed: {e}"
    s = auth.status()
    return True, (f"token ok, "
                  f"{s.get('access_token_expires_in_seconds', '?')}s left")
