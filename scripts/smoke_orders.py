# scripts/smoke_orders.py
"""Manual SIM smoke test for saxo_mcp.orders. NOT run by pytest.

Places ONE tiny real SIM order (1 share) with a bracket, then cancels the
bracket and prints every result. Requires: saxo-mcp login, SAXO_ENV=sim,
SAXO_WRITES_ENABLED=1, and an explicit --yes flag.

Run:  .venv\\Scripts\\python.exe scripts\\smoke_orders.py --ticker AAPL --yes
"""
from __future__ import annotations

import argparse
import sys

from saxo_mcp import orders


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="AAPL")
    ap.add_argument("--qty", type=float, default=1)
    ap.add_argument("--yes", action="store_true",
                    help="required: confirms a REAL SIM order will be placed")
    args = ap.parse_args()

    if args.qty <= 0:
        print("Refusing: --qty must be positive.")
        return 2
    if not args.yes:
        print("Refusing: pass --yes to place a real SIM order.")
        return 2
    if not orders.writes_enabled():
        print("Refusing: writes disabled (set SAXO_ENV=sim, SAXO_WRITES_ENABLED=1).")
        return 2

    key = orders.get_account_key()
    print(f"account_key: {key}")
    if not key:
        return 1
    uic = orders.resolve_stock_uic(args.ticker)
    print(f"uic({args.ticker}): {uic}")
    if not uic:
        return 1
    ok, why = orders.precheck_ok(key, uic, "Buy", args.qty)
    print(f"precheck: {ok} ({why})")
    if not ok:
        return 1
    res = orders.place_market(key, uic, "Buy", args.qty)
    print(f"place: {res}")
    if res.status != "PLACED" or not res.order_id:
        return 1
    fill = orders.wait_for_fill(res.order_id, uic, timeout_s=60)
    print(f"fill: {fill}")
    if not (fill.filled and fill.fill_price):
        print("No confirmed fill within timeout - check SaxoTraderGO; "
              "skipping bracket.")
        return 1
    tp = round(fill.fill_price * 1.25, 2)
    sl = round(fill.fill_price * 0.92, 2)
    br = orders.attach_bracket_oco(key, uic, args.qty, tp_price=tp, sl_price=sl)
    print(f"bracket: {br}")
    if br.status in ("PLACED_OCO",) and br.tp_order_id:
        print("cancelling bracket legs to leave a clean book...")
        print(f"  cancel tp: {orders.cancel_order(br.tp_order_id, key)}")
        if br.sl_order_id:
            print(f"  cancel sl: {orders.cancel_order(br.sl_order_id, key)}")
    print("SMOKE DONE - position remains open (1 share); close manually "
          "or leave on SIM.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
