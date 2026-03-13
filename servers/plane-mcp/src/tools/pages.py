"""Page management tools for Plane.

Per-project pages serve as a knowledge layer — notes co-locate with
work items so agents can retrieve context from their working project.

SDK covers create and retrieve; list, update, archive, and delete use
direct HTTP against the Plane REST API.
"""

from __future__ import annotations

import logging
from typing import Any

from plane.models.pages import CreatePage
from tools._helpers import audit_log, extract, home_workspace, normalize_list
from tools._http import api_delete, api_get, api_patch, api_post

logger = logging.getLogger("plane-mcp.pages")


def register_page_tools(mcp, get_client):
    @mcp.tool()
    async def list_project_pages(
        workspace_slug: str,
        project_id: str,
    ) -> dict[str, Any]:
        """List all pages in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
        """
        path = f"/workspaces/{workspace_slug}/projects/{project_id}/pages/"
        raw = await api_get(path)
        items = normalize_list(raw)
        results = []
        for p in items:
            results.append({
                "id": extract(p, "id"),
                "name": extract(p, "name"),
                "owned_by": extract(p, "owned_by"),
                "access": extract(p, "access"),
                "is_locked": extract(p, "is_locked", False),
                "archived_at": extract(p, "archived_at"),
                "created_at": extract(p, "created_at"),
                "updated_at": extract(p, "updated_at"),
            })

        logger.info(
            "list_project_pages: workspace=%s project=%s found %d pages",
            workspace_slug,
            project_id,
            len(results),
        )
        return {"ok": True, "data": results}

    @mcp.tool()
    async def create_project_page(
        workspace_slug: str,
        project_id: str,
        name: str,
        content_html: str = "",
    ) -> dict[str, Any]:
        """Create a new page in a project.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            name: Page title.
            content_html: Page content in HTML.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot create page in workspace '{workspace_slug}' — "
                    f"pages must be created in home workspace '{home}'."
                ),
            }

        audit_log("create_project_page", workspace_slug, {
            "project_id": project_id,
            "name": name,
        })

        client = get_client()
        create_kwargs: dict[str, Any] = {
            "name": name,
            "description_html": content_html or "",
        }

        page = client.pages.create_project_page(
            workspace_slug=workspace_slug,
            project_id=project_id,
            data=CreatePage(**create_kwargs),
        )

        page_id = extract(page, "id")
        logger.info(
            "create_project_page: created page=%s in project=%s",
            page_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": page_id,
                "name": name,
            },
        }

    @mcp.tool()
    async def get_project_page(
        workspace_slug: str,
        project_id: str,
        page_id: str,
    ) -> dict[str, Any]:
        """Retrieve a page with its content.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            page_id: The page UUID.
        """
        client = get_client()
        page = client.pages.retrieve_project_page(
            workspace_slug=workspace_slug,
            project_id=project_id,
            page_id=page_id,
        )

        data = {
            "id": extract(page, "id"),
            "name": extract(page, "name"),
            "description_html": extract(page, "description_html"),
            "owned_by": extract(page, "owned_by"),
            "access": extract(page, "access"),
            "is_locked": extract(page, "is_locked", False),
            "created_at": extract(page, "created_at"),
            "updated_at": extract(page, "updated_at"),
        }

        logger.info(
            "get_project_page: workspace=%s project=%s page=%s",
            workspace_slug,
            project_id,
            page_id,
        )
        return {"ok": True, "data": data}

    @mcp.tool()
    async def update_project_page(
        workspace_slug: str,
        project_id: str,
        page_id: str,
        name: str = "",
        content_html: str = "",
    ) -> dict[str, Any]:
        """Update a page's name and/or content.

        At least one of name or content_html must be provided.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            page_id: The page UUID.
            name: New page title (leave empty to keep current).
            content_html: New page content in HTML (leave empty to keep current).
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot update page in workspace '{workspace_slug}' — "
                    f"pages must be updated in home workspace '{home}'."
                ),
            }

        audit_log("update_project_page", workspace_slug, {
            "project_id": project_id,
            "page_id": page_id,
        })

        patch_data: dict[str, Any] = {}
        if name:
            patch_data["name"] = name
        if content_html:
            patch_data["description_html"] = content_html

        if not patch_data:
            return {
                "ok": False,
                "error": "At least one of name or content_html must be provided.",
            }

        path = f"/workspaces/{workspace_slug}/projects/{project_id}/pages/{page_id}/"
        result = await api_patch(path, patch_data)

        logger.info(
            "update_project_page: updated page=%s in project=%s",
            page_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": extract(result, "id", page_id),
                "name": extract(result, "name"),
                "updated_at": extract(result, "updated_at"),
            },
        }

    @mcp.tool()
    async def archive_project_page(
        workspace_slug: str,
        project_id: str,
        page_id: str,
    ) -> dict[str, Any]:
        """Archive a page. Archived pages can be restored or permanently deleted.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            page_id: The page UUID to archive.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot archive page in workspace '{workspace_slug}' — "
                    f"pages must be archived in home workspace '{home}'."
                ),
            }

        audit_log("archive_project_page", workspace_slug, {
            "project_id": project_id,
            "page_id": page_id,
        })

        path = f"/workspaces/{workspace_slug}/projects/{project_id}/pages/{page_id}/archive/"
        await api_post(path, {})

        logger.info(
            "archive_project_page: archived page=%s in project=%s",
            page_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": page_id,
                "status": "archived",
            },
        }

    @mcp.tool()
    async def delete_project_page(
        workspace_slug: str,
        project_id: str,
        page_id: str,
    ) -> dict[str, Any]:
        """Delete a page. Archives it first if not already archived, then deletes.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            page_id: The page UUID to delete.
        """
        home = home_workspace()
        if home and workspace_slug != home:
            return {
                "ok": False,
                "error": (
                    f"Cannot delete page in workspace '{workspace_slug}' — "
                    f"pages must be deleted in home workspace '{home}'."
                ),
            }

        audit_log("delete_project_page", workspace_slug, {
            "project_id": project_id,
            "page_id": page_id,
        })

        # Archive first (Plane requires archiving before deletion)
        archive_path = (
            f"/workspaces/{workspace_slug}/projects/{project_id}"
            f"/pages/{page_id}/archive/"
        )
        try:
            await api_post(archive_path, {})
        except Exception:
            pass  # May already be archived

        delete_path = (
            f"/workspaces/{workspace_slug}/projects/{project_id}"
            f"/pages/{page_id}/"
        )
        await api_delete(delete_path)

        logger.info(
            "delete_project_page: deleted page=%s from project=%s",
            page_id,
            project_id,
        )
        return {
            "ok": True,
            "data": {
                "id": page_id,
                "status": "deleted",
            },
        }
