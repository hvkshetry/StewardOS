"""Canonical work-item tool for Plane MCP."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from plane.models.work_items import (
    CreateWorkItem,
    CreateWorkItemComment,
    UpdateWorkItem,
    WorkItemAttachmentUploadRequest,
)

from tools._helpers import audit_log, extract, normalize_list, work_item_to_dict
from tools._http import api_delete, api_get, api_patch, api_post, api_put
from tools._labels import fetch_existing_labels, resolve_label_ids
from tools._members import resolve_member

logger = logging.getLogger("plane-mcp.work_item")

_RELATION_TYPE_MAP = {
    "relates_to": "relates_to",
    "is_blocked_by": "blocked_by",
    "blocks": "blocking",
    "is_duplicate_of": "duplicate",
}


def _comments_to_dict(comments: list[Any]) -> list[dict[str, Any]]:
    results = []
    for comment in comments:
        actor_detail = extract(comment, "actor_detail", default={}) if isinstance(comment, dict) else {}
        results.append(
            {
                "id": extract(comment, "id"),
                "comment_html": extract(comment, "comment_html"),
                "actor": actor_detail.get("display_name") or extract(comment, "created_by"),
                "created_at": extract(comment, "created_at"),
            }
        )
    return results


def register_work_item_tools(mcp, get_client):
    @mcp.tool()
    async def work_item(
        operation: str,
        workspace_slug: str,
        project_id: str,
        work_item_id: str = "",
        title: str = "",
        description_html: str = "",
        priority: str = "",
        state_id: str = "",
        assignee_id: str = "",
        assignee_query: str = "",
        clear_assignees: bool = False,
        due_date: str = "",
        start_date: str = "",
        labels: list[str] | None = None,
        parent_id: str = "",
        limit: int = 100,
        query: str = "",
        external_source: str = "",
        external_id: str = "",
        comment_html: str = "",
        relation_type: str = "",
        related_work_item_id: str = "",
        url: str = "",
        link_title: str = "",
        filename: str = "",
        file_size: int = 0,
        mime_type: str = "",
        fields: list[str] | None = None,
        expand: list[str] | None = None,
        paperless_document_id: str = "",
        paperless_base_url: str = "",
        paperless_tags: str = "",
        paperless_document_date: str = "",
    ) -> dict[str, Any]:
        """Canonical work-item operations for Plane.

        Operations:
        - list, search, get, get_bundle, list_overdue
        - get_by_external, upsert_by_external
        - create, update, transition, complete, delete
        - comment, history
        - attach_link, attach_document, attach_file
        - list_relations, create_relation, delete_relation
        """

        client = get_client()
        expand = expand or []
        fields = fields or []

        if operation == "list":
            params: dict[str, Any] = {}
            if parent_id:
                params["parent"] = parent_id
            if assignee_id:
                params["assignee"] = assignee_id
            if state_id:
                params["state"] = state_id
            if external_source:
                params["external_source"] = external_source
            if external_id:
                params["external_id"] = external_id
            if expand:
                params["expand"] = ",".join(expand)
            if fields:
                params["fields"] = ",".join(fields)
            raw = await api_get(f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/", params=params)
            items = normalize_list(raw)
            if isinstance(raw, dict) and "results" in raw:
                items = raw["results"]
            return {"ok": True, "data": [work_item_to_dict(item) for item in items[: max(limit, 1)]]}

        if operation == "search":
            raw = client.work_items.search(workspace_slug=workspace_slug, query=query)
            items = getattr(raw, "issues", None)
            if items is None:
                items = normalize_list(raw)
            return {
                "ok": True,
                "data": [
                    {
                        "id": extract(item, "id"),
                        "name": extract(item, "name"),
                        "project_id": extract(item, "project_id", extract(item, "project")),
                        "state": extract(item, "state"),
                        "priority": extract(item, "priority"),
                        "workspace_slug": extract(item, "workspace_slug", workspace_slug),
                    }
                    for item in items[: max(limit, 1)]
                ],
            }

        if operation == "get":
            params = {}
            if expand:
                params["expand"] = ",".join(expand)
            if fields:
                params["fields"] = ",".join(fields)
            raw = await api_get(
                f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/",
                params=params,
            )
            return {"ok": True, "data": work_item_to_dict(raw)}

        if operation == "get_bundle":
            params = {"expand": "coordination"} if not expand else {"expand": ",".join(expand)}
            item = await api_get(
                f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/",
                params=params,
            )
            all_items = normalize_list(client.work_items.list(workspace_slug=workspace_slug, project_id=project_id))
            children = [work_item_to_dict(candidate) for candidate in all_items if extract(candidate, "parent") == work_item_id]
            comments = normalize_list(
                client.work_items.comments.list(
                    workspace_slug=workspace_slug,
                    project_id=project_id,
                    work_item_id=work_item_id,
                )
            )
            return {
                "ok": True,
                "data": {
                    "work_item": work_item_to_dict(item),
                    "child_work_items": children,
                    "comments": _comments_to_dict(comments),
                },
            }

        if operation == "list_overdue":
            states = normalize_list(client.states.list(workspace_slug=workspace_slug, project_id=project_id))
            terminal_state_ids = {
                str(extract(state, "id"))
                for state in states
                if extract(state, "group") in ("completed", "cancelled")
            }
            items = normalize_list(client.work_items.list(workspace_slug=workspace_slug, project_id=project_id))
            today_str = date.today().isoformat()
            overdue = []
            for item in items:
                target = extract(item, "target_date")
                state = str(extract(item, "state", ""))
                if not target:
                    continue
                if str(target)[:10] < today_str and state not in terminal_state_ids:
                    overdue.append(work_item_to_dict(item))
            return {"ok": True, "data": overdue}

        if operation == "get_by_external":
            raw = await api_get(
                f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/",
                params={"external_source": external_source, "external_id": external_id, "expand": ",".join(expand)},
            )
            return {"ok": True, "data": work_item_to_dict(raw)}

        if operation == "upsert_by_external":
            payload: dict[str, Any] = {
                "external_source": external_source,
                "external_id": external_id,
                "name": title,
            }
            if description_html:
                payload["description_html"] = description_html
            if priority:
                payload["priority"] = priority.lower()
            if state_id:
                payload["state"] = state_id
            if parent_id:
                payload["parent"] = parent_id
            if start_date:
                payload["start_date"] = start_date
            if due_date:
                payload["target_date"] = due_date
            if labels is not None:
                existing_labels = fetch_existing_labels(client, workspace_slug, project_id)
                payload["labels"] = resolve_label_ids(client, workspace_slug, project_id, labels, existing_labels)
            if clear_assignees:
                payload["assignees"] = []
            elif assignee_id or assignee_query:
                if assignee_query and not assignee_id:
                    member, error = resolve_member(
                        client,
                        workspace_slug=workspace_slug,
                        project_id=project_id,
                        query=assignee_query,
                    )
                    if not member:
                        return {"ok": False, "error": error}
                    assignee_id = extract(member, "id")
                payload["assignees"] = [assignee_id]
            result = await api_put(
                f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/",
                payload,
            )
            return {"ok": True, "data": work_item_to_dict(result)}

        if operation == "create":
            audit_log("work_item.create", workspace_slug, {"project_id": project_id, "title": title})
            create_kwargs: dict[str, Any] = {"name": title}
            if description_html:
                create_kwargs["description_html"] = description_html
            if priority:
                create_kwargs["priority"] = priority.lower()
            if state_id:
                create_kwargs["state"] = state_id
            if parent_id:
                create_kwargs["parent"] = parent_id
            if start_date:
                create_kwargs["start_date"] = start_date
            if due_date:
                create_kwargs["target_date"] = due_date
            if external_source:
                create_kwargs["external_source"] = external_source
            if external_id:
                create_kwargs["external_id"] = external_id
            if labels is not None:
                existing_labels = fetch_existing_labels(client, workspace_slug, project_id)
                create_kwargs["labels"] = resolve_label_ids(client, workspace_slug, project_id, labels, existing_labels)
            if clear_assignees:
                create_kwargs["assignees"] = []
            elif assignee_id or assignee_query:
                if assignee_query and not assignee_id:
                    member, error = resolve_member(
                        client,
                        workspace_slug=workspace_slug,
                        project_id=project_id,
                        query=assignee_query,
                    )
                    if not member:
                        return {"ok": False, "error": error}
                    assignee_id = extract(member, "id")
                create_kwargs["assignees"] = [assignee_id]
            result = client.work_items.create(
                workspace_slug=workspace_slug,
                project_id=project_id,
                data=CreateWorkItem(**create_kwargs),
            )
            return {"ok": True, "data": work_item_to_dict(result)}

        if operation in {"update", "transition"}:
            audit_log("work_item.update", workspace_slug, {"project_id": project_id, "work_item_id": work_item_id})
            update_kwargs: dict[str, Any] = {}
            if title:
                update_kwargs["name"] = title
            if description_html:
                update_kwargs["description_html"] = description_html
            if priority:
                update_kwargs["priority"] = priority.lower()
            if state_id:
                update_kwargs["state"] = state_id
            if parent_id:
                update_kwargs["parent"] = parent_id
            if start_date:
                update_kwargs["start_date"] = start_date
            if due_date:
                update_kwargs["target_date"] = due_date
            if labels is not None:
                existing_labels = fetch_existing_labels(client, workspace_slug, project_id)
                update_kwargs["labels"] = resolve_label_ids(client, workspace_slug, project_id, labels, existing_labels)
            if clear_assignees:
                update_kwargs["assignees"] = []
            elif assignee_id or assignee_query:
                if assignee_query and not assignee_id:
                    member, error = resolve_member(
                        client,
                        workspace_slug=workspace_slug,
                        project_id=project_id,
                        query=assignee_query,
                    )
                    if not member:
                        return {"ok": False, "error": error}
                    assignee_id = extract(member, "id")
                update_kwargs["assignees"] = [assignee_id]
            result = client.work_items.update(
                workspace_slug=workspace_slug,
                project_id=project_id,
                work_item_id=work_item_id,
                data=UpdateWorkItem(**update_kwargs),
            )
            return {"ok": True, "data": work_item_to_dict(result)}

        if operation == "complete":
            states = normalize_list(client.states.list(workspace_slug=workspace_slug, project_id=project_id))
            done_state_id = next(
                (str(extract(state, "id")) for state in states if extract(state, "group") == "completed"),
                "",
            )
            if not done_state_id:
                return {"ok": False, "error": "No completed state exists in this project."}
            result = client.work_items.update(
                workspace_slug=workspace_slug,
                project_id=project_id,
                work_item_id=work_item_id,
                data=UpdateWorkItem(state=done_state_id),
            )
            return {"ok": True, "data": work_item_to_dict(result)}

        if operation == "delete":
            audit_log("work_item.delete", workspace_slug, {"project_id": project_id, "work_item_id": work_item_id})
            await api_delete(f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/")
            return {"ok": True, "data": {"id": work_item_id, "status": "deleted"}}

        if operation == "comment":
            result = client.work_items.comments.create(
                workspace_slug=workspace_slug,
                project_id=project_id,
                work_item_id=work_item_id,
                data=CreateWorkItemComment(comment_html=comment_html),
            )
            return {
                "ok": True,
                "data": {
                    "id": extract(result, "id"),
                    "work_item_id": work_item_id,
                    "comment_html": comment_html,
                },
            }

        if operation == "history":
            raw = await api_get(
                f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/activities/"
            )
            activities = normalize_list(raw)
            return {
                "ok": True,
                "data": [
                    {
                        "id": extract(activity, "id"),
                        "verb": extract(activity, "verb"),
                        "field": extract(activity, "field"),
                        "old_value": extract(activity, "old_value"),
                        "new_value": extract(activity, "new_value"),
                        "actor": extract(activity, "actor"),
                        "created_at": extract(activity, "created_at"),
                    }
                    for activity in activities
                ],
            }

        if operation == "attach_link":
            result = await api_post(
                f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/links/",
                {"url": url, **({"title": link_title} if link_title else {})},
            )
            return {
                "ok": True,
                "data": {
                    "id": extract(result, "id"),
                    "work_item_id": work_item_id,
                    "url": url,
                    "title": link_title,
                },
            }

        if operation == "attach_document":
            parts = [f"[Paperless #{paperless_document_id}]", link_title or title or "Document"]
            if paperless_tags:
                parts.append(f"tags:{paperless_tags}")
            if paperless_document_date:
                parts.append(f"date:{paperless_document_date}")
            rich_title = " | ".join(parts)
            doc_url = (
                f"{paperless_base_url.rstrip('/')}/documents/{paperless_document_id}/details"
                if paperless_base_url
                else f"/documents/{paperless_document_id}/details"
            )
            result = await api_post(
                f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/links/",
                {"url": doc_url, "title": rich_title},
            )
            return {
                "ok": True,
                "data": {
                    "id": extract(result, "id"),
                    "work_item_id": work_item_id,
                    "document_id": paperless_document_id,
                    "url": doc_url,
                    "title": rich_title,
                },
            }

        if operation == "attach_file":
            result = client.work_items.attachments.create(
                workspace_slug=workspace_slug,
                project_id=project_id,
                work_item_id=work_item_id,
                data=WorkItemAttachmentUploadRequest(
                    name=filename,
                    size=file_size,
                    **({"type": mime_type} if mime_type else {}),
                    **({"external_id": external_id} if external_id else {}),
                    **({"external_source": external_source} if external_source else {}),
                ),
            )
            return {
                "ok": True,
                "data": {
                    "id": extract(result, "id"),
                    "work_item_id": work_item_id,
                    "filename": filename,
                    "file_size": file_size,
                    "mime_type": mime_type,
                },
            }

        if operation == "list_relations":
            raw = await api_get(
                f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/relations/"
            )
            results = []
            relation_groups = {
                "blocking": "blocks",
                "blocked_by": "is_blocked_by",
                "duplicate": "is_duplicate_of",
                "relates_to": "relates_to",
            }
            if isinstance(raw, dict) and any(key in raw for key in relation_groups):
                for raw_key, normalized_type in relation_groups.items():
                    for related_issue in raw.get(raw_key, []) or []:
                        results.append(
                            {
                                "id": related_issue,
                                "relation_type": normalized_type,
                                "related_issue": related_issue,
                                "issue": work_item_id,
                            }
                        )
            else:
                items = normalize_list(raw)
                results = [
                    {
                        "id": extract(item, "id"),
                        "relation_type": extract(item, "relation_type"),
                        "related_issue": extract(item, "related_issue"),
                        "issue": extract(item, "issue"),
                        "created_at": extract(item, "created_at"),
                    }
                    for item in items
                ]
            return {"ok": True, "data": results}

        if operation == "create_relation":
            mapped_type = _RELATION_TYPE_MAP.get(relation_type)
            if not mapped_type:
                return {"ok": False, "error": f"Unsupported relation_type '{relation_type}'."}
            result = await api_post(
                f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/relations/",
                {"relation_type": mapped_type, "issues": [related_work_item_id]},
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

        if operation == "delete_relation":
            await api_post(
                f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/relations/remove/",
                {"related_issue": related_work_item_id or work_item_id},
            )
            return {
                "ok": True,
                "data": {
                    "work_item_id": work_item_id,
                    "relation_id": related_work_item_id or work_item_id,
                    "deleted": True,
                },
            }

        return {"ok": False, "error": f"Unsupported work_item operation '{operation}'."}
