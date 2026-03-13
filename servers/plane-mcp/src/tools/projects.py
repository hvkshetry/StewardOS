"""Project management tools for Plane.

Provides project creation (with governance validation) and retrieval.
"""

from __future__ import annotations

import logging
from typing import Any

from tools._helpers import audit_log, extract, home_workspace, normalize_list

logger = logging.getLogger("plane-mcp.projects")


def register_project_tools(mcp, get_client):
    @mcp.tool()
    async def create_project(
        workspace_slug: str,
        name: str,
        description: str = "",
        network: int = 2,
    ) -> dict[str, Any]:
        """Create a new project in the agent's home workspace.

        Validates that workspace_slug matches PLANE_HOME_WORKSPACE. Rejects
        cross-domain project creation to enforce governance boundaries.

        Warns if the workspace already has more than 20 projects, to help
        maintain organizational hygiene.

        Args:
            workspace_slug: Target workspace slug.
            name: Project name.
            description: Project description.
            network: Network visibility (0=secret, 2=visible). Defaults to 2.
        """
        client = get_client()
        audit_log("create_project", workspace_slug, {"name": name})

        home = home_workspace()
        cross_domain = workspace_slug != home if home else False

        if cross_domain and home:
            logger.warning(
                "REJECTED cross-domain project creation: target=%s home=%s",
                workspace_slug,
                home,
            )
            return {
                "ok": False,
                "error": (
                    f"Cannot create project in workspace '{workspace_slug}'. "
                    f"Agents may only create projects in their home workspace '{home}'. "
                    "Request human approval for cross-workspace project creation."
                ),
            }

        warnings: list[str] = []

        existing_projects = normalize_list(
            client.projects.list(workspace_slug=workspace_slug)
        )
        project_count = len(existing_projects)

        if project_count > 20:
            warnings.append(
                f"Workspace '{workspace_slug}' already has {project_count} projects. "
                "Consider archiving unused projects for organizational hygiene."
            )

        project = client.projects.create(
            workspace_slug=workspace_slug,
            data={
                "name": name,
                "description": description,
                "network": network,
            },
        )

        project_id = extract(project, "id")
        project_identifier = extract(project, "identifier")

        logger.info(
            "create_project: created project=%s (%s) in workspace=%s",
            project_id,
            project_identifier,
            workspace_slug,
        )
        result: dict[str, Any] = {
            "ok": True,
            "data": {
                "id": project_id,
                "name": name,
                "identifier": project_identifier,
                "description": description,
                "network": network,
                "cross_domain": cross_domain,
            },
        }
        if warnings:
            result["warnings"] = warnings
        return result

    @mcp.tool()
    async def get_project(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """Get project details.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        client = get_client()
        project = client.projects.retrieve(
            workspace_slug=workspace_slug,
            project_id=project_id,
        )

        data = {
            "id": extract(project, "id"),
            "name": extract(project, "name"),
            "identifier": extract(project, "identifier"),
            "description": extract(project, "description"),
            "network": extract(project, "network", 2),
            "member_count": extract(project, "total_members", 0),
            "created_at": extract(project, "created_at"),
            "updated_at": extract(project, "updated_at"),
        }

        logger.info(
            "get_project: workspace=%s project=%s (%s)",
            workspace_slug,
            project_id,
            data.get("name", ""),
        )
        return {"ok": True, "data": data}
