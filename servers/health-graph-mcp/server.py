"""Health Graph MCP Server.

Assertion-first health graph for genomics, PGx, labs, and insurance coverage intelligence.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from stewardos_lib.db import create_server_pool
from stewardos_lib.migrations import ensure_migrations

load_dotenv()

from subjects import register_subject_tools  # noqa: E402
from genomics import register_genomics_tools  # noqa: E402
from pgx import register_pgx_tools  # noqa: E402
from assertions import register_assertion_tools  # noqa: E402
from fhir import register_fhir_tools  # noqa: E402
from labs import register_lab_tools  # noqa: E402
from coverage import register_coverage_tools  # noqa: E402
from paperless_sync import register_paperless_tools  # noqa: E402
from genome_knowledge import register_genome_knowledge_tools  # noqa: E402
from status import register_status_tools  # noqa: E402

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://health:changeme@localhost:5434/health_graph"
)
AUTO_APPLY_MIGRATIONS = os.environ.get("HEALTH_GRAPH_AUTO_APPLY_MIGRATIONS", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
MIGRATIONS_DIR = Path(__file__).with_name("migrations")

mcp = FastMCP(
    "health-graph-mcp",
    instructions=(
        "Assertion-first health graph server. Stores canonical genomics, PGx, clinical assertions, "
        "lab observations, and coverage determinations with strict evidence-tier policy gating."
    ),
)

_pool: asyncpg.Pool | None = None
_init_lock = asyncio.Lock()
_initialized = False


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await create_server_pool(
            DATABASE_URL,
            schema="health",
            min_size=1,
            max_size=6,
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
                migration_table="health.schema_migrations",
            )
        _initialized = True


register_subject_tools(mcp, _get_pool, _ensure_initialized)
register_genomics_tools(mcp, _get_pool, _ensure_initialized)
register_pgx_tools(mcp, _get_pool, _ensure_initialized)
register_assertion_tools(mcp, _get_pool, _ensure_initialized)
register_fhir_tools(mcp, _get_pool, _ensure_initialized)
register_lab_tools(mcp, _get_pool, _ensure_initialized)
register_coverage_tools(mcp, _get_pool, _ensure_initialized)
register_paperless_tools(mcp, _get_pool, _ensure_initialized)
register_genome_knowledge_tools(mcp, _get_pool, _ensure_initialized)
register_status_tools(mcp, _get_pool, _ensure_initialized)


if __name__ == "__main__":
    mcp.run()
