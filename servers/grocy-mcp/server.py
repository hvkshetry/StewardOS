"""MCP server for Grocy pantry inventory and chore tracking."""

import os

import httpx
from mcp.server.fastmcp import FastMCP

GROCY_URL = os.environ.get("GROCY_URL", "http://localhost:9283")
GROCY_API_KEY = os.environ.get("GROCY_API_KEY", "")

mcp = FastMCP(
    "grocy-mcp",
    instructions=(
        "Grocy pantry inventory and household management server. Provides tools to "
        "track pantry stock levels, manage shopping lists based on actual inventory, "
        "and track household chores. Source of truth for 'what do we have' and "
        "'what's running low'. Mealie owns recipes/meal-plans; Grocy owns pantry stock."
    ),
)


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "GROCY-API-KEY": GROCY_API_KEY,
    }


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=GROCY_URL,
        headers=_headers(),
        timeout=30.0,
    )


async def _request(method: str, path: str, **kwargs) -> dict | list | str:
    """Execute an HTTP request against the Grocy API."""
    try:
        async with _client() as client:
            resp = await client.request(method, path, **kwargs)
            resp.raise_for_status()
            if resp.status_code == 204:
                return {"status": "success"}
            return resp.json()
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.RequestError as exc:
        return f"Request failed: {exc}"


@mcp.tool()
async def get_stock_overview() -> dict | list | str:
    """Get overview of all products currently in stock with quantities and locations."""
    return await _request("GET", "/api/stock")


@mcp.tool()
async def get_stock_item(product_id: int) -> dict | list | str:
    """Get detailed stock info for a specific product by its ID."""
    return await _request("GET", f"/api/stock/products/{product_id}")


@mcp.tool()
async def get_missing_products() -> dict | list | str:
    """Get products that are below their minimum stock amount (need restocking)."""
    return await _request("GET", "/api/stock/volatile", params={"due_soon_days": 5})


@mcp.tool()
async def add_product_to_stock(
    product_id: int,
    amount: float,
    best_before_date: str = "",
    location_id: int | None = None,
) -> dict | str:
    """Add stock for a product. best_before_date format: YYYY-MM-DD (empty = no expiry)."""
    payload: dict = {
        "amount": amount,
        "best_before_date": best_before_date or "2999-12-31",
    }
    if location_id is not None:
        payload["location_id"] = location_id
    return await _request(
        "POST",
        f"/api/stock/products/{product_id}/add",
        json=payload,
    )


@mcp.tool()
async def consume_product(
    product_id: int,
    amount: float,
    spoiled: bool = False,
) -> dict | str:
    """Consume (remove from stock) a given amount of a product. Set spoiled=True if wasted."""
    return await _request(
        "POST",
        f"/api/stock/products/{product_id}/consume",
        json={"amount": amount, "spoiled": spoiled},
    )


@mcp.tool()
async def get_shopping_list(list_id: int = 1) -> dict | list | str:
    """Get shopping list items. Default list_id=1 is the main shopping list."""
    items = await _request("GET", "/api/objects/shopping_list")
    if isinstance(items, list):
        return [i for i in items if i.get("shopping_list_id") == list_id]
    return items


@mcp.tool()
async def get_chores() -> dict | list | str:
    """Get all household chores with their next execution dates."""
    return await _request("GET", "/api/chores")


@mcp.tool()
async def complete_chore(chore_id: int) -> dict | str:
    """Mark a chore as completed (tracks execution timestamp)."""
    return await _request(
        "POST",
        f"/api/chores/{chore_id}/execute",
        json={},
    )


@mcp.tool()
async def get_product_by_barcode(barcode: str) -> dict | list | str:
    """Look up a product by its barcode.

    Args:
        barcode: Product barcode (EAN, UPC, etc.)
    """
    return await _request("GET", f"/api/stock/products/by-barcode/{barcode}")


@mcp.tool()
async def add_by_barcode(
    barcode: str,
    amount: float,
    best_before_date: str = "",
) -> dict | str:
    """Add stock for a product identified by barcode.

    Args:
        barcode: Product barcode
        amount: Quantity to add
        best_before_date: Expiry date YYYY-MM-DD (empty = no expiry)
    """
    return await _request(
        "POST",
        f"/api/stock/products/by-barcode/{barcode}/add",
        json={
            "amount": amount,
            "best_before_date": best_before_date or "2999-12-31",
        },
    )


@mcp.tool()
async def inventory_product(
    product_id: int,
    new_amount: float,
    best_before_date: str = "",
) -> dict | str:
    """Set the exact stock amount for a product (inventory correction).

    Args:
        product_id: Product ID
        new_amount: The corrected total quantity in stock
        best_before_date: Expiry date YYYY-MM-DD (empty = no expiry)
    """
    return await _request(
        "POST",
        f"/api/stock/products/{product_id}/inventory",
        json={
            "new_amount": new_amount,
            "best_before_date": best_before_date or "2999-12-31",
        },
    )


@mcp.tool()
async def add_missing_to_shopping_list(list_id: int = 1) -> dict | str:
    """Add all products below their minimum stock to the shopping list.

    Args:
        list_id: Shopping list ID (default 1 = main list)
    """
    return await _request(
        "POST",
        "/api/stock/shoppinglist/add-missing-products",
        json={"list_id": list_id},
    )


@mcp.tool()
async def get_expiring_products(due_soon_days: int = 5) -> dict | list | str:
    """Get products expiring within the specified number of days.

    Args:
        due_soon_days: Number of days to look ahead (default 5)
    """
    result = await _request(
        "GET",
        "/api/stock/volatile",
        params={"due_soon_days": due_soon_days},
    )
    if isinstance(result, dict):
        return result.get("due_products", result)
    return result


@mcp.tool()
async def list_locations() -> dict | list | str:
    """List all storage locations (pantry, fridge, freezer, etc.)."""
    return await _request("GET", "/api/objects/locations")


@mcp.tool()
async def open_product(product_id: int, amount: float = 1) -> dict | str:
    """Mark a product unit as opened (tracks opened vs unopened stock).

    Args:
        product_id: Product ID
        amount: Number of units to mark as opened (default 1)
    """
    return await _request(
        "POST",
        f"/api/stock/products/{product_id}/open",
        json={"amount": amount},
    )


@mcp.tool()
async def transfer_product(
    product_id: int,
    amount: float,
    location_from: int,
    location_to: int,
) -> dict | str:
    """Move product stock from one location to another.

    Args:
        product_id: Product ID
        amount: Quantity to transfer
        location_from: Source location ID
        location_to: Destination location ID
    """
    return await _request(
        "POST",
        f"/api/stock/products/{product_id}/transfer",
        json={
            "amount": amount,
            "location_id_from": location_from,
            "location_id_to": location_to,
        },
    )


if __name__ == "__main__":
    mcp.run()
