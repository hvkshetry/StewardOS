"""Estimate management tools for Plane.

Estimates define effort scales (points, categories, time) used for
capacity planning on work items. All operations use direct HTTP —
the plane-sdk does not cover estimate CRUD.
"""

from __future__ import annotations

import logging
from typing import Any

from tools._helpers import audit_log, extract, home_workspace, normalize_list
from tools._http import api_delete, api_get, api_patch, api_post

logger = logging.getLogger("plane-mcp.estimates")


def _estimate_path(
    workspace_slug: str, project_id: str, estimate_id: str = "",
) -> str:
    base = f"/workspaces/{workspace_slug}/projects/{project_id}/estimates/"
    if estimate_id:
        return f"{base}{estimate_id}/"
    return base


def register_estimate_tools(mcp, get_client):
    @mcp.tool()
    async def list_estimates(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """List all estimate scales in a project.

        Each estimate includes its points (the individual values in the scale).

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        raw = await api_get(_estimate_path(workspace_slug, project_id))
        items = normalize_list(raw)
        results = []
        for e in items:
            points = extract(e, "points", [])
            if not isinstance(points, list):
                points = []
            results.append({
                "id": extract(e, "id"),
                "name": extract(e, "name"),
                "description": extract(e, "description"),
                "type": extract(e, "type"),
                "last_used": extract(e, "last_used", False),
                "points": [
                    {
                        "id": extract(p, "id"),
                        "key": extract(p, "key"),
                        "value": extract(p, "value"),
                    }
                    for p in points
                ],
            })

        logger.info(
            "list_estimates: workspace=%s project=%s found %d estimates",
            workspace_slug,
            project_id,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def create_estimate(
        workspace_slug: str,
        project_id: str,
        name: str,
        estimate_type: str = "categories",
        estimate_points: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a new estimate scale in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            name: Estimate name (e.g. 'Story Points', 'T-Shirt Sizes').
            estimate_type: Scale type (categories, points, time).
            estimate_points: List of point dicts with 'key' (int) and 'value' (str).
                Example: [{"key": 0, "value": "XS"}, {"key": 1, "value": "S"}]
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create estimate in workspace '{workspace_slug}' — "
                    f"estimates must be created in home workspace '{home}'."
                ),
            }

        audit_log("create_estimate", workspace_slug, {
            "project_id": project_id,
            "name": name,
        })

        post_data: dict[str, Any] = {
            "estimate": {
                "name": name,
                "type": estimate_type,
            },
            "estimate_points": estimate_points or [],
        }

        result = await api_post(
            _estimate_path(workspace_slug, project_id),
            post_data,
        )

        estimate_id = extract(result, "id")
        points = extract(result, "points", [])
        if not isinstance(points, list):
            points = []

        logger.info(
            "create_estimate: created estimate=%s in project=%s",
            estimate_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": estimate_id,
                "name": name,
                "type": estimate_type,
                "points_count": len(points),
            },
        }

    @mcp.tool()
    async def get_estimate(
        workspace_slug: str,
        project_id: str,
        estimate_id: str,
    ) -> dict[str, Any]:
        """Retrieve an estimate scale with all its points.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            estimate_id: The estimate UUID.
        """
        raw = await api_get(
            _estimate_path(workspace_slug, project_id, estimate_id),
        )

        points = extract(raw, "points", [])
        if not isinstance(points, list):
            points = []

        data = {
            "id": extract(raw, "id"),
            "name": extract(raw, "name"),
            "description": extract(raw, "description"),
            "type": extract(raw, "type"),
            "last_used": extract(raw, "last_used", False),
            "points": [
                {
                    "id": extract(p, "id"),
                    "key": extract(p, "key"),
                    "value": extract(p, "value"),
                }
                for p in points
            ],
        }

        logger.info(
            "get_estimate: workspace=%s project=%s estimate=%s",
            workspace_slug,
            project_id,
            estimate_id,
        )
        return {"ok": True, "data": data}

    @mcp.tool()
    async def update_estimate(
        workspace_slug: str,
        project_id: str,
        estimate_id: str,
        name: str = "",
        estimate_type: str = "",
        estimate_points: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Update an estimate scale and/or its points.

        At least one of name, estimate_type, or estimate_points must be provided.
        When updating points, include 'id', 'key', and 'value' for each.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            estimate_id: The estimate UUID.
            name: New estimate name.
            estimate_type: New scale type (categories, points, time).
            estimate_points: Updated point dicts with 'id', 'key', and 'value'.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot update estimate in workspace '{workspace_slug}' — "
                    f"estimates must be updated in home workspace '{home}'."
                ),
            }

        audit_log("update_estimate", workspace_slug, {
            "project_id": project_id,
            "estimate_id": estimate_id,
        })

        patch_data: dict[str, Any] = {}
        estimate_fields: dict[str, Any] = {}
        if name:
            estimate_fields["name"] = name
        if estimate_type:
            estimate_fields["type"] = estimate_type
        if estimate_fields:
            patch_data["estimate"] = estimate_fields
        if estimate_points is not None:
            patch_data["estimate_points"] = estimate_points

        if not patch_data:
            return {
                "ok": False,
                "error": "At least one of name, estimate_type, or estimate_points must be provided.",
            }

        result = await api_patch(
            _estimate_path(workspace_slug, project_id, estimate_id),
            patch_data,
        )

        logger.info(
            "update_estimate: updated estimate=%s in project=%s",
            estimate_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": extract(result, "id", estimate_id),
                "name": extract(result, "name"),
                "type": extract(result, "type"),
            },
        }

    @mcp.tool()
    async def delete_estimate(
        workspace_slug: str,
        project_id: str,
        estimate_id: str,
    ) -> dict[str, Any]:
        """Delete an estimate scale from a project.

        Work items using this estimate will have their estimate_point cleared.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            estimate_id: The estimate UUID to delete.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot delete estimate in workspace '{workspace_slug}' — "
                    f"estimates must be deleted in home workspace '{home}'."
                ),
            }

        audit_log("delete_estimate", workspace_slug, {
            "project_id": project_id,
            "estimate_id": estimate_id,
        })

        await api_delete(
            _estimate_path(workspace_slug, project_id, estimate_id),
        )

        logger.info(
            "delete_estimate: deleted estimate=%s from project=%s",
            estimate_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": estimate_id,
                "status": "deleted",
            },
        }
