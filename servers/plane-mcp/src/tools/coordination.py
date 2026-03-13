"""Coordination tools for agent-agent and human-agent collaboration.

Provides member discovery, cross-project search, intake triage,
and work item history capabilities.
"""

from __future__ import annotations

import logging
from typing import Any

from plane.models.intake import CreateIntakeWorkItem, UpdateIntakeWorkItem
from plane.models.work_items import WorkItemForIntakeRequest
from tools._helpers import audit_log, extract, home_workspace, normalize_list

logger = logging.getLogger("plane-mcp.coordination")

# Map human-readable status strings to Plane intake status integers
_INTAKE_STATUS_MAP = {
    "pending": -2,
    "declined": -1,
    "snoozed": 0,
    "accepted": 1,
    "duplicate": 2,
}


def register_coordination_tools(mcp, get_client):
    @mcp.tool()
    async def list_project_members(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """List all members of a project.

        Useful for knowing who (human or agent) can be assigned work.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        client = get_client()
        members = normalize_list(
            client.projects.get_members(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        results = []
        for m in members:
            results.append({
                "id": extract(m, "id"),
                "display_name": extract(m, "display_name"),
                "email": extract(m, "email"),
                "role": extract(m, "role"),
            })

        logger.info(
            "list_project_members: workspace=%s project=%s found %d members",
            workspace_slug,
            project_id,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def list_workspace_members(
        workspace_slug: str,
    ) -> dict[str, Any]:
        """List all members of a workspace.

        Discovers assignable targets across all projects in the workspace.

        Args:
            workspace_slug: The workspace slug.
        """
        client = get_client()
        members = normalize_list(
            client.workspaces.get_members(
                workspace_slug=workspace_slug,
            )
        )
        results = []
        for m in members:
            results.append({
                "id": extract(m, "id"),
                "display_name": extract(m, "display_name"),
                "email": extract(m, "email"),
                "role": extract(m, "role"),
            })

        logger.info(
            "list_workspace_members: workspace=%s found %d members",
            workspace_slug,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def search_work_items(
        workspace_slug: str,
        query: str,
    ) -> dict[str, Any]:
        """Search work items across all projects in a workspace.

        Uses Plane's workspace-scoped search API. Returns matching work items
        from any project the agent has access to.

        Args:
            workspace_slug: The workspace slug.
            query: Search query string.
        """
        client = get_client()
        raw = client.work_items.search(
            workspace_slug=workspace_slug,
            query=query,
        )

        # WorkItemSearch returns results in .issues field
        items = getattr(raw, "issues", None)
        if items is None:
            # Fallback for dict responses (e.g. in tests)
            items = normalize_list(raw)

        results = []
        for wi in items:
            results.append({
                "id": extract(wi, "id"),
                "name": extract(wi, "name"),
                "project_id": extract(wi, "project_id", extract(wi, "project")),
                "state": extract(wi, "state"),
                "priority": extract(wi, "priority"),
                "workspace_slug": extract(wi, "workspace_slug", workspace_slug),
            })

        logger.info(
            "search_work_items: workspace=%s query='%s' found %d results",
            workspace_slug,
            query,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def list_intake_items(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """List intake (triage queue) items for a project.

        Intake items are inbound work that hasn't been accepted
        into the project backlog yet.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        client = get_client()
        items = normalize_list(
            client.intake.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        results = []
        for item in items:
            # SDK IntakeWorkItem nests work-item data under issue_detail
            detail = extract(item, "issue_detail")
            if detail and detail != "":
                name = extract(detail, "name")
                desc = extract(detail, "description_html")
                priority = extract(detail, "priority")
            else:
                # Fallback for flat dict (tests / direct HTTP)
                name = extract(item, "name")
                desc = extract(item, "description_html")
                priority = extract(item, "priority")

            results.append({
                "id": extract(item, "id"),
                "issue_id": extract(item, "issue"),
                "name": name,
                "description_html": desc,
                "priority": priority,
                "source": extract(item, "source"),
                "status": extract(item, "status"),
                "created_at": extract(item, "created_at"),
            })

        logger.info(
            "list_intake_items: workspace=%s project=%s found %d items",
            workspace_slug,
            project_id,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def create_intake_item(
        workspace_slug: str,
        project_id: str,
        title: str,
        description: str = "",
        priority: str = "medium",
    ) -> dict[str, Any]:
        """Create a new intake item for triage.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            title: Item title.
            description: Item description (HTML supported).
            priority: Priority level (none, low, medium, high, urgent).
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create intake item in workspace '{workspace_slug}' — "
                    f"intake items must be created in home workspace '{home}'."
                ),
            }

        audit_log("create_intake_item", workspace_slug, {
            "project_id": project_id,
            "title": title,
        })

        client = get_client()

        issue_kwargs: dict[str, Any] = {
            "name": title,
            "priority": priority.lower(),
        }
        if description:
            issue_kwargs["description_html"] = f"<p>{description}</p>"

        item = client.intake.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            data=CreateIntakeWorkItem(
                issue=WorkItemForIntakeRequest(**issue_kwargs),
            ),
        )

        item_id = extract(item, "id")
        issue_id = extract(item, "issue")
        logger.info(
            "create_intake_item: created intake=%s issue=%s in project=%s",
            item_id,
            issue_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": item_id,
                "issue_id": issue_id,
                "name": title,
                "priority": priority,
            },
        }

    @mcp.tool()
    async def update_intake_item(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
        status: str = "",
    ) -> dict[str, Any]:
        """Update an intake item's status (accept, decline, snooze).

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The underlying work item UUID (use issue_id from
                list_intake_items or create_intake_item, not the intake item's own id).
            status: New status (pending, declined, snoozed, accepted, duplicate).
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot update intake item in workspace '{workspace_slug}' — "
                    f"intake items must be updated in home workspace '{home}'."
                ),
            }

        audit_log("update_intake_item", workspace_slug, {
            "project_id": project_id,
            "work_item_id": work_item_id,
        })

        if not status:
            return {
                "ok": False,
                "error": "At least one of status must be provided.",
            }

        status_int = _INTAKE_STATUS_MAP.get(status.lower())
        if status_int is None:
            valid = ", ".join(_INTAKE_STATUS_MAP.keys())
            return {
                "ok": False,
                "error": f"Invalid status '{status}'. Valid values: {valid}",
            }

        client = get_client()
        result = client.intake.update(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=UpdateIntakeWorkItem(status=status_int),
        )

        logger.info(
            "update_intake_item: updated intake=%s in project=%s",
            work_item_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": extract(result, "id", work_item_id),
                "status": status,
            },
        }

    @mcp.tool()
    async def get_work_item_history(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
    ) -> dict[str, Any]:
        """Get the activity history for a work item.

        Returns a chronological list of changes (state transitions, field
        updates, comments, etc.) for audit and context reconstruction.

        Uses the SDK activities endpoint (work-items/{id}/activities) rather
        than the app-level /issues/{id}/history/ — activities provides the
        same audit trail data via a supported public API surface.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The work item UUID.
        """
        client = get_client()
        activities = normalize_list(
            client.work_items.activities.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
                work_item_id=work_item_id,
            )
        )

        results = []
        for a in activities:
            results.append({
                "id": extract(a, "id"),
                "verb": extract(a, "verb"),
                "field": extract(a, "field"),
                "old_value": extract(a, "old_value"),
                "new_value": extract(a, "new_value"),
                "actor": extract(a, "actor"),
                "created_at": extract(a, "created_at"),
            })

        logger.info(
            "get_work_item_history: work_item=%s found %d activities",
            work_item_id,
            len(results),
        )
        return {"ok": True, "data": results}
