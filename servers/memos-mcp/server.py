"""MCP server for Memos note-taking and journaling (REST API v1, gRPC-Gateway)."""

import os

import httpx
from mcp.server.fastmcp import FastMCP

MEMOS_URL = os.environ.get("MEMOS_URL", "http://localhost:5230")
MEMOS_TOKEN = os.environ.get("MEMOS_TOKEN", "")

mcp = FastMCP(
    "memos-mcp",
    instructions=(
        "Memos note-taking and journaling server. Provides tools to create, read, update, "
        "delete, and search memos, manage comments, relations, reactions, attachments, "
        "and retrieve user stats via the Memos REST API v1."
    ),
)


def _ok_response(payload):
    return {"status": "ok", "errors": [], "data": payload}


def _error_response(message: str, *, code: str) -> dict:
    return {"status": "error", "errors": [{"code": code, "message": message}], "data": None}


def _headers() -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if MEMOS_TOKEN:
        headers["Authorization"] = f"Bearer {MEMOS_TOKEN}"
    return headers


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=MEMOS_URL,
        headers=_headers(),
        timeout=30.0,
    )


async def _request(method: str, path: str, **kwargs) -> dict:
    """Execute an HTTP request against the Memos API."""
    try:
        async with _client() as client:
            resp = await client.request(method, path, **kwargs)
            resp.raise_for_status()
            if resp.status_code == 204:
                return _ok_response({"status": "success"})
            try:
                return _ok_response(resp.json())
            except ValueError:
                return _ok_response(resp.text)
    except httpx.HTTPStatusError as exc:
        return _error_response(
            f"HTTP {exc.response.status_code}: {exc.response.text}",
            code="http_error",
        )
    except httpx.RequestError as exc:
        return _error_response(f"Request failed: {exc}", code="request_error")


# ---------------------------------------------------------------------------
# Memo CRUD
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_memos(
    page_size: int = 20,
    page_token: str = "",
    filter: str = "",
) -> dict:
    """List memos with optional pagination and filtering.

    Args:
        page_size: Number of memos to return per page (default 20).
        page_token: Token for the next page (from a previous response).
        filter: CEL filter expression, e.g. 'visibility == "PUBLIC"'.
    """
    params: dict = {"pageSize": page_size}
    if page_token:
        params["pageToken"] = page_token
    if filter:
        params["filter"] = filter
    return await _request("GET", "/api/v1/memos", params=params)


@mcp.tool()
async def get_memo(id: int) -> dict:
    """Get a single memo by its numeric ID.

    Args:
        id: The memo ID.
    """
    return await _request("GET", f"/api/v1/memos/{id}")


@mcp.tool()
async def create_memo(
    content: str,
    visibility: str = "PRIVATE",
) -> dict:
    """Create a new memo.

    Args:
        content: Markdown content of the memo.
        visibility: One of PRIVATE, PROTECTED, or PUBLIC (default PRIVATE).
    """
    return await _request(
        "POST",
        "/api/v1/memos",
        json={"content": content, "visibility": visibility},
    )


@mcp.tool()
async def update_memo(
    id: int,
    content: str | None = None,
    visibility: str | None = None,
) -> dict:
    """Update an existing memo's content and/or visibility.

    Args:
        id: The memo ID.
        content: New markdown content (omit to leave unchanged).
        visibility: New visibility - PRIVATE, PROTECTED, or PUBLIC (omit to leave unchanged).
    """
    body: dict = {}
    update_masks: list[str] = []
    if content is not None:
        body["content"] = content
        update_masks.append("content")
    if visibility is not None:
        body["visibility"] = visibility
        update_masks.append("visibility")
    if not update_masks:
        return _error_response(
            "Nothing to update. Provide content and/or visibility.",
            code="validation_error",
        )
    return await _request(
        "PATCH",
        f"/api/v1/memos/{id}",
        params={"updateMask": ",".join(update_masks)},
        json=body,
    )


@mcp.tool()
async def delete_memo(id: int) -> dict:
    """Delete a memo by its numeric ID.

    Args:
        id: The memo ID.
    """
    return await _request("DELETE", f"/api/v1/memos/{id}")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@mcp.tool()
async def search_memos(
    query: str,
    page_size: int = 20,
    page_token: str = "",
) -> dict:
    """Search memos by keyword. Wraps the query into a CEL content.contains() filter.

    Args:
        query: Search keyword to find in memo content.
        page_size: Number of results per page (default 20).
        page_token: Token for the next page.
    """
    # Escape double-quotes inside the query for CEL string literal safety
    safe_query = query.replace("\\", "\\\\").replace('"', '\\"')
    cel_filter = f'content.contains("{safe_query}")'
    params: dict = {"pageSize": page_size, "filter": cel_filter}
    if page_token:
        params["pageToken"] = page_token
    return await _request("GET", "/api/v1/memos", params=params)


# ---------------------------------------------------------------------------
# Comments
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_memo_comments(id: int) -> dict:
    """List all comments on a memo.

    Args:
        id: The parent memo ID.
    """
    return await _request("GET", f"/api/v1/memos/{id}/comments")


@mcp.tool()
async def create_memo_comment(id: int, content: str) -> dict:
    """Add a comment to a memo.

    Args:
        id: The parent memo ID.
        content: Markdown content of the comment.
    """
    return await _request(
        "POST",
        f"/api/v1/memos/{id}/comments",
        json={"content": content},
    )


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_memo_relations(id: int) -> dict:
    """List all relations of a memo.

    Args:
        id: The memo ID.
    """
    return await _request("GET", f"/api/v1/memos/{id}/relations")


@mcp.tool()
async def set_memo_relations(id: int, relations: list[dict]) -> dict:
    """Set relations for a memo, replacing existing relations.

    Args:
        id: The memo ID.
        relations: List of relation objects, each with 'relatedMemoId' (int)
                   and 'type' (e.g. 'REFERENCE' or 'COMMENT').
    """
    return await _request(
        "PATCH",
        f"/api/v1/memos/{id}/relations",
        json={"relations": relations},
    )


# ---------------------------------------------------------------------------
# Reactions
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_memo_reactions(id: int) -> dict:
    """List all reactions on a memo.

    Args:
        id: The memo ID.
    """
    return await _request("GET", f"/api/v1/memos/{id}/reactions")


@mcp.tool()
async def upsert_reaction(id: int, reaction_type: str) -> dict:
    """Add or update a reaction on a memo.

    Args:
        id: The memo ID.
        reaction_type: Reaction type string, e.g. 'THUMBS_UP', 'HEART', 'LAUGH'.
    """
    return await _request(
        "POST",
        f"/api/v1/memos/{id}/reactions",
        json={"reactionType": reaction_type},
    )


# ---------------------------------------------------------------------------
# Attachments (resources)
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_attachments() -> dict:
    """List all attachments (resources) in the Memos instance."""
    return await _request("GET", "/api/v1/attachments")


@mcp.tool()
async def upload_attachment(file_path: str) -> dict:
    """Upload a file as an attachment to Memos.

    Args:
        file_path: Absolute path to the file to upload.
    """
    import mimetypes

    filename = os.path.basename(file_path)
    mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    try:
        async with _client() as client:
            with open(file_path, "rb") as f:
                resp = await client.post(
                    "/api/v1/attachments",
                    files={"file": (filename, f, mime_type)},
                )
                resp.raise_for_status()
                return _ok_response(resp.json())
    except FileNotFoundError:
        return _error_response(f"File not found: {file_path}", code="file_not_found")
    except httpx.HTTPStatusError as exc:
        return _error_response(
            f"HTTP {exc.response.status_code}: {exc.response.text}",
            code="http_error",
        )
    except httpx.RequestError as exc:
        return _error_response(f"Request failed: {exc}", code="request_error")


@mcp.tool()
async def delete_attachment(id: int) -> dict:
    """Delete an attachment by its numeric ID.

    Args:
        id: The attachment ID.
    """
    return await _request("DELETE", f"/api/v1/attachments/{id}")


# ---------------------------------------------------------------------------
# Users & instance
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_user_stats(id: str = "me") -> dict:
    """Get memo statistics for a user.

    Args:
        id: User ID or 'me' for the current authenticated user (default 'me').
    """
    return await _request("GET", f"/api/v1/users/{id}:getStats")


@mcp.tool()
async def get_instance_profile() -> dict:
    """Get the Memos instance profile (version, mode, etc.)."""
    return await _request("GET", "/api/v1/instance/profile")


@mcp.tool()
async def list_users() -> dict:
    """List all users on the Memos instance."""
    return await _request("GET", "/api/v1/users")


if __name__ == "__main__":
    mcp.run()
