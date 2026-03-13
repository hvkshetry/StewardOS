"""Cycle management tools for Plane.

Cycles serve as milestone-like timeboxes for organizing work items
into sprints or time-bounded iterations.
"""

from __future__ import annotations

import logging
from typing import Any

from plane.models.cycles import CreateCycle
from tools._helpers import audit_log, extract, home_workspace, normalize_list, work_item_to_dict

logger = logging.getLogger("plane-mcp.cycles")


def register_cycle_tools(mcp, get_client):
    @mcp.tool()
    async def list_cycles(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """List all cycles in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        client = get_client()
        cycles = normalize_list(
            client.cycles.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        results = []
        for c in cycles:
            results.append({
                "id": extract(c, "id"),
                "name": extract(c, "name"),
                "description": extract(c, "description"),
                "start_date": extract(c, "start_date"),
                "end_date": extract(c, "end_date"),
                "status": extract(c, "status"),
                "created_at": extract(c, "created_at"),
            })

        logger.info(
            "list_cycles: workspace=%s project=%s found %d cycles",
            workspace_slug,
            project_id,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def create_cycle(
        workspace_slug: str,
        project_id: str,
        name: str,
        description: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> dict[str, Any]:
        """Create a new cycle (timebox) in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            name: Cycle name.
            description: Cycle description.
            start_date: Start date (ISO format YYYY-MM-DD).
            end_date: End date (ISO format YYYY-MM-DD).
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create cycle in workspace '{workspace_slug}' — "
                    f"cycles must be created in home workspace '{home}'."
                ),
            }

        audit_log("create_cycle", workspace_slug, {
            "project_id": project_id,
            "name": name,
        })

        client = get_client()
        create_kwargs: dict[str, Any] = {
            "name": name,
            "project_id": project_id,
            "owned_by": "",  # Server sets to authenticated user
        }
        if description:
            create_kwargs["description"] = description
        if start_date:
            create_kwargs["start_date"] = start_date
        if end_date:
            create_kwargs["end_date"] = end_date

        cycle = client.cycles.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            data=CreateCycle(**create_kwargs),
        )

        cycle_id = extract(cycle, "id")
        logger.info(
            "create_cycle: created cycle=%s in workspace=%s project=%s",
            cycle_id,
            workspace_slug,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": cycle_id,
                "name": name,
                "description": description,
                "start_date": start_date,
                "end_date": end_date,
            },
        }

    @mcp.tool()
    async def add_cycle_work_items(
        workspace_slug: str,
        project_id: str,
        cycle_id: str,
        work_item_ids: list[str],
    ) -> dict[str, Any]:
        """Add work items to a cycle.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            cycle_id: The cycle UUID.
            work_item_ids: List of work item UUIDs to add.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot modify cycle in workspace '{workspace_slug}' — "
                    f"cycle membership must be managed in home workspace '{home}'."
                ),
            }

        audit_log("add_cycle_work_items", workspace_slug, {
            "project_id": project_id,
            "cycle_id": cycle_id,
            "count": len(work_item_ids),
        })

        client = get_client()
        client.cycles.add_work_items(
            workspace_slug=workspace_slug,
            project_id=project_id,
            cycle_id=cycle_id,
            issue_ids=work_item_ids,
        )

        logger.info(
            "add_cycle_work_items: added %d items to cycle=%s",
            len(work_item_ids),
            cycle_id,
        )
        return {
            "ok": True,
            "data": {
                "cycle_id": cycle_id,
                "added_count": len(work_item_ids),
                "work_item_ids": work_item_ids,
            },
        }

    @mcp.tool()
    async def remove_cycle_work_item(
        workspace_slug: str,
        project_id: str,
        cycle_id: str,
        work_item_id: str,
    ) -> dict[str, Any]:
        """Remove a work item from a cycle.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            cycle_id: The cycle UUID.
            work_item_id: The work item UUID to remove.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot modify cycle in workspace '{workspace_slug}' — "
                    f"cycle membership must be managed in home workspace '{home}'."
                ),
            }

        audit_log("remove_cycle_work_item", workspace_slug, {
            "project_id": project_id,
            "cycle_id": cycle_id,
            "work_item_id": work_item_id,
        })

        client = get_client()
        client.cycles.remove_work_item(
            workspace_slug=workspace_slug,
            project_id=project_id,
            cycle_id=cycle_id,
            work_item_id=work_item_id,
        )

        logger.info(
            "remove_cycle_work_item: removed %s from cycle=%s",
            work_item_id,
            cycle_id,
        )
        return {
            "ok": True,
            "data": {
                "cycle_id": cycle_id,
                "removed_work_item_id": work_item_id,
            },
        }

    @mcp.tool()
    async def get_cycle_progress(
        workspace_slug: str,
        project_id: str,
        cycle_id: str,
    ) -> dict[str, Any]:
        """Get cycle details and work item progress summary.

        Retrieves the cycle metadata and lists all work items in it,
        with a count of items by state ID in the `by_state` dict.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            cycle_id: The cycle UUID.
        """
        client = get_client()
        cycle = client.cycles.retrieve(
            workspace_slug=workspace_slug,
            project_id=project_id,
            cycle_id=cycle_id,
        )
        cycle_data = {
            "id": extract(cycle, "id"),
            "name": extract(cycle, "name"),
            "description": extract(cycle, "description"),
            "start_date": extract(cycle, "start_date"),
            "end_date": extract(cycle, "end_date"),
            "status": extract(cycle, "status"),
        }

        work_items = normalize_list(
            client.cycles.list_work_items(
                workspace_slug=workspace_slug,
                project_id=project_id,
                cycle_id=cycle_id,
            )
        )

        items = []
        state_counts: dict[str, int] = {}
        for wi in work_items:
            item_dict = work_item_to_dict(wi)
            items.append(item_dict)
            state_val = item_dict.get("state", "unknown")
            state_counts[state_val] = state_counts.get(state_val, 0) + 1

        logger.info(
            "get_cycle_progress: cycle=%s has %d work items",
            cycle_id,
            len(items),
        )
        return {
            "ok": True,
            "data": {
                "cycle": cycle_data,
                "work_items": items,
                "total_count": len(items),
                "by_state": state_counts,
            },
        }
