"""Plane PM MCP Server.

Governance-safe MCP wrapper around the Plane project management API.
Provides tools for work-item discovery, creation, execution, project
management, cycles, modules, pages, coordination, state/label
management, saved views, and estimate scales with audit logging and
cross-domain governance controls.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from mcp.server.fastmcp import FastMCP
from plane import PlaneClient
from tools.coordination import register_coordination_tools
from tools.creation import register_creation_tools
from tools.cycles import register_cycle_tools
from tools.discovery import register_discovery_tools
from tools.estimates import register_estimate_tools
from tools.execution import register_execution_tools
from tools.management import register_management_tools
from tools.modules import register_module_tools
from tools.pages import register_page_tools
from tools.projects import register_project_tools
from tools.relations import register_relation_tools
from tools.views import register_view_tools

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
        "Plane project-management MCP server. Provides governance-safe tools "
        "for work-item discovery, case/task creation with structured labels, "
        "execution state transitions, project management, cycle/module "
        "timeboxing, per-project pages, member/intake coordination, "
        "state/label lifecycle management, saved views, estimate scales, "
        "and work-item relation/dependency graphs. "
        "All write operations are audit-logged with workspace attribution."
    ),
    lifespan=lifespan,
)

register_discovery_tools(mcp, get_client)
register_creation_tools(mcp, get_client)
register_execution_tools(mcp, get_client)
register_project_tools(mcp, get_client)
register_cycle_tools(mcp, get_client)
register_module_tools(mcp, get_client)
register_page_tools(mcp, get_client)
register_coordination_tools(mcp, get_client)
register_management_tools(mcp, get_client)
register_view_tools(mcp, get_client)
register_estimate_tools(mcp, get_client)
register_relation_tools(mcp, get_client)

if __name__ == "__main__":
    mcp.run()
