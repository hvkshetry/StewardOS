"""Creation tools for Plane cases and tasks.

All write operations are audit-logged with workspace attribution.
All structural writes (cases, agent-tasks, human-tasks) are rejected
when workspace_slug != PLANE_HOME_WORKSPACE — Plane requires parent
and child work items to reside in the same project.
"""

from __future__ import annotations

import logging
from typing import Any

from plane.models.labels import CreateLabel
from plane.models.work_items import CreateWorkItem
from tools._helpers import audit_log, extract, home_workspace, normalize_list

logger = logging.getLogger("plane-mcp.creation")


def _ensure_label_exists(
    client: Any,
    workspace_slug: str,
    project_id: str,
    label_name: str,
    existing_labels: list[dict[str, Any]],
) -> str:
    """Find or create a label by name, returning its ID."""
    for lb in existing_labels:
        name = lb.get("name", "") if isinstance(lb, dict) else getattr(lb, "name", "")
        lb_id = lb.get("id", "") if isinstance(lb, dict) else getattr(lb, "id", "")
        if name == label_name:
            return lb_id

    new_label = client.labels.create(
        workspace_slug=workspace_slug,
        project_id=project_id,
        data=CreateLabel(name=label_name, color="#6366f1"),
    )
    new_id = extract(new_label, "id")
    existing_labels.append({"id": new_id, "name": label_name})
    return new_id


def _resolve_label_ids(
    client: Any,
    workspace_slug: str,
    project_id: str,
    label_names: list[str],
    existing_labels: list[dict[str, Any]],
) -> list[str]:
    """Resolve a list of label names to their IDs, creating any that are missing."""
    ids = []
    for name in label_names:
        label_id = _ensure_label_exists(
            client, workspace_slug, project_id, name, existing_labels,
        )
        ids.append(label_id)
    return ids


def _fetch_existing_labels(client: Any, workspace_slug: str, project_id: str) -> list[dict[str, Any]]:
    """Fetch all labels for a project and normalize to list of dicts."""
    items = normalize_list(
        client.labels.list(workspace_slug=workspace_slug, project_id=project_id)
    )
    result = []
    for lb in items:
        result.append({
            "id": extract(lb, "id"),
            "name": extract(lb, "name"),
        })
    return result


def register_creation_tools(mcp, get_client):
    @mcp.tool()
    async def create_case(
        workspace_slug: str,
        project_id: str,
        title: str,
        description: str = "",
        priority: str = "medium",
        labels: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new work item labeled as a 'case' (top-level governance unit).

        Validates workspace_slug against PLANE_HOME_WORKSPACE. If they differ,
        the operation is rejected — cases must be created in the home workspace.
        Use create_agent_task for cross-domain delegation.

        Args:
            workspace_slug: Target workspace slug.
            project_id: Target project UUID.
            title: Case title.
            description: Case description (HTML supported).
            priority: Priority level (none, low, medium, high, urgent).
            labels: Additional label names to apply (beyond the automatic 'case' label).
        """
        client = get_client()
        audit_log("create_case", workspace_slug, {"project_id": project_id, "title": title})

        home = home_workspace()
        cross_domain = workspace_slug != home if home else False

        if cross_domain and home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create case in workspace '{workspace_slug}' — "
                    f"cases must be created in home workspace '{home}'. "
                    "Use create_agent_task for cross-domain delegation."
                ),
            }

        existing_labels = _fetch_existing_labels(client, workspace_slug, project_id)

        required_labels = ["case"]
        if labels:
            required_labels.extend(labels)

        label_ids = _resolve_label_ids(
            client, workspace_slug, project_id, required_labels, existing_labels,
        )

        work_item = client.work_items.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            data=CreateWorkItem(
                name=title,
                description_html=f"<p>{description}</p>" if description else None,
                priority=priority.lower(),
                labels=label_ids,
            ),
        )

        item_id = extract(work_item, "id")
        logger.info(
            "create_case: created work_item=%s in workspace=%s project=%s",
            item_id,
            workspace_slug,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": item_id,
                "name": title,
                "labels": required_labels,
                "priority": priority,
                "cross_domain": cross_domain,
            },
        }

    @mcp.tool()
    async def create_agent_task(
        workspace_slug: str,
        project_id: str,
        case_id: str,
        title: str,
        description: str = "",
        target_alias: str = "",
        priority: str = "medium",
    ) -> dict[str, Any]:
        """Create a child work item under a case, labeled as 'agent-task'.

        Agent tasks are delegated to a specific persona/agent identified by
        target_alias. The task is linked as a child of the parent case.

        Args:
            workspace_slug: Target workspace slug.
            project_id: Target project UUID.
            case_id: Parent case work item UUID.
            title: Task title.
            description: Task description (HTML supported).
            target_alias: The persona/agent alias this task is delegated to.
            priority: Priority level (none, low, medium, high, urgent).
        """
        client = get_client()
        audit_log("create_agent_task", workspace_slug, {
            "project_id": project_id,
            "case_id": case_id,
            "target_alias": target_alias,
        })

        home = home_workspace()
        cross_domain = workspace_slug != home if home else False

        if cross_domain and home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create agent task in workspace '{workspace_slug}' — "
                    f"parent/child work items must be in the same project within "
                    f"home workspace '{home}'. Create the task in your home workspace "
                    f"with a target_alias label to route execution to the specialist."
                ),
            }

        existing_labels = _fetch_existing_labels(client, workspace_slug, project_id)

        required_labels = ["agent-task"]
        if target_alias:
            required_labels.append(f"target_alias:{target_alias}")
        required_labels.append(f"delegated_by:{case_id}")

        label_ids = _resolve_label_ids(
            client, workspace_slug, project_id, required_labels, existing_labels,
        )

        work_item = client.work_items.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            data=CreateWorkItem(
                name=title,
                description_html=f"<p>{description}</p>" if description else None,
                priority=priority.lower(),
                labels=label_ids,
                parent=case_id,
            ),
        )

        item_id = extract(work_item, "id")
        logger.info(
            "create_agent_task: created work_item=%s under case=%s target=%s",
            item_id,
            case_id,
            target_alias,
        )
        return {
            "ok": True,
            "data": {
                "id": item_id,
                "name": title,
                "parent": case_id,
                "labels": required_labels,
                "target_alias": target_alias,
                "priority": priority,
                "cross_domain": cross_domain,
            },
        }

    @mcp.tool()
    async def create_human_task(
        workspace_slug: str,
        project_id: str,
        case_id: str,
        title: str,
        description: str = "",
        assignee_id: str = "",
        priority: str = "medium",
        due_date: str = "",
        start_date: str = "",
    ) -> dict[str, Any]:
        """Create a child work item under a case, labeled as 'human-task'.

        Human tasks are assigned to a specific person for manual execution.
        The task is linked as a child of the parent case. Supports optional
        due_date and start_date for scheduling and overdue tracking.

        Args:
            workspace_slug: Target workspace slug.
            project_id: Target project UUID.
            case_id: Parent case work item UUID.
            title: Task title.
            description: Task description (HTML supported).
            assignee_id: UUID of the person to assign this task to.
            priority: Priority level (none, low, medium, high, urgent).
            due_date: Target completion date (ISO format YYYY-MM-DD).
            start_date: Start date for the task (ISO format YYYY-MM-DD).
        """
        client = get_client()
        audit_log("create_human_task", workspace_slug, {
            "project_id": project_id,
            "case_id": case_id,
            "assignee_id": assignee_id,
        })

        home = home_workspace()
        cross_domain = workspace_slug != home if home else False

        if cross_domain and home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create human task in workspace '{workspace_slug}' — "
                    f"parent/child work items must be in the same project within "
                    f"home workspace '{home}'."
                ),
            }

        existing_labels = _fetch_existing_labels(client, workspace_slug, project_id)

        required_labels = ["human-task"]
        required_labels.append(f"delegated_by:{case_id}")

        label_ids = _resolve_label_ids(
            client, workspace_slug, project_id, required_labels, existing_labels,
        )

        create_kwargs: dict[str, Any] = {
            "name": title,
            "description_html": f"<p>{description}</p>" if description else None,
            "priority": priority.lower(),
            "labels": label_ids,
            "parent": case_id,
        }
        if assignee_id:
            create_kwargs["assignees"] = [assignee_id]
        if due_date:
            create_kwargs["target_date"] = due_date
        if start_date:
            create_kwargs["start_date"] = start_date

        work_item = client.work_items.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            data=CreateWorkItem(**create_kwargs),
        )

        item_id = extract(work_item, "id")
        logger.info(
            "create_human_task: created work_item=%s under case=%s assignee=%s",
            item_id,
            case_id,
            assignee_id,
        )
        return {
            "ok": True,
            "data": {
                "id": item_id,
                "name": title,
                "parent": case_id,
                "labels": required_labels,
                "assignee_id": assignee_id,
                "priority": priority,
                "due_date": due_date,
                "start_date": start_date,
                "cross_domain": cross_domain,
            },
        }
