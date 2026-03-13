"""Shared helper functions for Plane MCP tool modules."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("plane-mcp")

def home_workspace() -> str:
    return os.environ.get("PLANE_HOME_WORKSPACE", "")


def audit_log(
    tool_name: str,
    workspace_slug: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """Log write operation for governance audit trail."""
    home = home_workspace()
    cross_domain = workspace_slug != home if home else False
    msg = "AUDIT %s: workspace=%s home=%s cross_domain=%s"
    args: list[Any] = [tool_name, workspace_slug, home, cross_domain]
    if extra:
        msg += " extra=%s"
        args.append(extra)
    if cross_domain:
        logger.warning(msg, *args)
    else:
        logger.info(msg, *args)


def normalize_list(raw: Any) -> list:
    """Normalize SDK response into a plain list.

    Handles plain lists, dicts with "results" key, and Pydantic
    Paginated*Response objects that carry results in a `.results` attribute.
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "results" in raw:
        return raw["results"]
    if raw is None:
        return []
    # Pydantic Paginated*Response objects from plane-sdk
    results = getattr(raw, "results", None)
    if results is not None and isinstance(results, list):
        return results
    return [raw]


def extract(obj: Any, key: str, default: Any = "") -> Any:
    """Extract a value from a dict or object attribute."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def work_item_to_dict(item: Any) -> dict[str, Any]:
    """Convert a work item (dict or SDK object) to a standard dict."""
    return {
        "id": extract(item, "id"),
        "name": extract(item, "name"),
        "description_html": extract(item, "description_html"),
        "state": extract(item, "state"),
        "priority": extract(item, "priority"),
        "labels": extract(item, "labels", default=[]),
        "parent": extract(item, "parent"),
        "assignees": extract(item, "assignees", default=[]),
        "start_date": extract(item, "start_date"),
        "target_date": extract(item, "target_date"),
        "created_at": extract(item, "created_at"),
        "updated_at": extract(item, "updated_at"),
    }
