"""Saved view management tools for Plane.

Views are reusable saved filters that agents and humans use for
dashboards and recurring queries against work items.
All operations use direct HTTP — the plane-sdk does not cover views.
"""

from __future__ import annotations

import logging
from typing import Any

from tools._helpers import audit_log, extract, home_workspace, normalize_list
from tools._http import api_delete, api_get, api_patch, api_post

logger = logging.getLogger("plane-mcp.views")


def _view_path(workspace_slug: str, project_id: str, view_id: str = "") -> str:
    base = f"/workspaces/{workspace_slug}/projects/{project_id}/views/"
    if view_id:
        return f"{base}{view_id}/"
    return base


def register_view_tools(mcp, get_client):
    @mcp.tool()
    async def list_views(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """List all saved views in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        raw = await api_get(_view_path(workspace_slug, project_id))
        items = normalize_list(raw)
        results = []
        for v in items:
            results.append({
                "id": extract(v, "id"),
                "name": extract(v, "name"),
                "description": extract(v, "description"),
                "query_data": extract(v, "query_data"),
                "access": extract(v, "access"),
                "created_at": extract(v, "created_at"),
                "updated_at": extract(v, "updated_at"),
            })

        logger.info(
            "list_views: workspace=%s project=%s found %d views",
            workspace_slug,
            project_id,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def create_view(
        workspace_slug: str,
        project_id: str,
        name: str,
        description: str = "",
        query_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new saved view (filter) in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            name: View name.
            description: View description.
            query_data: Filter query data (state, priority, label, assignee filters).
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create view in workspace '{workspace_slug}' — "
                    f"views must be created in home workspace '{home}'."
                ),
            }

        audit_log("create_view", workspace_slug, {
            "project_id": project_id,
            "name": name,
        })

        post_data: dict[str, Any] = {"name": name}
        if description:
            post_data["description"] = description
        if query_data:
            post_data["query_data"] = query_data

        result = await api_post(
            _view_path(workspace_slug, project_id),
            post_data,
        )

        view_id = extract(result, "id")
        logger.info(
            "create_view: created view=%s in project=%s",
            view_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": view_id,
                "name": name,
                "description": description,
            },
        }

    @mcp.tool()
    async def get_view(
        workspace_slug: str,
        project_id: str,
        view_id: str,
    ) -> dict[str, Any]:
        """Retrieve a saved view with its filter configuration.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            view_id: The view UUID.
        """
        raw = await api_get(
            _view_path(workspace_slug, project_id, view_id),
        )

        data = {
            "id": extract(raw, "id"),
            "name": extract(raw, "name"),
            "description": extract(raw, "description"),
            "query_data": extract(raw, "query_data"),
            "display_filters": extract(raw, "display_filters"),
            "display_properties": extract(raw, "display_properties"),
            "access": extract(raw, "access"),
            "is_locked": extract(raw, "is_locked", False),
            "created_at": extract(raw, "created_at"),
            "updated_at": extract(raw, "updated_at"),
        }

        logger.info(
            "get_view: workspace=%s project=%s view=%s",
            workspace_slug,
            project_id,
            view_id,
        )
        return {"ok": True, "data": data}

    @mcp.tool()
    async def update_view(
        workspace_slug: str,
        project_id: str,
        view_id: str,
        name: str = "",
        description: str = "",
        query_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update a saved view's name, description, or filters.

        At least one of name, description, or query_data must be provided.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            view_id: The view UUID.
            name: New view name.
            description: New view description.
            query_data: New filter query data.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot update view in workspace '{workspace_slug}' — "
                    f"views must be updated in home workspace '{home}'."
                ),
            }

        audit_log("update_view", workspace_slug, {
            "project_id": project_id,
            "view_id": view_id,
        })

        patch_data: dict[str, Any] = {}
        if name:
            patch_data["name"] = name
        if description:
            patch_data["description"] = description
        if query_data:
            patch_data["query_data"] = query_data

        if not patch_data:
            return {
                "ok": False,
                "error": "At least one of name, description, or query_data must be provided.",
            }

        result = await api_patch(
            _view_path(workspace_slug, project_id, view_id),
            patch_data,
        )

        logger.info(
            "update_view: updated view=%s in project=%s",
            view_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": extract(result, "id", view_id),
                "name": extract(result, "name"),
                "updated_at": extract(result, "updated_at"),
            },
        }

    @mcp.tool()
    async def delete_view(
        workspace_slug: str,
        project_id: str,
        view_id: str,
    ) -> dict[str, Any]:
        """Delete a saved view from a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            view_id: The view UUID to delete.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot delete view in workspace '{workspace_slug}' — "
                    f"views must be deleted in home workspace '{home}'."
                ),
            }

        audit_log("delete_view", workspace_slug, {
            "project_id": project_id,
            "view_id": view_id,
        })

        await api_delete(
            _view_path(workspace_slug, project_id, view_id),
        )

        logger.info(
            "delete_view: deleted view=%s from project=%s",
            view_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": view_id,
                "status": "deleted",
            },
        }
