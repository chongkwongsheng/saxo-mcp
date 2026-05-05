"""Write MCP tools: precheck (always) + place/cancel/modify (gated).

Gate layers:
  1. Env flag SAXO_WRITES_ENABLED — must be "1" on SIM or "live-i-mean-it" on LIVE,
     otherwise place/cancel/modify are NOT registered as tools at all.
  2. Every write tool requires an explicit `confirm=True` argument.
  3. Tool docstrings instruct the LLM to call precheck_order first and surface
     the result to the user before any write call.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from .client import get_client


def _writes_enabled() -> bool:
    env = os.getenv("SAXO_ENV", "sim").lower()
    flag = os.getenv("SAXO_WRITES_ENABLED", "")
    if env == "live":
        return flag == "live-i-mean-it"
    return flag == "1"


def register(mcp: FastMCP) -> None:
    # --- precheck is always registered (Saxo's precheck endpoint is read-only) ---

    @mcp.tool()
    def precheck_order(
        account_key: str,
        uic: int,
        asset_type: str,
        buy_sell: str,
        amount: float,
        order_type: str = "Market",
        order_price: float | None = None,
        order_duration: str = "DayOrder",
    ) -> dict:
        """Precheck an order WITHOUT placing it. Saxo returns estimated
        cost, margin impact, and any validation errors. Call this first,
        ALWAYS surface the result to the user, and only proceed to
        place_order after the user explicitly confirms.

        Args:
            account_key: AccountKey from get_accounts
            uic: instrument UIC
            asset_type: e.g. "Stock", "FxSpot"
            buy_sell: "Buy" or "Sell"
            amount: quantity (shares, lots, etc. depending on asset type)
            order_type: "Market", "Limit", "Stop", "StopLimit", etc.
            order_price: required for Limit / Stop orders
            order_duration: "DayOrder", "GoodTillCancel", "ImmediateOrCancel", ...
        """
        body: dict = {
            "AccountKey": account_key,
            "Uic": uic,
            "AssetType": asset_type,
            "BuySell": buy_sell,
            "Amount": amount,
            "OrderType": order_type,
            "OrderDuration": {"DurationType": order_duration},
        }
        if order_price is not None:
            body["OrderPrice"] = order_price
        return get_client().post("/trade/v2/orders/precheck", json=body)

    if not _writes_enabled():
        # Writes disabled — stop here. place/cancel/modify simply don't exist
        # as MCP tools, so the LLM can't call them even by accident.
        return

    @mcp.tool()
    def place_order(
        account_key: str,
        uic: int,
        asset_type: str,
        buy_sell: str,
        amount: float,
        confirm: bool,
        order_type: str = "Market",
        order_price: float | None = None,
        order_duration: str = "DayOrder",
    ) -> dict:
        """WRITE OPERATION — places a REAL order on Saxo.

        Requirements before calling this:
          1. You MUST have called precheck_order with the same parameters.
          2. You MUST have surfaced the precheck result to the user.
          3. The user MUST have explicitly confirmed the trade.
          4. `confirm` MUST be True (refused otherwise).

        On SIM this uses simulated money. Still behave as if it were real.
        """
        if not confirm:
            return {
                "error": "confirm=True required. Call precheck_order first, "
                "show the result to the user, and only set confirm=True after "
                "the user explicitly agrees."
            }
        body: dict = {
            "AccountKey": account_key,
            "Uic": uic,
            "AssetType": asset_type,
            "BuySell": buy_sell,
            "Amount": amount,
            "OrderType": order_type,
            "OrderDuration": {"DurationType": order_duration},
        }
        if order_price is not None:
            body["OrderPrice"] = order_price
        return get_client().post("/trade/v2/orders", json=body)

    @mcp.tool()
    def cancel_order(order_id: str, account_key: str, confirm: bool) -> dict:
        """WRITE OPERATION — cancels a working order. `confirm` must be True.

        Args:
            order_id: OrderId from get_orders
            account_key: AccountKey that owns the order
            confirm: must be True; refused otherwise
        """
        if not confirm:
            return {"error": "confirm=True required."}
        return get_client().delete(
            f"/trade/v2/orders/{order_id}",
            params={"AccountKey": account_key},
        )

    @mcp.tool()
    def modify_order(
        order_id: str,
        account_key: str,
        confirm: bool,
        amount: float | None = None,
        order_price: float | None = None,
    ) -> dict:
        """WRITE OPERATION — modifies a working order's amount and/or price.
        `confirm` must be True. At least one of amount/order_price must be set.
        """
        if not confirm:
            return {"error": "confirm=True required."}
        if amount is None and order_price is None:
            return {"error": "Provide at least one of amount or order_price."}
        body: dict = {"OrderId": order_id, "AccountKey": account_key}
        if amount is not None:
            body["Amount"] = amount
        if order_price is not None:
            body["OrderPrice"] = order_price
        return get_client().patch("/trade/v2/orders", json=body)
