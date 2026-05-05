"""Read-only MCP tools for Saxo OpenAPI. Always registered."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .client import get_client


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_user_info() -> dict:
        """Get the authenticated Saxo user's profile (name, language, client key)."""
        return get_client().get("/port/v1/users/me")

    @mcp.tool()
    def get_accounts() -> dict:
        """List accounts accessible to the authenticated user.

        The returned AccountKey values are required by most other tools
        (e.g. get_balances, place_order).
        """
        return get_client().get("/port/v1/accounts/me")

    @mcp.tool()
    def get_balances() -> dict:
        """Get cash balance, margin, and P&L for the user's default account."""
        return get_client().get("/port/v1/balances/me")

    @mcp.tool()
    def get_positions() -> dict:
        """List open positions for the user."""
        return get_client().get("/port/v1/positions/me")

    @mcp.tool()
    def get_orders() -> dict:
        """List open (working) orders for the user."""
        return get_client().get("/port/v1/orders/me")

    @mcp.tool()
    def get_closed_positions() -> dict:
        """List historical / closed positions for the user."""
        return get_client().get("/port/v1/closedpositions/me")

    @mcp.tool()
    def search_instruments(
        keywords: str,
        asset_types: str | None = None,
        limit: int = 20,
    ) -> dict:
        """Search Saxo's instrument catalog.

        Args:
            keywords: search text, e.g. "AAPL", "EURUSD", "Tesla"
            asset_types: optional comma-separated AssetType filter,
                e.g. "FxSpot,Stock,CfdOnStock"
            limit: max results (default 20)

        Returns:
            JSON containing a Data[] list of instruments, each with Uic,
            AssetType, Description, Symbol — needed for price/trade calls.
        """
        params: dict = {"Keywords": keywords, "$top": limit}
        if asset_types:
            params["AssetTypes"] = asset_types
        return get_client().get("/ref/v1/instruments", params=params)

    @mcp.tool()
    def get_instrument_details(uic: int, asset_type: str) -> dict:
        """Get full details for a specific instrument.

        Args:
            uic: instrument UIC (from search_instruments)
            asset_type: e.g. "Stock", "FxSpot", "CfdOnStock"
        """
        return get_client().get(f"/ref/v1/instruments/details/{uic}/{asset_type}")

    @mcp.tool()
    def get_info_price(uic: int, asset_type: str) -> dict:
        """Get the current info price (bid/ask/last) for an instrument."""
        return get_client().get(
            "/trade/v1/infoprices",
            params={"Uic": uic, "AssetType": asset_type},
        )

    @mcp.tool()
    def get_price_history(
        uic: int,
        asset_type: str,
        horizon: int = 60,
        count: int = 100,
    ) -> dict:
        """Get historical OHLC bars for an instrument.

        Args:
            uic: instrument UIC
            asset_type: e.g. "Stock", "FxSpot"
            horizon: bar size in minutes — typical: 1, 5, 15, 60, 1440
            count: number of bars to return (max ~1200)
        """
        return get_client().get(
            "/chart/v1/charts",
            params={
                "Uic": uic,
                "AssetType": asset_type,
                "Horizon": horizon,
                "Count": count,
            },
        )
