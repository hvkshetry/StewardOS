import os

import asyncpg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from stewardos_lib.db import create_server_pool

from people import register_people_tools
from entities import register_entities_tools
from assets import register_assets_tools
from ownership import register_ownership_tools
from documents import register_documents_tools
from compliance import register_compliance_tools
from cross_cutting import register_cross_cutting_tools

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://estate:changeme@localhost:5434/estate_planning"
)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await create_server_pool(
            DATABASE_URL,
            schema="estate",
            min_size=1,
            max_size=5,
        )
    return _pool


mcp = FastMCP(
    "estate-planning",
    instructions=(
        "Estate planning graph for people, legal entities, ownership paths, "
        "documents, and critical dates across jurisdictions."
    ),
)

register_people_tools(mcp, get_pool)
register_entities_tools(mcp, get_pool)
register_assets_tools(mcp, get_pool)
register_ownership_tools(mcp, get_pool)
register_documents_tools(mcp, get_pool)
register_compliance_tools(mcp, get_pool)
register_cross_cutting_tools(mcp, get_pool)

if __name__ == "__main__":
    mcp.run()
