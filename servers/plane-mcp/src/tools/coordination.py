"""Canonical coordination tool for Plane MCP."""

from __future__ import annotations

import logging
from typing import Any

from plane.models.work_items import CreateWorkItem

from tools._helpers import audit_log, extract, normalize_list, work_item_to_dict
from tools._http import api_get, api_patch, api_post, api_put
from tools._labels import fetch_existing_labels, resolve_label_ids
from tools._members import member_to_dict, resolve_member

logger = logging.getLogger("plane-mcp.coordination")


def _coordination_path(workspace_slug: str, project_id: str, work_item_id: str, action: str = "") -> str:
    base = f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/coordination/"
    if action:
        return f"{base}{action}/"
    return base


def _normalize_assignee_ids(value: list[str] | None) -> list[str]:
    return [str(item) for item in (value or []) if str(item).strip()]


def _resolve_single_assignee(
    client: Any,
    workspace_slug: str,
    project_id: str,
    *,
    assignee_id: str = "",
    assignee_query: str = "",
) -> tuple[str, dict[str, Any] | None, str | None]:
    if assignee_query and not assignee_id:
        member, error = resolve_member(
            client,
            workspace_slug=workspace_slug,
            project_id=project_id,
            query=assignee_query,
        )
        if not member:
            return "", None, error
        return str(extract(member, "id")), member_to_dict(member), None
    if assignee_id:
        member, error = resolve_member(
            client,
            workspace_slug=workspace_slug,
            project_id=project_id,
            member_id=assignee_id,
        )
        if not member:
            return "", None, error
        return str(extract(member, "id")), member_to_dict(member), None
    return "", None, None


def _build_coordination_payload(
    *,
    route_to: str = "",
    reply_identity: str = "",
    coordination_status: str = "",
    approver_id: str = "",
    allowed_responder: str = "",
    waiting_on: str = "",
    waiting_since: str = "",
    claimed_by_id: str = "",
    lease_seconds: int = 0,
    metadata: dict[str, Any] | None = None,
    assignee_ids: list[str] | None = None,
    clear_assignees: bool = False,
    comment_html: str = "",
    channel: str = "",
    message_id: str = "",
    note: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if route_to:
        payload["route_to"] = route_to
    if reply_identity:
        payload["reply_identity"] = reply_identity
    if coordination_status:
        payload["coordination_status"] = coordination_status
    if approver_id:
        payload["approver_id"] = approver_id
    if allowed_responder:
        payload["allowed_responder"] = allowed_responder
    if waiting_on:
        payload["waiting_on"] = waiting_on
    if waiting_since:
        payload["waiting_since"] = waiting_since
    if claimed_by_id:
        payload["claimed_by_id"] = claimed_by_id
    if lease_seconds:
        payload["lease_seconds"] = lease_seconds
    if metadata is not None:
        payload["metadata"] = metadata
    normalized_assignee_ids = _normalize_assignee_ids(assignee_ids)
    if normalized_assignee_ids:
        payload["assignee_ids"] = normalized_assignee_ids
    if clear_assignees:
        payload["clear_assignees"] = True
    if comment_html:
        payload["comment_html"] = comment_html
    if channel:
        payload["channel"] = channel
    if message_id:
        payload["message_id"] = message_id
    if note:
        payload["note"] = note
    return payload


def register_coordination_tools(mcp, get_client):
    @mcp.tool()
    async def coordination(
        operation: str,
        workspace_slug: str,
        project_id: str,
        work_item_id: str = "",
        title: str = "",
        description_html: str = "",
        priority: str = "",
        parent_id: str = "",
        route_to: str = "",
        reply_identity: str = "",
        coordination_status: str = "",
        approver_id: str = "",
        allowed_responder: str = "",
        waiting_on: str = "",
        waiting_since: str = "",
        claimed_by_id: str = "",
        lease_seconds: int = 3600,
        assignee_id: str = "",
        assignee_query: str = "",
        assignee_ids: list[str] | None = None,
        clear_assignees: bool = False,
        metadata: dict[str, Any] | None = None,
        comment_html: str = "",
        external_source: str = "",
        external_id: str = "",
        labels: list[str] | None = None,
        limit: int = 100,
        channel: str = "",
        message_id: str = "",
        note: str = "",
        agent_tasks: list[dict[str, Any]] | None = None,
        human_tasks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Canonical coordination operations for Plane.

        Operations:
        - get, set
        - claim, handoff, release
        - queue
        - request_approval, approve, reject
        - record_reply
        - delegate
        """

        client = get_client()

        if operation == "get":
            raw = await api_get(_coordination_path(workspace_slug, project_id, work_item_id))
            return {"ok": True, "data": raw}

        if operation == "set":
            payload = _build_coordination_payload(
                route_to=route_to,
                reply_identity=reply_identity,
                coordination_status=coordination_status,
                approver_id=approver_id,
                allowed_responder=allowed_responder,
                waiting_on=waiting_on,
                waiting_since=waiting_since,
                claimed_by_id=claimed_by_id,
                metadata=metadata,
            )
            raw = await api_patch(_coordination_path(workspace_slug, project_id, work_item_id), payload)
            return {"ok": True, "data": raw}

        if operation in {
            "claim",
            "handoff",
            "release",
            "request_approval",
            "approve",
            "reject",
            "record_reply",
        }:
            resolved_assignee_id = assignee_id
            resolved_assignee = None
            if operation == "handoff" and assignee_query and not assignee_id:
                resolved_assignee_id, resolved_assignee, error = _resolve_single_assignee(
                    client,
                    workspace_slug,
                    project_id,
                    assignee_query=assignee_query,
                )
                if error:
                    return {"ok": False, "error": error}
            elif operation == "handoff" and assignee_id:
                resolved_assignee_id, resolved_assignee, error = _resolve_single_assignee(
                    client,
                    workspace_slug,
                    project_id,
                    assignee_id=assignee_id,
                )
                if error:
                    return {"ok": False, "error": error}

            resolved_assignee_ids = _normalize_assignee_ids(assignee_ids)
            if resolved_assignee_id:
                resolved_assignee_ids = [resolved_assignee_id]

            payload = _build_coordination_payload(
                route_to=route_to,
                reply_identity=reply_identity,
                coordination_status=coordination_status,
                approver_id=approver_id,
                allowed_responder=allowed_responder,
                waiting_on=waiting_on,
                waiting_since=waiting_since,
                claimed_by_id=claimed_by_id,
                lease_seconds=lease_seconds,
                metadata=metadata,
                assignee_ids=resolved_assignee_ids,
                clear_assignees=clear_assignees,
                comment_html=comment_html,
                channel=channel,
                message_id=message_id,
                note=note,
            )
            raw = await api_post(
                _coordination_path(workspace_slug, project_id, work_item_id, operation.replace("request_approval", "request-approval").replace("record_reply", "record-reply")),
                payload,
            )
            result: dict[str, Any] = {"ok": True, "data": raw}
            if resolved_assignee:
                result["resolved_assignee"] = resolved_assignee
            return result

        if operation == "queue":
            params: dict[str, Any] = {"expand": "coordination"}
            if route_to:
                params["route_to"] = route_to
            if coordination_status:
                params["coordination_status"] = coordination_status
            if approver_id:
                params["approver_id"] = approver_id
            if claimed_by_id:
                params["claimed_by_id"] = claimed_by_id
            if waiting_on:
                params["waiting_on"] = waiting_on
            if parent_id:
                params["parent"] = parent_id
            if assignee_query and not assignee_id:
                assignee_id, _, error = _resolve_single_assignee(
                    client,
                    workspace_slug,
                    project_id,
                    assignee_query=assignee_query,
                )
                if error:
                    return {"ok": False, "error": error}
            if assignee_id:
                params["assignee"] = assignee_id
            raw = await api_get(f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/", params=params)
            items = raw["results"] if isinstance(raw, dict) and "results" in raw else normalize_list(raw)
            return {"ok": True, "data": [work_item_to_dict(item) for item in items[: max(limit, 1)]]}

        if operation == "delegate":
            audit_log("coordination.delegate", workspace_slug, {"project_id": project_id, "title": title})
            existing_labels = fetch_existing_labels(client, workspace_slug, project_id)
            case_label_names = ["case", *(labels or [])]
            case_label_ids = resolve_label_ids(
                client,
                workspace_slug,
                project_id,
                case_label_names,
                existing_labels,
            )

            case_payload: dict[str, Any] = {
                "name": title,
                "labels": case_label_ids,
            }
            if description_html:
                case_payload["description_html"] = description_html
            if priority:
                case_payload["priority"] = priority.lower()
            if parent_id:
                case_payload["parent"] = parent_id
            if external_source:
                case_payload["external_source"] = external_source
            if external_id:
                case_payload["external_id"] = external_id

            if external_source and external_id:
                case_raw = await api_put(
                    f"/workspaces/{workspace_slug}/projects/{project_id}/work-items/",
                    case_payload,
                )
            else:
                case_raw = client.work_items.create(
                    workspace_slug=workspace_slug,
                    project_id=project_id,
                    data=CreateWorkItem(**case_payload),
                )

            case_id = str(extract(case_raw, "id"))
            if not case_id:
                return {"ok": False, "error": "Plane did not return a case id for delegate operation."}

            if any(
                [
                    route_to,
                    reply_identity,
                    coordination_status,
                    approver_id,
                    allowed_responder,
                    waiting_on,
                    waiting_since,
                    metadata is not None,
                ]
            ):
                await api_patch(
                    _coordination_path(workspace_slug, project_id, case_id),
                    _build_coordination_payload(
                        route_to=route_to,
                        reply_identity=reply_identity,
                        coordination_status=coordination_status or "triaged",
                        approver_id=approver_id,
                        allowed_responder=allowed_responder,
                        waiting_on=waiting_on,
                        waiting_since=waiting_since,
                        metadata=metadata,
                    ),
                )

            created_agent_tasks: list[dict[str, Any]] = []
            for spec in agent_tasks or []:
                task_title = str(spec.get("title") or spec.get("name") or "").strip()
                if not task_title:
                    return {"ok": False, "error": "Each agent task requires a title."}
                task_route_to = str(spec.get("target_alias") or spec.get("route_to") or "").strip()
                task_reply_identity = str(spec.get("reply_identity") or task_route_to or "").strip()
                resolved_task_assignee_id = str(spec.get("assignee_id") or "").strip()
                resolved_task_assignee = None
                assignee_query_value = str(spec.get("assignee_query") or task_route_to or "").strip()
                if assignee_query_value or resolved_task_assignee_id:
                    resolved_task_assignee_id, resolved_task_assignee, error = _resolve_single_assignee(
                        client,
                        workspace_slug,
                        project_id,
                        assignee_id=resolved_task_assignee_id,
                        assignee_query=assignee_query_value,
                    )
                    if error:
                        return {"ok": False, "error": error}

                task_label_names = ["agent-task", *(spec.get("labels") or [])]
                task_label_ids = resolve_label_ids(
                    client,
                    workspace_slug,
                    project_id,
                    task_label_names,
                    existing_labels,
                )
                create_kwargs: dict[str, Any] = {
                    "name": task_title,
                    "parent": case_id,
                    "labels": task_label_ids,
                }
                if spec.get("description_html"):
                    create_kwargs["description_html"] = spec["description_html"]
                if spec.get("priority"):
                    create_kwargs["priority"] = str(spec["priority"]).lower()
                if spec.get("due_date"):
                    create_kwargs["target_date"] = spec["due_date"]
                if spec.get("start_date"):
                    create_kwargs["start_date"] = spec["start_date"]
                if spec.get("external_source"):
                    create_kwargs["external_source"] = spec["external_source"]
                if spec.get("external_id"):
                    create_kwargs["external_id"] = spec["external_id"]
                if resolved_task_assignee_id:
                    create_kwargs["assignees"] = [resolved_task_assignee_id]

                created_task = client.work_items.create(
                    workspace_slug=workspace_slug,
                    project_id=project_id,
                    data=CreateWorkItem(**create_kwargs),
                )
                created_task_id = str(extract(created_task, "id"))
                coordination_raw = await api_post(
                    _coordination_path(workspace_slug, project_id, created_task_id, "handoff"),
                    _build_coordination_payload(
                        route_to=task_route_to,
                        reply_identity=task_reply_identity,
                        coordination_status=str(spec.get("coordination_status") or "delegated"),
                        allowed_responder=str(spec.get("allowed_responder") or ""),
                        waiting_on=str(spec.get("waiting_on") or ""),
                        waiting_since=str(spec.get("waiting_since") or ""),
                        assignee_ids=[resolved_task_assignee_id] if resolved_task_assignee_id else None,
                        clear_assignees=bool(spec.get("clear_assignees", False)),
                        comment_html=str(spec.get("comment_html") or ""),
                        metadata=spec.get("metadata"),
                    ),
                )
                created_agent_tasks.append(
                    {
                        "work_item": work_item_to_dict(created_task),
                        "coordination": coordination_raw,
                        "route_to": task_route_to,
                        "resolved_assignee": resolved_task_assignee,
                    }
                )

            created_human_tasks: list[dict[str, Any]] = []
            for spec in human_tasks or []:
                task_title = str(spec.get("title") or spec.get("name") or "").strip()
                if not task_title:
                    return {"ok": False, "error": "Each human task requires a title."}
                resolved_task_assignee_id = str(spec.get("assignee_id") or "").strip()
                resolved_task_assignee = None
                assignee_query_value = str(spec.get("assignee_query") or "").strip()
                if assignee_query_value or resolved_task_assignee_id:
                    resolved_task_assignee_id, resolved_task_assignee, error = _resolve_single_assignee(
                        client,
                        workspace_slug,
                        project_id,
                        assignee_id=resolved_task_assignee_id,
                        assignee_query=assignee_query_value,
                    )
                    if error:
                        return {"ok": False, "error": error}

                task_route_to = str(spec.get("route_to") or assignee_query_value or "").strip()
                task_label_names = ["human-task", *(spec.get("labels") or [])]
                task_label_ids = resolve_label_ids(
                    client,
                    workspace_slug,
                    project_id,
                    task_label_names,
                    existing_labels,
                )
                create_kwargs = {
                    "name": task_title,
                    "parent": case_id,
                    "labels": task_label_ids,
                }
                if spec.get("description_html"):
                    create_kwargs["description_html"] = spec["description_html"]
                if spec.get("priority"):
                    create_kwargs["priority"] = str(spec["priority"]).lower()
                if spec.get("due_date"):
                    create_kwargs["target_date"] = spec["due_date"]
                if spec.get("start_date"):
                    create_kwargs["start_date"] = spec["start_date"]
                if resolved_task_assignee_id:
                    create_kwargs["assignees"] = [resolved_task_assignee_id]

                created_task = client.work_items.create(
                    workspace_slug=workspace_slug,
                    project_id=project_id,
                    data=CreateWorkItem(**create_kwargs),
                )
                created_task_id = str(extract(created_task, "id"))
                coordination_raw = await api_post(
                    _coordination_path(workspace_slug, project_id, created_task_id, "handoff"),
                    _build_coordination_payload(
                        route_to=task_route_to,
                        reply_identity=str(spec.get("reply_identity") or ""),
                        coordination_status=str(spec.get("coordination_status") or "delegated"),
                        allowed_responder=str(spec.get("allowed_responder") or ""),
                        waiting_on=str(spec.get("waiting_on") or ""),
                        waiting_since=str(spec.get("waiting_since") or ""),
                        assignee_ids=[resolved_task_assignee_id] if resolved_task_assignee_id else None,
                        clear_assignees=bool(spec.get("clear_assignees", False)),
                        comment_html=str(spec.get("comment_html") or ""),
                        metadata=spec.get("metadata"),
                    ),
                )
                created_human_tasks.append(
                    {
                        "work_item": work_item_to_dict(created_task),
                        "coordination": coordination_raw,
                        "route_to": task_route_to,
                        "resolved_assignee": resolved_task_assignee,
                    }
                )

            result: dict[str, Any] = {
                "ok": True,
                "data": {
                    "case": work_item_to_dict(case_raw),
                    "agent_tasks": created_agent_tasks,
                    "human_tasks": created_human_tasks,
                },
            }
            return result

        return {"ok": False, "error": f"Unsupported coordination operation '{operation}'."}
