"""Canonical workspace/project/member tool for Plane MCP."""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx

from tools._helpers import (
    display_name_from_slug,
    extract,
    home_workspace,
    normalize_list,
    work_item_to_dict,
)
from tools._http import api_get
from tools._members import (
    list_project_members as list_project_members_normalized,
    list_workspace_members as list_workspace_members_normalized,
    member_to_dict,
    resolve_member,
)

logger = logging.getLogger("plane-mcp.workspace")


def _known_workspace_slugs() -> list[str]:
    configured = {
        slug.strip()
        for slug in os.environ.get("PLANE_KNOWN_WORKSPACES", "").split(",")
        if slug.strip()
    }
    if configured:
        return sorted(configured)

    home = home_workspace()
    if home:
        configured.add(home)

    config_root = Path.home() / "personal" / "agent-configs"
    pattern = re.compile(r'PLANE_HOME_WORKSPACE\s*=\s*"([^"]+)"')
    if config_root.exists():
        for config_path in config_root.glob("*/.codex/config.toml"):
            try:
                content = config_path.read_text(encoding="utf-8")
            except OSError:
                continue
            for match in pattern.finditer(content):
                configured.add(match.group(1))

    return sorted(configured)


def register_workspace_tools(mcp, get_client):
    @mcp.tool()
    async def workspace(
        operation: str,
        workspace_slug: str = "",
        project_id: str = "",
        query: str = "",
        member_id: str = "",
    ) -> dict[str, Any]:
        """Canonical workspace/project/member operations for Plane.

        Operations:
        - list_workspaces
        - list_projects
        - get_project
        - get_project_bundle
        - list_workspace_members
        - list_project_members
        - resolve_workspace_member
        - resolve_project_member
        """

        client = get_client()

        if operation == "list_workspaces":
            try:
                raw = await api_get("/workspaces/")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise

                results = []
                for slug in _known_workspace_slugs():
                    try:
                        members = normalize_list(client.workspaces.get_members(workspace_slug=slug))
                    except Exception as member_exc:  # noqa: BLE001
                        logger.warning(
                            "workspace fallback: unable to inspect workspace=%s error=%s",
                            slug,
                            member_exc,
                        )
                        continue
                    results.append(
                        {
                            "slug": slug,
                            "name": display_name_from_slug(slug),
                            "member_count": len(members),
                            "id": slug,
                        }
                    )
                return {
                    "ok": True,
                    "data": results,
                    "warnings": [
                        "Plane does not expose workspace listing over PAT-authenticated /api/v1 on this deployment. Returned configured workspaces instead."
                    ],
                }

            items = normalize_list(raw)
            return {
                "ok": True,
                "data": [
                    {
                        "slug": extract(ws, "slug"),
                        "name": extract(ws, "name"),
                        "member_count": extract(ws, "total_members", 0),
                        "id": extract(ws, "id"),
                    }
                    for ws in items
                ],
            }

        if operation == "list_projects":
            items = normalize_list(client.projects.list(workspace_slug=workspace_slug))
            return {
                "ok": True,
                "data": [
                    {
                        "id": extract(proj, "id"),
                        "name": extract(proj, "name"),
                        "identifier": extract(proj, "identifier"),
                        "description": extract(proj, "description"),
                        "network": extract(proj, "network", 2),
                        "member_count": extract(proj, "total_members", 0),
                    }
                    for proj in items
                ],
            }

        if operation == "get_project":
            project = client.projects.retrieve(workspace_slug=workspace_slug, project_id=project_id)
            return {
                "ok": True,
                "data": {
                    "id": extract(project, "id"),
                    "name": extract(project, "name"),
                    "identifier": extract(project, "identifier"),
                    "description": extract(project, "description"),
                    "network": extract(project, "network", 2),
                    "member_count": extract(project, "total_members", 0),
                    "page_view": extract(project, "page_view", False),
                    "issue_views_view": extract(project, "issue_views_view", False),
                },
            }

        if operation == "get_project_bundle":
            project = client.projects.retrieve(workspace_slug=workspace_slug, project_id=project_id)
            states = normalize_list(client.states.list(workspace_slug=workspace_slug, project_id=project_id))
            labels = normalize_list(client.labels.list(workspace_slug=workspace_slug, project_id=project_id))
            work_items = normalize_list(client.work_items.list(workspace_slug=workspace_slug, project_id=project_id))
            return {
                "ok": True,
                "data": {
                    "project": {
                        "id": extract(project, "id"),
                        "name": extract(project, "name"),
                        "identifier": extract(project, "identifier"),
                        "description": extract(project, "description"),
                        "network": extract(project, "network", 2),
                    },
                    "states": [
                        {
                            "id": extract(state, "id"),
                            "name": extract(state, "name"),
                            "group": extract(state, "group"),
                            "color": extract(state, "color"),
                        }
                        for state in states
                    ],
                    "labels": [
                        {
                            "id": extract(label, "id"),
                            "name": extract(label, "name"),
                            "color": extract(label, "color"),
                        }
                        for label in labels
                    ],
                    "recent_work_items": [work_item_to_dict(item) for item in work_items[:20]],
                },
            }

        if operation == "list_workspace_members":
            return {
                "ok": True,
                "data": list_workspace_members_normalized(client, workspace_slug),
            }

        if operation == "list_project_members":
            return {
                "ok": True,
                "data": list_project_members_normalized(client, workspace_slug, project_id),
            }

        if operation == "resolve_workspace_member":
            member, error = resolve_member(client, workspace_slug=workspace_slug, query=query, member_id=member_id)
            if not member:
                return {"ok": False, "error": error}
            return {"ok": True, "data": member_to_dict(member)}

        if operation == "resolve_project_member":
            member, error = resolve_member(
                client,
                workspace_slug=workspace_slug,
                project_id=project_id,
                query=query,
                member_id=member_id,
            )
            if not member:
                return {"ok": False, "error": error}
            return {"ok": True, "data": member_to_dict(member)}

        return {"ok": False, "error": f"Unsupported workspace operation '{operation}'."}
