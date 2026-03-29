"""Plane PM MCP Server."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from plane import PlaneClient
from tools.coordination import register_coordination_tools
from tools.project_admin import register_project_admin_tools
from tools.work_item import register_work_item_tools
from tools.workspace import register_workspace_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("plane-mcp")

PLANE_BASE_URL = os.environ.get("PLANE_BASE_URL", "http://localhost:8082")
PLANE_API_TOKEN = os.environ.get("PLANE_API_TOKEN", "")

_client: PlaneClient | None = None


def _build_client() -> PlaneClient:
    return PlaneClient(api_key=PLANE_API_TOKEN, base_url=PLANE_BASE_URL)


def get_client() -> PlaneClient:
    global _client
    if _client is None:
        _client = _build_client()
    return _client


@asynccontextmanager
async def lifespan(_: FastMCP):
    global _client
    _client = _build_client()
    logger.info("Plane client initialized (base_url=%s)", PLANE_BASE_URL)
    try:
        yield
    finally:
        _client = None
        logger.info("Plane client released")


mcp = FastMCP(
    "plane-pm",
    instructions=(
        "Plane project-management MCP server with a canonical four-tool surface. "
        "Use `workspace` for workspace/project/member discovery, `work_item` for "
        "work-item CRUD/history/relations/external identity, `coordination` for "
        "routing/claiming/handoffs/approval/delegation, and `project_admin` for "
        "projects plus states, labels, views, pages, cycles, modules, and estimates. "
        "All write operations are audit-logged with workspace attribution."
    ),
    lifespan=lifespan,
)

register_workspace_tools(mcp, get_client)
register_work_item_tools(mcp, get_client)
register_coordination_tools(mcp, get_client)
register_project_admin_tools(mcp, get_client)

if __name__ == "__main__":
    mcp.run()
