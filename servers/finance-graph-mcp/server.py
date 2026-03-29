"""Finance Graph MCP Server.

Provides tools for managing illiquid assets, valuations, statement facts,
ownership interests, and long-term liabilities (mortgage/HELOC/debt).
"""

import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from stewardos_lib.db import create_server_pool
from stewardos_lib.migrations import ensure_migrations

from people import register_people_tools
from entities import register_entities_tools
from assets import register_assets_tools
from ownership import register_ownership_tools
from valuations import register_valuations_tools
from liabilities import register_liabilities_tools
from ips_targets import register_ips_targets_tools
from cross_cutting import register_cross_cutting_tools

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://finance:changeme@localhost:5434/stewardos_db"
)
AUTO_APPLY_MIGRATIONS = os.environ.get("FINANCE_GRAPH_AUTO_APPLY_MIGRATIONS", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
MIGRATIONS_DIR = Path(__file__).with_name("migrations")

_pool: asyncpg.Pool | None = None
_init_lock = asyncio.Lock()
_initialized = False


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await create_server_pool(
            DATABASE_URL,
            schema="finance",
            min_size=1,
            max_size=5,
        )
    return _pool


async def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    async with _init_lock:
        if _initialized:
            return
        pool = await _get_pool()
        async with pool.acquire() as conn:
            await ensure_migrations(
                conn,
                migrations_dir=MIGRATIONS_DIR,
                auto_apply=AUTO_APPLY_MIGRATIONS,
                migration_table="finance.schema_migrations",
            )
        _initialized = True


async def _close_pool() -> None:
    global _pool, _initialized
    pool = _pool
    _pool = None
    _initialized = False
    if pool is not None:
        await pool.close()


async def get_pool() -> asyncpg.Pool:
    await _ensure_initialized()
    return await _get_pool()


@asynccontextmanager
async def lifespan(_: FastMCP):
    await _ensure_initialized()
    try:
        yield
    finally:
        await _close_pool()


mcp = FastMCP(
    "finance-graph",
    instructions=(
        "Finance graph for illiquid assets, valuations, ownership interests, "
        "PL/CFS/BS facts, and long-term liabilities including refinance analytics."
    ),
    lifespan=lifespan,
)

register_people_tools(mcp, get_pool)
register_entities_tools(mcp, get_pool)
register_assets_tools(mcp, get_pool)
register_ownership_tools(mcp, get_pool)
register_valuations_tools(mcp, get_pool)
register_liabilities_tools(mcp, get_pool)
register_ips_targets_tools(mcp, get_pool)
register_cross_cutting_tools(mcp, get_pool)

if __name__ == "__main__":
    mcp.run()
