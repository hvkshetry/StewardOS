"""State and label management tools for Plane.

Provides explicit lifecycle management for workflow states and labels,
going beyond the implicit label creation in creation tools.
"""

from __future__ import annotations

import logging
from typing import Any

from plane.models.labels import CreateLabel, UpdateLabel
from plane.models.states import CreateState, UpdateState
from tools._helpers import audit_log, extract, home_workspace, normalize_list

logger = logging.getLogger("plane-mcp.management")


def register_management_tools(mcp, get_client):
    # -----------------------------------------------------------------------
    # States
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def list_states(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """List all workflow states in a project.

        States are grouped by type: backlog, unstarted, started, completed, cancelled.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        client = get_client()
        states = normalize_list(
            client.states.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        results = []
        for s in states:
            results.append({
                "id": extract(s, "id"),
                "name": extract(s, "name"),
                "group": extract(s, "group"),
                "color": extract(s, "color"),
                "sequence": extract(s, "sequence", 0),
            })

        logger.info(
            "list_states: workspace=%s project=%s found %d states",
            workspace_slug,
            project_id,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def create_state(
        workspace_slug: str,
        project_id: str,
        name: str,
        group: str,
        color: str = "#6366f1",
    ) -> dict[str, Any]:
        """Create a new workflow state in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            name: State name (e.g. 'In Review', 'Blocked').
            group: State group (backlog, unstarted, started, completed, cancelled).
            color: Hex color for the state (default: indigo).
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create state in workspace '{workspace_slug}' — "
                    f"states must be created in home workspace '{home}'."
                ),
            }

        audit_log("create_state", workspace_slug, {
            "project_id": project_id,
            "name": name,
            "group": group,
        })

        client = get_client()
        state = client.states.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            data=CreateState(name=name, group=group, color=color),
        )

        state_id = extract(state, "id")
        logger.info(
            "create_state: created state=%s (%s) in project=%s",
            state_id,
            name,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": state_id,
                "name": name,
                "group": group,
                "color": color,
            },
        }

    @mcp.tool()
    async def update_state(
        workspace_slug: str,
        project_id: str,
        state_id: str,
        name: str = "",
        group: str = "",
        color: str = "",
    ) -> dict[str, Any]:
        """Update a workflow state's properties.

        At least one of name, group, or color must be provided.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            state_id: The state UUID to update.
            name: New state name.
            group: New state group (backlog, unstarted, started, completed, cancelled).
            color: New hex color.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot update state in workspace '{workspace_slug}' — "
                    f"states must be updated in home workspace '{home}'."
                ),
            }

        audit_log("update_state", workspace_slug, {
            "project_id": project_id,
            "state_id": state_id,
        })

        update_kwargs: dict[str, Any] = {}
        if name:
            update_kwargs["name"] = name
        if group:
            update_kwargs["group"] = group
        if color:
            update_kwargs["color"] = color

        if not update_kwargs:
            return {
                "ok": False,
                "error": "At least one of name, group, or color must be provided.",
            }

        client = get_client()
        result = client.states.update(
            workspace_slug=workspace_slug,
            project_id=project_id,
            state_id=state_id,
            data=UpdateState(**update_kwargs),
        )

        logger.info(
            "update_state: updated state=%s in project=%s",
            state_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": extract(result, "id", state_id),
                "name": extract(result, "name"),
                "group": extract(result, "group"),
                "color": extract(result, "color"),
            },
        }

    # -----------------------------------------------------------------------
    # Labels
    # -----------------------------------------------------------------------

    @mcp.tool()
    async def list_labels(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """List all labels in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        client = get_client()
        labels = normalize_list(
            client.labels.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )
        results = []
        for lb in labels:
            results.append({
                "id": extract(lb, "id"),
                "name": extract(lb, "name"),
                "color": extract(lb, "color"),
            })

        logger.info(
            "list_labels: workspace=%s project=%s found %d labels",
            workspace_slug,
            project_id,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def create_label(
        workspace_slug: str,
        project_id: str,
        name: str,
        color: str = "#6366f1",
    ) -> dict[str, Any]:
        """Create a new label in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            name: Label name.
            color: Hex color for the label (default: indigo).
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create label in workspace '{workspace_slug}' — "
                    f"labels must be created in home workspace '{home}'."
                ),
            }

        audit_log("create_label", workspace_slug, {
            "project_id": project_id,
            "name": name,
        })

        client = get_client()
        label = client.labels.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            data=CreateLabel(name=name, color=color),
        )

        label_id = extract(label, "id")
        logger.info(
            "create_label: created label=%s (%s) in project=%s",
            label_id,
            name,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": label_id,
                "name": name,
                "color": color,
            },
        }

    @mcp.tool()
    async def update_label(
        workspace_slug: str,
        project_id: str,
        label_id: str,
        name: str = "",
        color: str = "",
    ) -> dict[str, Any]:
        """Update a label's properties.

        At least one of name or color must be provided.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            label_id: The label UUID to update.
            name: New label name.
            color: New hex color.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot update label in workspace '{workspace_slug}' — "
                    f"labels must be updated in home workspace '{home}'."
                ),
            }

        audit_log("update_label", workspace_slug, {
            "project_id": project_id,
            "label_id": label_id,
        })

        update_kwargs: dict[str, Any] = {}
        if name:
            update_kwargs["name"] = name
        if color:
            update_kwargs["color"] = color

        if not update_kwargs:
            return {
                "ok": False,
                "error": "At least one of name or color must be provided.",
            }

        client = get_client()
        result = client.labels.update(
            workspace_slug=workspace_slug,
            project_id=project_id,
            label_id=label_id,
            data=UpdateLabel(**update_kwargs),
        )

        logger.info(
            "update_label: updated label=%s in project=%s",
            label_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": extract(result, "id", label_id),
                "name": extract(result, "name"),
                "color": extract(result, "color"),
            },
        }

    @mcp.tool()
    async def delete_label(
        workspace_slug: str,
        project_id: str,
        label_id: str,
    ) -> dict[str, Any]:
        """Delete a label from a project.

        Existing work items with this label will have it removed.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            label_id: The label UUID to delete.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot delete label in workspace '{workspace_slug}' — "
                    f"labels must be deleted in home workspace '{home}'."
                ),
            }

        audit_log("delete_label", workspace_slug, {
            "project_id": project_id,
            "label_id": label_id,
        })

        client = get_client()
        client.labels.delete(
            workspace_slug=workspace_slug,
            project_id=project_id,
            label_id=label_id,
        )

        logger.info(
            "delete_label: deleted label=%s from project=%s",
            label_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": label_id,
                "status": "deleted",
            },
        }
