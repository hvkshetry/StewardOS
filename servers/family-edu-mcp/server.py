"""MCP server for learner records and development control-plane operations."""

import asyncio
from contextlib import asynccontextmanager
import os

import asyncpg
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from stewardos_lib.migrations import ensure_migrations

from learners import register_learner_tools
from artifacts import register_artifact_tools
from assessments import register_assessment_tools
from metrics import register_metric_tools
from goals import register_goal_tools
from briefs import register_brief_tools
from planning import register_planning_tools

load_dotenv()

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://family_edu:changeme@localhost:5434/stewardos_db"
)
AUTO_APPLY_MIGRATIONS = os.environ.get("FAMILY_EDU_AUTO_APPLY_MIGRATIONS", "").strip().lower() in {
    "1",
    "true",
    "yes",
}
MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "migrations")

_pool: asyncpg.Pool | None = None
_init_lock = asyncio.Lock()
_initialized = False


async def _get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=8,
            server_settings={"search_path": "family_edu,public"},
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
                migration_table="family_edu.schema_migrations",
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
    """Public pool accessor that ensures schema initialization on first call."""
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
    "family-edu-mcp",
    instructions=(
        "Learner records and development control-plane server. Tracks learner identity, "
        "enrollments, linked evidence artifacts, assessments, metric observations, goals, "
        "and structured weekly planning."
    ),
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Register domain tool modules
# ---------------------------------------------------------------------------
register_learner_tools(mcp, get_pool)
register_artifact_tools(mcp, get_pool)
register_assessment_tools(mcp, get_pool)
register_metric_tools(mcp, get_pool)
register_goal_tools(mcp, get_pool)
register_brief_tools(mcp, get_pool)
register_planning_tools(mcp, get_pool)

if __name__ == "__main__":
    mcp.run()
