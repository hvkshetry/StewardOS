"""Relation tools for work item dependency graphs.

Provides tools to create, list, and delete relations between work items.
Supports relation types: relates_to, is_blocked_by, blocks, is_duplicate_of.

Uses app-level /issues/{id}/issue-relation/ paths because the /work-items/
relation routes do not exist in Plane v1.2.x. Will migrate to SDK calls
when routes appear in a future Plane release.
"""

from __future__ import annotations

import logging
from typing import Any

from tools._helpers import audit_log, extract, home_workspace
from tools._http import api_delete, api_get, api_post

logger = logging.getLogger("plane-mcp.relations")

_VALID_RELATION_TYPES = {
    "relates_to",
    "is_blocked_by",
    "blocks",
    "is_duplicate_of",
}

# App-level path template (not /work-items/ — routes missing in v1.2.x)
_RELATION_PATH = (
    "/workspaces/{workspace}/projects/{project}/issues/{issue}/issue-relation/"
)


def _relation_base_path(
    workspace_slug: str,
    project_id: str,
    work_item_id: str,
) -> str:
    return _RELATION_PATH.format(
        workspace=workspace_slug,
        project=project_id,
        issue=work_item_id,
    )


def register_relation_tools(mcp, get_client):
    @mcp.tool()
    async def list_work_item_relations(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
    ) -> dict[str, Any]:
        """List all relations for a work item.

        Returns incoming and outgoing relations showing dependency
        and duplication links.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The work item UUID.
        """
        path = _relation_base_path(workspace_slug, project_id, work_item_id)
        data = await api_get(path)

        results = []
        items = data if isinstance(data, list) else data.get("results", [])
        for r in items:
            results.append({
                "id": extract(r, "id"),
                "relation_type": extract(r, "relation_type"),
                "related_issue": extract(r, "related_issue"),
                "issue": extract(r, "issue"),
                "created_at": extract(r, "created_at"),
            })

        logger.info(
            "list_work_item_relations: work_item=%s found %d relations",
            work_item_id,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def create_work_item_relation(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
        related_work_item_id: str,
        relation_type: str,
    ) -> dict[str, Any]:
        """Create a relation between two work items.

        Supports dependency tracking and duplicate detection across
        a project's work items.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The source work item UUID.
            related_work_item_id: The target work item UUID.
            relation_type: One of: relates_to, is_blocked_by, blocks, is_duplicate_of.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create relation in workspace '{workspace_slug}' — "
                    f"relations must be created in home workspace '{home}'."
                ),
            }

        if relation_type not in _VALID_RELATION_TYPES:
            valid = ", ".join(sorted(_VALID_RELATION_TYPES))
            return {
                "ok": False,
                "error": f"Invalid relation_type '{relation_type}'. Valid: {valid}",
            }

        audit_log("create_work_item_relation", workspace_slug, {
            "work_item_id": work_item_id,
            "related_work_item_id": related_work_item_id,
            "relation_type": relation_type,
        })

        path = _relation_base_path(workspace_slug, project_id, work_item_id)
        result = await api_post(path, {
            "related_list": [
                {
                    "issue": related_work_item_id,
                    "relation_type": relation_type,
                }
            ],
        })

        logger.info(
            "create_work_item_relation: %s -[%s]-> %s",
            work_item_id,
            relation_type,
            related_work_item_id,
        )
        return {
            "ok": True,
            "data": {
                "work_item_id": work_item_id,
                "related_work_item_id": related_work_item_id,
                "relation_type": relation_type,
                "result": result,
            },
        }

    @mcp.tool()
    async def delete_work_item_relation(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
        relation_id: str,
    ) -> dict[str, Any]:
        """Delete a relation between work items.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The work item UUID that owns the relation.
            relation_id: The relation UUID to delete.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot delete relation in workspace '{workspace_slug}' — "
                    f"relations must be deleted in home workspace '{home}'."
                ),
            }

        audit_log("delete_work_item_relation", workspace_slug, {
            "work_item_id": work_item_id,
            "relation_id": relation_id,
        })

        path = _relation_base_path(workspace_slug, project_id, work_item_id)
        await api_delete(f"{path}{relation_id}/")

        logger.info(
            "delete_work_item_relation: removed relation %s from work_item %s",
            relation_id,
            work_item_id,
        )
        return {
            "ok": True,
            "data": {
                "work_item_id": work_item_id,
                "relation_id": relation_id,
                "deleted": True,
            },
        }
