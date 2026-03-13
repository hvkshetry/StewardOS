"""Module management tools for Plane.

Modules serve as thematic workstreams for grouping related work items
across time boundaries (unlike cycles which are time-boxed).
"""

from __future__ import annotations

import logging
from typing import Any

from plane.models.modules import CreateModule
from tools._helpers import audit_log, extract, home_workspace, normalize_list, work_item_to_dict

logger = logging.getLogger("plane-mcp.modules")


def register_module_tools(mcp, get_client):
    @mcp.tool()
    async def list_modules(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """List all modules in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        client = get_client()
        modules = normalize_list(
            client.modules.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        results = []
        for m in modules:
            results.append({
                "id": extract(m, "id"),
                "name": extract(m, "name"),
                "description": extract(m, "description"),
                "start_date": extract(m, "start_date"),
                "target_date": extract(m, "target_date"),
                "status": extract(m, "status"),
                "created_at": extract(m, "created_at"),
            })

        logger.info(
            "list_modules: workspace=%s project=%s found %d modules",
            workspace_slug,
            project_id,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def create_module(
        workspace_slug: str,
        project_id: str,
        name: str,
        description: str = "",
        start_date: str = "",
        target_date: str = "",
    ) -> dict[str, Any]:
        """Create a new module (thematic workstream) in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            name: Module name.
            description: Module description.
            start_date: Start date (ISO format YYYY-MM-DD).
            target_date: Target completion date (ISO format YYYY-MM-DD).
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create module in workspace '{workspace_slug}' — "
                    f"modules must be created in home workspace '{home}'."
                ),
            }

        audit_log("create_module", workspace_slug, {
            "project_id": project_id,
            "name": name,
        })

        client = get_client()
        create_kwargs: dict[str, Any] = {"name": name}
        if description:
            create_kwargs["description"] = description
        if start_date:
            create_kwargs["start_date"] = start_date
        if target_date:
            create_kwargs["target_date"] = target_date

        module = client.modules.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            data=CreateModule(**create_kwargs),
        )

        module_id = extract(module, "id")
        logger.info(
            "create_module: created module=%s in workspace=%s project=%s",
            module_id,
            workspace_slug,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": module_id,
                "name": name,
                "description": description,
                "start_date": start_date,
                "target_date": target_date,
            },
        }

    @mcp.tool()
    async def add_module_work_items(
        workspace_slug: str,
        project_id: str,
        module_id: str,
        work_item_ids: list[str],
    ) -> dict[str, Any]:
        """Add work items to a module.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            module_id: The module UUID.
            work_item_ids: List of work item UUIDs to add.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot modify module in workspace '{workspace_slug}' — "
                    f"module membership must be managed in home workspace '{home}'."
                ),
            }

        audit_log("add_module_work_items", workspace_slug, {
            "project_id": project_id,
            "module_id": module_id,
            "count": len(work_item_ids),
        })

        client = get_client()
        client.modules.add_work_items(
            workspace_slug=workspace_slug,
            project_id=project_id,
            module_id=module_id,
            issue_ids=work_item_ids,
        )

        logger.info(
            "add_module_work_items: added %d items to module=%s",
            len(work_item_ids),
            module_id,
        )
        return {
            "ok": True,
            "data": {
                "module_id": module_id,
                "added_count": len(work_item_ids),
                "work_item_ids": work_item_ids,
            },
        }

    @mcp.tool()
    async def remove_module_work_item(
        workspace_slug: str,
        project_id: str,
        module_id: str,
        work_item_id: str,
    ) -> dict[str, Any]:
        """Remove a work item from a module.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            module_id: The module UUID.
            work_item_id: The work item UUID to remove.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot modify module in workspace '{workspace_slug}' — "
                    f"module membership must be managed in home workspace '{home}'."
                ),
            }

        audit_log("remove_module_work_item", workspace_slug, {
            "project_id": project_id,
            "module_id": module_id,
            "work_item_id": work_item_id,
        })

        client = get_client()
        client.modules.remove_work_item(
            workspace_slug=workspace_slug,
            project_id=project_id,
            module_id=module_id,
            work_item_id=work_item_id,
        )

        logger.info(
            "remove_module_work_item: removed %s from module=%s",
            work_item_id,
            module_id,
        )
        return {
            "ok": True,
            "data": {
                "module_id": module_id,
                "removed_work_item_id": work_item_id,
            },
        }
