"""Discovery tools for Plane workspaces, projects, and work items.

All tools in this module are read-only and do not require governance
checks beyond standard audit logging.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from tools._helpers import extract, normalize_list, work_item_to_dict
from tools._http import api_get

logger = logging.getLogger("plane-mcp.discovery")


def register_discovery_tools(mcp, get_client):
    @mcp.tool()
    async def list_workspaces() -> dict[str, Any]:
        """Enumerate all visible workspaces.

        Returns a list of workspace objects with slug, name, and member count.
        This is a read-only operation.
        """
        # SDK has no workspaces.list() — use direct HTTP
        raw = await api_get("/workspaces/")
        items = normalize_list(raw)

        results = []
        for ws in items:
            results.append({
                "slug": extract(ws, "slug"),
                "name": extract(ws, "name"),
                "member_count": extract(ws, "total_members", 0),
                "id": extract(ws, "id"),
            })

        logger.info("list_workspaces: found %d workspaces", len(results))
        return {"ok": True, "data": results}

    @mcp.tool()
    async def list_projects(workspace_slug: str) -> dict[str, Any]:
        """List all projects in a workspace.

        Args:
            workspace_slug: The workspace slug to list projects from.
        """
        client = get_client()
        projects = client.projects.list(workspace_slug=workspace_slug)
        items = normalize_list(projects)
        results = []
        for proj in items:
            results.append({
                "id": extract(proj, "id"),
                "name": extract(proj, "name"),
                "identifier": extract(proj, "identifier"),
                "description": extract(proj, "description"),
                "network": extract(proj, "network", 2),
                "member_count": extract(proj, "total_members", 0),
            })

        logger.info(
            "list_projects: workspace=%s found %d projects",
            workspace_slug,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def get_project_bundle(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """Get a project along with its states, labels, and recent work items.

        Returns a bundle containing the project details, available states,
        labels, and the most recent work items for quick orientation.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        client = get_client()
        project = client.projects.retrieve(
            workspace_slug=workspace_slug,
            project_id=project_id,
        )
        project_data = {
            "id": extract(project, "id"),
            "name": extract(project, "name"),
            "identifier": extract(project, "identifier"),
            "description": extract(project, "description"),
            "network": extract(project, "network", 2),
        }

        states = normalize_list(
            client.states.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        state_list = []
        for s in states:
            state_list.append({
                "id": extract(s, "id"),
                "name": extract(s, "name"),
                "group": extract(s, "group"),
                "color": extract(s, "color"),
            })

        labels = normalize_list(
            client.labels.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        label_list = []
        for lb in labels:
            label_list.append({
                "id": extract(lb, "id"),
                "name": extract(lb, "name"),
                "color": extract(lb, "color"),
            })

        work_items = normalize_list(
            client.work_items.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        recent_items = []
        for wi in work_items[:20]:
            recent_items.append({
                "id": extract(wi, "id"),
                "name": extract(wi, "name"),
                "state": extract(wi, "state"),
                "priority": extract(wi, "priority"),
                "labels": extract(wi, "labels", default=[]),
                "parent": extract(wi, "parent"),
                "created_at": extract(wi, "created_at"),
            })

        logger.info(
            "get_project_bundle: workspace=%s project=%s states=%d labels=%d items=%d",
            workspace_slug,
            project_id,
            len(state_list),
            len(label_list),
            len(recent_items),
        )
        return {
            "ok": True,
            "data": {
                "project": project_data,
                "states": state_list,
                "labels": label_list,
                "recent_work_items": recent_items,
            },
        }

    @mcp.tool()
    async def get_case_bundle(
        workspace_slug: str,
        project_id: str,
        case_id: str,
    ) -> dict[str, Any]:
        """Get a work item labeled as a 'case' along with its child items and comments.

        A case is the top-level governance unit. This bundle provides the case
        details, all child work items (tasks), and activity comments.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            case_id: The work item UUID for the case.
        """
        client = get_client()
        case_item = client.work_items.retrieve(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=case_id,
        )
        case_data = work_item_to_dict(case_item)

        all_items = normalize_list(
            client.work_items.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        children = []
        for wi in all_items:
            if extract(wi, "parent") == case_id:
                children.append(work_item_to_dict(wi))

        comments = _fetch_comments(client, workspace_slug, project_id, case_id)

        logger.info(
            "get_case_bundle: workspace=%s case=%s children=%d comments=%d",
            workspace_slug,
            case_id,
            len(children),
            len(comments),
        )
        return {
            "ok": True,
            "data": {
                "case": case_data,
                "child_work_items": children,
                "comments": comments,
            },
        }

    @mcp.tool()
    async def get_task_bundle(
        workspace_slug: str,
        project_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        """Get a work item (task) along with its sub-items and comments.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            task_id: The work item UUID.
        """
        client = get_client()
        task_item = client.work_items.retrieve(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=task_id,
        )
        task_data = work_item_to_dict(task_item)

        all_items = normalize_list(
            client.work_items.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        sub_items = []
        for wi in all_items:
            if extract(wi, "parent") == task_id:
                sub_items.append(work_item_to_dict(wi))

        comments = _fetch_comments(client, workspace_slug, project_id, task_id)

        logger.info(
            "get_task_bundle: workspace=%s task=%s sub_items=%d comments=%d",
            workspace_slug,
            task_id,
            len(sub_items),
            len(comments),
        )
        return {
            "ok": True,
            "data": {
                "task": task_data,
                "sub_items": sub_items,
                "comments": comments,
            },
        }

    @mcp.tool()
    async def list_overdue_tasks(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """List work items with a target_date before today that are not yet completed.

        Useful for tracking human tasks that need follow-up. Filters out items
        in the 'completed' or 'cancelled' state groups.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        client = get_client()

        # Fetch states to identify completed/cancelled groups
        states = normalize_list(
            client.states.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        terminal_state_ids = set()
        for s in states:
            group = extract(s, "group")
            if group in ("completed", "cancelled"):
                terminal_state_ids.add(extract(s, "id"))

        # Fetch all work items and filter
        all_items = normalize_list(
            client.work_items.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )

        today_str = date.today().isoformat()
        overdue = []
        for wi in all_items:
            target = extract(wi, "target_date")
            state = extract(wi, "state")
            if not target:
                continue
            # Normalize target_date to date string for comparison
            target_date_str = str(target)[:10]
            if target_date_str < today_str and state not in terminal_state_ids:
                overdue.append(work_item_to_dict(wi))

        logger.info(
            "list_overdue_tasks: workspace=%s project=%s found %d overdue",
            workspace_slug,
            project_id,
            len(overdue),
        )
        return {"ok": True, "data": overdue}


def _fetch_comments(
    client: Any,
    workspace_slug: str,
    project_id: str,
    work_item_id: str,
) -> list[dict[str, Any]]:
    """Fetch comments for a work item using the SDK."""
    try:
        comments_raw = client.work_items.comments.list(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
        )
        comments = normalize_list(comments_raw)
    except Exception:
        logger.warning(
            "Failed to fetch comments for work_item=%s",
            work_item_id,
        )
        return []

    result = []
    for c in comments:
        # Resolve actor display name from either dict or SDK object
        if isinstance(c, dict):
            actor_detail = c.get("actor_detail", {})
            actor = actor_detail.get("display_name", "") if actor_detail else ""
        else:
            # SDK WorkItemComment exposes created_by (actor UUID)
            actor = extract(c, "created_by")

        result.append({
            "id": extract(c, "id"),
            "comment_html": extract(c, "comment_html"),
            "actor": actor,
            "created_at": extract(c, "created_at"),
        })
    return result
