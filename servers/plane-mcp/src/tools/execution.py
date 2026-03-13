"""Execution tools for Plane work item state transitions and updates.

All write operations are audit-logged with workspace attribution.
"""

from __future__ import annotations

import logging
from typing import Any

from plane.models.work_items import (
    CreateWorkItemComment,
    UpdateWorkItem,
    WorkItemAttachmentUploadRequest,
)
from tools._helpers import audit_log, extract, normalize_list
from tools._http import api_post

logger = logging.getLogger("plane-mcp.execution")


def register_execution_tools(mcp, get_client):
    @mcp.tool()
    async def update_task_state(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
        state_id: str,
    ) -> dict[str, Any]:
        """Transition a work item to a new state.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The work item UUID to update.
            state_id: The target state UUID to transition to.
        """
        audit_log("update_task_state", workspace_slug, {
            "project_id": project_id,
            "work_item_id": work_item_id,
            "state_id": state_id,
        })

        client = get_client()
        updated = client.work_items.update(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=UpdateWorkItem(state=state_id),
        )

        updated_id = extract(updated, "id", work_item_id)
        logger.info(
            "update_task_state: work_item=%s transitioned to state=%s",
            updated_id,
            state_id,
        )
        return {
            "ok": True,
            "data": {
                "id": updated_id,
                "state": state_id,
            },
        }

    @mcp.tool()
    async def add_task_comment(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
        comment_html: str,
    ) -> dict[str, Any]:
        """Add a comment to a work item.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The work item UUID to comment on.
            comment_html: The comment body in HTML.
        """
        audit_log("add_task_comment", workspace_slug, {
            "project_id": project_id,
            "work_item_id": work_item_id,
        })

        client = get_client()
        result = client.work_items.comments.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=CreateWorkItemComment(comment_html=comment_html),
        )

        comment_id = extract(result, "id")
        logger.info(
            "add_task_comment: comment=%s added to work_item=%s",
            comment_id,
            work_item_id,
        )
        return {
            "ok": True,
            "data": {
                "id": comment_id,
                "work_item_id": work_item_id,
                "comment_html": comment_html,
            },
        }

    @mcp.tool()
    async def complete_task(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
    ) -> dict[str, Any]:
        """Mark a work item as done by finding the 'Done' state and transitioning to it.

        Looks up the project's states, finds the one in the 'completed' group
        (typically named 'Done'), and sets the work item to that state.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The work item UUID to complete.
        """
        audit_log("complete_task", workspace_slug, {
            "project_id": project_id,
            "work_item_id": work_item_id,
        })

        client = get_client()

        states = normalize_list(
            client.states.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
            )
        )

        done_state_id = None
        for s in states:
            group = extract(s, "group")
            name = extract(s, "name")
            s_id = extract(s, "id")
            if group == "completed" or name.lower() == "done":
                done_state_id = s_id
                break

        if not done_state_id:
            return {
                "ok": False,
                "error": {
                    "code": "no_done_state",
                    "message": (
                        f"No 'completed' group state found in project {project_id}. "
                        "Configure a state with group='completed' in Plane."
                    ),
                },
            }

        updated = client.work_items.update(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=UpdateWorkItem(state=done_state_id),
        )

        updated_id = extract(updated, "id", work_item_id)
        logger.info(
            "complete_task: work_item=%s completed (state=%s)",
            updated_id,
            done_state_id,
        )
        return {
            "ok": True,
            "data": {
                "id": updated_id,
                "state": done_state_id,
                "status": "completed",
            },
        }

    @mcp.tool()
    async def attach_external_link(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
        url: str,
        title: str = "",
    ) -> dict[str, Any]:
        """Attach an external link to a work item.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The work item UUID to attach the link to.
            url: The external URL to link.
            title: Display title for the link.
        """
        audit_log("attach_external_link", workspace_slug, {
            "project_id": project_id,
            "work_item_id": work_item_id,
            "url": url,
        })

        # Use direct HTTP because SDK CreateWorkItemLink only has url field
        # (title is silently dropped via extra="ignore")
        data: dict[str, str] = {"url": url}
        if title:
            data["title"] = title

        path = (
            f"/workspaces/{workspace_slug}/projects/{project_id}"
            f"/work-items/{work_item_id}/links/"
        )
        result = await api_post(path, data)

        link_id = extract(result, "id")
        logger.info(
            "attach_external_link: link=%s attached to work_item=%s",
            link_id,
            work_item_id,
        )
        return {
            "ok": True,
            "data": {
                "id": link_id,
                "work_item_id": work_item_id,
                "url": url,
                "title": title,
            },
        }

    @mcp.tool()
    async def attach_paperless_document(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
        document_id: str,
        title: str,
        paperless_url: str = "",
        tags: str = "",
        document_date: str = "",
    ) -> dict[str, Any]:
        """Attach a Paperless-ngx document reference to a work item as a rich external link.

        Creates an external link with structured metadata (document ID, tags, date)
        embedded in the title for easy identification and cross-referencing.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The work item UUID to attach the document to.
            document_id: The Paperless-ngx document ID.
            title: Document title / display name.
            paperless_url: Base URL of the Paperless instance (e.g. https://docs.example.com).
            tags: Comma-separated document tags for context.
            document_date: Document date (ISO format) for temporal context.
        """
        audit_log("attach_paperless_document", workspace_slug, {
            "project_id": project_id,
            "work_item_id": work_item_id,
            "document_id": document_id,
        })

        # Build a metadata-rich link title
        parts = [f"[Paperless #{document_id}]", title]
        if tags:
            parts.append(f"tags:{tags}")
        if document_date:
            parts.append(f"date:{document_date}")
        rich_title = " | ".join(parts)

        # Construct document URL
        if paperless_url:
            doc_url = f"{paperless_url.rstrip('/')}/documents/{document_id}/details"
        else:
            doc_url = f"/documents/{document_id}/details"

        # Use direct HTTP because SDK CreateWorkItemLink only has url field
        path = (
            f"/workspaces/{workspace_slug}/projects/{project_id}"
            f"/work-items/{work_item_id}/links/"
        )
        result = await api_post(path, {"url": doc_url, "title": rich_title})

        link_id = extract(result, "id")
        logger.info(
            "attach_paperless_document: doc=%s linked to work_item=%s",
            document_id,
            work_item_id,
        )
        return {
            "ok": True,
            "data": {
                "id": link_id,
                "work_item_id": work_item_id,
                "document_id": document_id,
                "url": doc_url,
                "title": rich_title,
            },
        }

    @mcp.tool()
    async def attach_work_item_file(
        workspace_slug: str,
        project_id: str,
        work_item_id: str,
        filename: str,
        file_size: int,
        mime_type: str = "",
        external_id: str = "",
        external_source: str = "",
    ) -> dict[str, Any]:
        """Register a file attachment on a work item.

        Creates attachment metadata via the SDK. The actual file must be
        uploaded separately or referenced via external_id/external_source.

        Args:
            workspace_slug: The workspace slug.
            project_id: The project UUID.
            work_item_id: The work item UUID to attach the file to.
            filename: Original filename of the asset.
            file_size: File size in bytes.
            mime_type: MIME type of the file (e.g. 'application/pdf').
            external_id: External identifier for the asset.
            external_source: External source system name.
        """
        audit_log("attach_work_item_file", workspace_slug, {
            "project_id": project_id,
            "work_item_id": work_item_id,
            "filename": filename,
        })

        client = get_client()
        upload_kwargs: dict[str, Any] = {
            "name": filename,
            "size": file_size,
        }
        if mime_type:
            upload_kwargs["type"] = mime_type
        if external_id:
            upload_kwargs["external_id"] = external_id
        if external_source:
            upload_kwargs["external_source"] = external_source

        result = client.work_items.attachments.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=WorkItemAttachmentUploadRequest(**upload_kwargs),
        )

        attachment_id = extract(result, "id")
        logger.info(
            "attach_work_item_file: attached %s to work_item=%s",
            filename,
            work_item_id,
        )
        return {
            "ok": True,
            "data": {
                "id": attachment_id,
                "work_item_id": work_item_id,
                "filename": filename,
                "file_size": file_size,
                "mime_type": mime_type,
            },
        }
