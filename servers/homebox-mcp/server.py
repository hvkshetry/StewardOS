"""MCP server for Homebox home inventory management."""

import os

import httpx
from mcp.server.fastmcp import FastMCP

HOMEBOX_URL = os.environ.get("HOMEBOX_URL", "http://localhost:3100")
HOMEBOX_USERNAME = os.environ.get("HOMEBOX_USERNAME", "")
HOMEBOX_PASSWORD = os.environ.get("HOMEBOX_PASSWORD", "")

_token: str | None = None

mcp = FastMCP(
    "homebox-mcp",
    instructions=(
        "Homebox home inventory management server. Provides tools to track household "
        "items, organize by location and label, manage maintenance logs, and view "
        "inventory statistics. Source of truth for 'what do we own' and 'where is it'."
    ),
)


def _normalize_token(token: str) -> str:
    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


def _client(auth: bool = True) -> httpx.AsyncClient:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if auth and _token:
        headers["Authorization"] = f"Bearer {_normalize_token(_token)}"
    return httpx.AsyncClient(
        base_url=HOMEBOX_URL,
        headers=headers,
        timeout=30.0,
    )


async def _login() -> None:
    """Authenticate with Homebox and cache the Bearer token."""
    global _token
    async with _client(auth=False) as client:
        resp = await client.post(
            "/api/v1/users/login",
            json={"username": HOMEBOX_USERNAME, "password": HOMEBOX_PASSWORD},
        )
        resp.raise_for_status()
        data = resp.json()
        _token = _normalize_token(data.get("token", ""))


async def _request(method: str, path: str, **kwargs) -> dict | list | str:
    """Execute an HTTP request with auto-login and 401 retry."""
    global _token

    if not _token:
        try:
            await _login()
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            return f"Login failed: {exc}"

    try:
        async with _client() as client:
            resp = await client.request(method, path, **kwargs)

            # Retry once on 401 after re-login
            if resp.status_code == 401:
                try:
                    await _login()
                except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                    return f"Re-login failed: {exc}"
                # Rebuild client with fresh token
                async with _client() as retry_client:
                    resp = await retry_client.request(method, path, **kwargs)

            resp.raise_for_status()
            if resp.status_code == 204:
                return {"status": "success"}
            ct = resp.headers.get("content-type", "")
            if "application/json" in ct:
                return resp.json()
            return resp.text
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.RequestError as exc:
        return f"Request failed: {exc}"


# ---------------------------------------------------------------------------
# Items (8 tools)
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_items(
    q: str = "",
    page: int = 1,
    page_size: int = 25,
    labels: list[str] | None = None,
    locations: list[str] | None = None,
    fields: list[str] | None = None,
) -> dict | list | str:
    """Search and list inventory items with optional filters.

    Args:
        q: Free-text search query.
        page: Page number (1-based).
        page_size: Results per page.
        labels: Filter by label IDs.
        locations: Filter by location IDs.
        fields: Filter by custom field values.
    """
    params: dict = {"page": page, "pageSize": page_size}
    if q:
        params["q"] = q
    if labels:
        params["labels[]"] = labels
    if locations:
        params["locations[]"] = locations
    if fields:
        params["fields[]"] = fields
    return await _request("GET", "/api/v1/items", params=params)


@mcp.tool()
async def get_item(item_id: str) -> dict | str:
    """Get full details for a specific inventory item by its UUID."""
    return await _request("GET", f"/api/v1/items/{item_id}")


@mcp.tool()
async def create_item(
    name: str,
    location_id: str,
    description: str = "",
    label_ids: list[str] | None = None,
    quantity: int = 1,
    purchase_price: float = 0.0,
) -> dict | str:
    """Create a new inventory item.

    Args:
        name: Item name.
        location_id: UUID of the location to place the item.
        description: Optional description.
        label_ids: Optional list of label UUIDs to attach.
        quantity: Number of this item (default 1).
        purchase_price: Original purchase price.
    """
    payload: dict = {
        "name": name,
        "description": description,
        "locationId": location_id,
        "quantity": quantity,
        "purchasePrice": purchase_price,
    }
    if label_ids:
        payload["labelIds"] = label_ids
    return await _request("POST", "/api/v1/items", json=payload)


@mcp.tool()
async def update_item(item_id: str, item: dict) -> dict | str:
    """Update an existing item. Pass the full item object with desired changes.

    Args:
        item_id: UUID of the item to update.
        item: Full item object (get it from get_item, modify fields, pass back).
    """
    return await _request("PUT", f"/api/v1/items/{item_id}", json=item)


@mcp.tool()
async def delete_item(item_id: str) -> dict | str:
    """Permanently delete an inventory item by its UUID."""
    return await _request("DELETE", f"/api/v1/items/{item_id}")


@mcp.tool()
async def get_item_path(item_id: str) -> dict | list | str:
    """Get the full location path (breadcrumb) for an item.

    Args:
        item_id: UUID of the item.
    """
    return await _request("GET", f"/api/v1/items/{item_id}/path")


@mcp.tool()
async def import_items_csv(csv_content: str) -> dict | str:
    """Import items from CSV content. The CSV should follow the Homebox import format.

    Args:
        csv_content: Raw CSV text content to import.
    """
    # Multipart upload: send csv_content as a file
    return await _request(
        "POST",
        "/api/v1/items/import",
        content=None,  # clear any json default
        files={"csv": ("import.csv", csv_content.encode(), "text/csv")},
    )


@mcp.tool()
async def export_items_csv() -> str:
    """Export all items as CSV text."""
    result = await _request("GET", "/api/v1/items/export")
    return result


# ---------------------------------------------------------------------------
# Locations (5 tools)
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_locations() -> dict | list | str:
    """List all locations (flat list)."""
    return await _request("GET", "/api/v1/locations")


@mcp.tool()
async def get_location_tree() -> dict | list | str:
    """Get locations as a nested tree structure showing parent-child relationships."""
    return await _request("GET", "/api/v1/locations/tree")


@mcp.tool()
async def create_location(
    name: str,
    description: str = "",
    parent_id: str | None = None,
) -> dict | str:
    """Create a new location.

    Args:
        name: Location name (e.g. 'Kitchen Cabinet 3').
        description: Optional description.
        parent_id: UUID of parent location for nesting (optional).
    """
    payload: dict = {"name": name, "description": description}
    if parent_id:
        payload["parentId"] = parent_id
    return await _request("POST", "/api/v1/locations", json=payload)


@mcp.tool()
async def update_location(
    location_id: str,
    name: str,
    description: str = "",
    parent_id: str | None = None,
) -> dict | str:
    """Update an existing location.

    Args:
        location_id: UUID of the location to update.
        name: New name.
        description: New description.
        parent_id: UUID of new parent location (or None for top-level).
    """
    payload: dict = {"name": name, "description": description}
    if parent_id:
        payload["parentId"] = parent_id
    return await _request("PUT", f"/api/v1/locations/{location_id}", json=payload)


@mcp.tool()
async def delete_location(location_id: str) -> dict | str:
    """Delete a location by its UUID. Items in this location should be moved first."""
    return await _request("DELETE", f"/api/v1/locations/{location_id}")


# ---------------------------------------------------------------------------
# Tags (4 tools)
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_tags() -> dict | list | str:
    """List all tags (labels) available for categorizing items."""
    return await _request("GET", "/api/v1/tags")


@mcp.tool()
async def create_tag(name: str) -> dict | str:
    """Create a new tag.

    Args:
        name: Tag name (e.g. 'Electronics', 'Warranty Active').
    """
    return await _request("POST", "/api/v1/tags", json={"name": name})


@mcp.tool()
async def update_tag(tag_id: str, name: str) -> dict | str:
    """Rename an existing tag.

    Args:
        tag_id: UUID of the tag to update.
        name: New tag name.
    """
    return await _request("PUT", f"/api/v1/tags/{tag_id}", json={"name": name})


@mcp.tool()
async def delete_tag(tag_id: str) -> dict | str:
    """Delete a tag by its UUID."""
    return await _request("DELETE", f"/api/v1/tags/{tag_id}")


# ---------------------------------------------------------------------------
# Maintenance (3 tools)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_item_maintenance(item_id: str) -> dict | list | str:
    """Get maintenance log entries for a specific item.

    Args:
        item_id: UUID of the item.
    """
    return await _request("GET", f"/api/v1/items/{item_id}/maintenance")


@mcp.tool()
async def add_maintenance_entry(
    item_id: str,
    name: str,
    description: str = "",
    date: str = "",
    cost: float = 0.0,
) -> dict | str:
    """Add a maintenance entry for an item.

    Args:
        item_id: UUID of the item.
        name: Maintenance task name (e.g. 'Filter replacement').
        description: Optional details.
        date: Date of maintenance in YYYY-MM-DD format (default: today).
        cost: Cost of the maintenance.
    """
    from datetime import date as date_cls

    payload: dict = {
        "name": name,
        "description": description,
        "date": date if date else date_cls.today().isoformat(),
        "cost": cost,
    }
    return await _request("POST", f"/api/v1/items/{item_id}/maintenance", json=payload)


@mcp.tool()
async def list_all_maintenance() -> dict | list | str:
    """List all maintenance entries across all items."""
    return await _request("GET", "/api/v1/maintenance")


# ---------------------------------------------------------------------------
# Statistics (4 tools)
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_group_statistics() -> dict | str:
    """Get overall group statistics (total items, total value, etc.)."""
    return await _request("GET", "/api/v1/groups/statistics")


@mcp.tool()
async def get_purchase_price_stats() -> dict | list | str:
    """Get purchase price statistics over time."""
    return await _request("GET", "/api/v1/groups/statistics/purchase-price")


@mcp.tool()
async def get_stats_by_location() -> dict | list | str:
    """Get item count and value statistics grouped by location."""
    return await _request("GET", "/api/v1/groups/statistics/locations")


@mcp.tool()
async def get_stats_by_tag() -> dict | list | str:
    """Get item count and value statistics grouped by tag."""
    return await _request("GET", "/api/v1/groups/statistics/tags")


# ---------------------------------------------------------------------------
# Assets (1 tool)
# ---------------------------------------------------------------------------


@mcp.tool()
async def lookup_asset(asset_id: str) -> dict | str:
    """Look up an item by its asset ID (the short human-readable asset tag).

    Args:
        asset_id: The asset tag ID (e.g. '000-001').
    """
    return await _request("GET", f"/api/v1/assets/{asset_id}")


if __name__ == "__main__":
    mcp.run()
