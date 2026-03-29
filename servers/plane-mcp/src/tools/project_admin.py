"""Canonical project administration tool for Plane MCP."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from plane.models.cycles import CreateCycle, UpdateCycle
from plane.models.labels import CreateLabel, UpdateLabel
from plane.models.modules import CreateModule, UpdateModule
from plane.models.pages import CreatePage
from plane.models.states import CreateState, UpdateState

from tools._helpers import audit_log, extract, normalize_list, not_found_response, work_item_to_dict
from tools._http import api_delete, api_get, api_patch, api_post

logger = logging.getLogger("plane-mcp.project_admin")


def _view_path(workspace_slug: str, project_id: str, view_id: str = "") -> str:
    base = f"/workspaces/{workspace_slug}/projects/{project_id}/views/"
    return f"{base}{view_id}/" if view_id else base


def _page_path(workspace_slug: str, project_id: str, page_id: str = "", action: str = "") -> str:
    base = f"/workspaces/{workspace_slug}/projects/{project_id}/pages/"
    if page_id:
        base = f"{base}{page_id}/"
    if action:
        return f"{base}{action}/"
    return base


def _estimate_path(workspace_slug: str, project_id: str, estimate_id: str = "") -> str:
    base = f"/workspaces/{workspace_slug}/projects/{project_id}/estimates/"
    return f"{base}{estimate_id}/" if estimate_id else base


def _simple_items(raw: list[Any], keys: list[str]) -> list[dict[str, Any]]:
    return [{key: extract(item, key) for key in keys} for item in raw]


def register_project_admin_tools(mcp, get_client):
    @mcp.tool()
    async def project_admin(
        operation: str,
        workspace_slug: str,
        project_id: str = "",
        project_identifier: str = "",
        name: str = "",
        description: str = "",
        network: int = 2,
        state_id: str = "",
        group: str = "",
        color: str = "",
        label_id: str = "",
        page_id: str = "",
        content_html: str = "",
        view_id: str = "",
        query_data: dict[str, Any] | None = None,
        cycle_id: str = "",
        module_id: str = "",
        estimate_id: str = "",
        estimate_type: str = "",
        estimate_points: list[dict[str, Any]] | None = None,
        work_item_ids: list[str] | None = None,
        work_item_id: str = "",
        start_date: str = "",
        end_date: str = "",
        target_date: str = "",
    ) -> dict[str, Any]:
        """Canonical project administration operations for Plane.

        Operations:
        - create_project, get_project
        - list_states, create_state, update_state, delete_state
        - list_labels, create_label, update_label, delete_label
        - list_views, create_view, get_view, update_view, delete_view
        - list_pages, create_page, get_page, update_page, archive_page, delete_page
        - list_cycles, create_cycle, get_cycle, update_cycle, delete_cycle, add_cycle_work_items, remove_cycle_work_item
        - list_modules, create_module, get_module, update_module, delete_module, add_module_work_items, remove_module_work_item
        - list_estimates, create_estimate, get_estimate, update_estimate, delete_estimate
        """

        client = get_client()

        if operation == "create_project":
            audit_log("project_admin.create_project", workspace_slug, {"name": name})
            project = client.projects.create(
                workspace_slug=workspace_slug,
                data={
                    "name": name,
                    "description": description,
                    "network": network,
                },
            )
            return {
                "ok": True,
                "data": {
                    "id": extract(project, "id"),
                    "name": extract(project, "name", name),
                    "identifier": extract(project, "identifier"),
                    "description": extract(project, "description", description),
                    "network": extract(project, "network", network),
                },
            }

        if operation == "get_project":
            project = client.projects.retrieve(workspace_slug=workspace_slug, project_id=project_id)
            return {
                "ok": True,
                "data": {
                    "id": extract(project, "id"),
                    "name": extract(project, "name"),
                    "identifier": extract(project, "identifier", project_identifier),
                    "description": extract(project, "description"),
                    "network": extract(project, "network", 2),
                    "member_count": extract(project, "total_members", 0),
                    "page_view": extract(project, "page_view", False),
                    "issue_views_view": extract(project, "issue_views_view", False),
                },
            }

        if operation == "list_states":
            items = normalize_list(client.states.list(workspace_slug=workspace_slug, project_id=project_id))
            return {"ok": True, "data": _simple_items(items, ["id", "name", "group", "color", "sequence"])}

        if operation == "create_state":
            audit_log("project_admin.create_state", workspace_slug, {"project_id": project_id, "name": name})
            state = client.states.create(
                workspace_slug=workspace_slug,
                project_id=project_id,
                data=CreateState(name=name, group=group, color=color or "#6366f1"),
            )
            return {"ok": True, "data": {"id": extract(state, "id"), "name": extract(state, "name", name), "group": extract(state, "group", group), "color": extract(state, "color", color or "#6366f1")}}

        if operation == "update_state":
            payload: dict[str, Any] = {}
            if name:
                payload["name"] = name
            if group:
                payload["group"] = group
            if color:
                payload["color"] = color
            if not payload:
                return {"ok": False, "error": "At least one of name, group, or color must be provided."}
            audit_log("project_admin.update_state", workspace_slug, {"project_id": project_id, "state_id": state_id})
            state = client.states.update(
                workspace_slug=workspace_slug,
                project_id=project_id,
                state_id=state_id,
                data=UpdateState(**payload),
            )
            return {"ok": True, "data": {"id": extract(state, "id", state_id), "name": extract(state, "name"), "group": extract(state, "group"), "color": extract(state, "color")}}

        if operation == "delete_state":
            audit_log("project_admin.delete_state", workspace_slug, {"project_id": project_id, "state_id": state_id})
            client.states.delete(workspace_slug=workspace_slug, project_id=project_id, state_id=state_id)
            return {"ok": True, "data": {"id": state_id, "status": "deleted"}}

        if operation == "list_labels":
            items = normalize_list(client.labels.list(workspace_slug=workspace_slug, project_id=project_id))
            return {"ok": True, "data": _simple_items(items, ["id", "name", "color"])}

        if operation == "create_label":
            audit_log("project_admin.create_label", workspace_slug, {"project_id": project_id, "name": name})
            label = client.labels.create(
                workspace_slug=workspace_slug,
                project_id=project_id,
                data=CreateLabel(name=name, color=color or "#6366f1"),
            )
            return {"ok": True, "data": {"id": extract(label, "id"), "name": extract(label, "name", name), "color": extract(label, "color", color or "#6366f1")}}

        if operation == "update_label":
            payload = {}
            if name:
                payload["name"] = name
            if color:
                payload["color"] = color
            if not payload:
                return {"ok": False, "error": "At least one of name or color must be provided."}
            audit_log("project_admin.update_label", workspace_slug, {"project_id": project_id, "label_id": label_id})
            label = client.labels.update(
                workspace_slug=workspace_slug,
                project_id=project_id,
                label_id=label_id,
                data=UpdateLabel(**payload),
            )
            return {"ok": True, "data": {"id": extract(label, "id", label_id), "name": extract(label, "name"), "color": extract(label, "color")}}

        if operation == "delete_label":
            audit_log("project_admin.delete_label", workspace_slug, {"project_id": project_id, "label_id": label_id})
            client.labels.delete(workspace_slug=workspace_slug, project_id=project_id, label_id=label_id)
            return {"ok": True, "data": {"id": label_id, "status": "deleted"}}

        if operation == "list_views":
            path = _view_path(workspace_slug, project_id)
            try:
                raw = await api_get(path)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project views", path)
                raise
            items = normalize_list(raw)
            return {"ok": True, "data": _simple_items(items, ["id", "name", "description", "query_data", "access", "created_at", "updated_at"])}

        if operation == "create_view":
            audit_log("project_admin.create_view", workspace_slug, {"project_id": project_id, "name": name})
            payload: dict[str, Any] = {"name": name}
            if description:
                payload["description"] = description
            if query_data:
                payload["query_data"] = query_data
            path = _view_path(workspace_slug, project_id)
            try:
                raw = await api_post(path, payload)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project views", path)
                raise
            return {"ok": True, "data": {"id": extract(raw, "id"), "name": extract(raw, "name", name), "description": extract(raw, "description", description), "query_data": extract(raw, "query_data", query_data or {})}}

        if operation == "get_view":
            path = _view_path(workspace_slug, project_id, view_id)
            try:
                raw = await api_get(path)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project view", path)
                raise
            return {"ok": True, "data": {key: extract(raw, key) for key in ["id", "name", "description", "query_data", "display_filters", "display_properties", "access", "is_locked", "created_at", "updated_at"]}}

        if operation == "update_view":
            payload = {}
            if name:
                payload["name"] = name
            if description:
                payload["description"] = description
            if query_data:
                payload["query_data"] = query_data
            if not payload:
                return {"ok": False, "error": "At least one of name, description, or query_data must be provided."}
            audit_log("project_admin.update_view", workspace_slug, {"project_id": project_id, "view_id": view_id})
            path = _view_path(workspace_slug, project_id, view_id)
            try:
                raw = await api_patch(path, payload)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project view", path)
                raise
            return {"ok": True, "data": {"id": extract(raw, "id", view_id), "name": extract(raw, "name"), "updated_at": extract(raw, "updated_at")}}

        if operation == "delete_view":
            audit_log("project_admin.delete_view", workspace_slug, {"project_id": project_id, "view_id": view_id})
            path = _view_path(workspace_slug, project_id, view_id)
            try:
                await api_delete(path)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project view", path)
                raise
            return {"ok": True, "data": {"id": view_id, "status": "deleted"}}

        if operation == "list_pages":
            path = _page_path(workspace_slug, project_id)
            try:
                raw = await api_get(path)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project pages", path)
                raise
            items = normalize_list(raw)
            return {"ok": True, "data": _simple_items(items, ["id", "name", "owned_by", "access", "is_locked", "archived_at", "created_at", "updated_at"])}

        if operation == "create_page":
            audit_log("project_admin.create_page", workspace_slug, {"project_id": project_id, "name": name})
            page = client.pages.create_project_page(
                workspace_slug=workspace_slug,
                project_id=project_id,
                data=CreatePage(name=name, description_html=content_html or ""),
            )
            return {"ok": True, "data": {"id": extract(page, "id"), "name": extract(page, "name", name)}}

        if operation == "get_page":
            page = client.pages.retrieve_project_page(
                workspace_slug=workspace_slug,
                project_id=project_id,
                page_id=page_id,
            )
            return {"ok": True, "data": {key: extract(page, key) for key in ["id", "name", "description_html", "owned_by", "access", "is_locked", "created_at", "updated_at"]}}

        if operation == "update_page":
            payload = {}
            if name:
                payload["name"] = name
            if content_html:
                payload["description_html"] = content_html
            if not payload:
                return {"ok": False, "error": "At least one of name or content_html must be provided."}
            audit_log("project_admin.update_page", workspace_slug, {"project_id": project_id, "page_id": page_id})
            path = _page_path(workspace_slug, project_id, page_id)
            try:
                raw = await api_patch(path, payload)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project page", path)
                raise
            return {"ok": True, "data": {"id": extract(raw, "id", page_id), "name": extract(raw, "name"), "updated_at": extract(raw, "updated_at")}}

        if operation == "archive_page":
            audit_log("project_admin.archive_page", workspace_slug, {"project_id": project_id, "page_id": page_id})
            path = _page_path(workspace_slug, project_id, page_id, "archive")
            try:
                await api_post(path, {})
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project page archive", path)
                raise
            return {"ok": True, "data": {"id": page_id, "status": "archived"}}

        if operation == "delete_page":
            audit_log("project_admin.delete_page", workspace_slug, {"project_id": project_id, "page_id": page_id})
            archive_path = _page_path(workspace_slug, project_id, page_id, "archive")
            page_path = _page_path(workspace_slug, project_id, page_id)
            try:
                await api_post(archive_path, {})
                await api_delete(page_path)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project page", page_path)
                raise
            return {"ok": True, "data": {"id": page_id, "status": "deleted"}}

        if operation == "list_cycles":
            items = normalize_list(client.cycles.list(workspace_slug=workspace_slug, project_id=project_id))
            return {"ok": True, "data": _simple_items(items, ["id", "name", "description", "start_date", "end_date", "status", "created_at"])}

        if operation == "create_cycle":
            audit_log("project_admin.create_cycle", workspace_slug, {"project_id": project_id, "name": name})
            cycle = client.cycles.create(
                workspace_slug=workspace_slug,
                project_id=project_id,
                data=CreateCycle(
                    name=name,
                    project_id=project_id,
                    owned_by="",
                    description=description or None,
                    start_date=start_date or None,
                    end_date=end_date or None,
                ),
            )
            return {"ok": True, "data": {"id": extract(cycle, "id"), "name": extract(cycle, "name", name), "description": extract(cycle, "description", description), "start_date": extract(cycle, "start_date", start_date), "end_date": extract(cycle, "end_date", end_date)}}

        if operation == "get_cycle":
            cycle = client.cycles.retrieve(workspace_slug=workspace_slug, project_id=project_id, cycle_id=cycle_id)
            work_items = normalize_list(client.cycles.list_work_items(workspace_slug=workspace_slug, project_id=project_id, cycle_id=cycle_id))
            return {"ok": True, "data": {"cycle": {key: extract(cycle, key) for key in ["id", "name", "description", "start_date", "end_date", "status", "created_at", "updated_at"]}, "work_items": [work_item_to_dict(item) for item in work_items]}}

        if operation == "update_cycle":
            payload = {}
            if name:
                payload["name"] = name
            if description:
                payload["description"] = description
            if start_date:
                payload["start_date"] = start_date
            if end_date:
                payload["end_date"] = end_date
            if not payload:
                return {"ok": False, "error": "At least one of name, description, start_date, or end_date must be provided."}
            audit_log("project_admin.update_cycle", workspace_slug, {"project_id": project_id, "cycle_id": cycle_id})
            cycle = client.cycles.update(
                workspace_slug=workspace_slug,
                project_id=project_id,
                cycle_id=cycle_id,
                data=UpdateCycle(**payload),
            )
            return {"ok": True, "data": {"id": extract(cycle, "id", cycle_id), "name": extract(cycle, "name"), "description": extract(cycle, "description"), "start_date": extract(cycle, "start_date"), "end_date": extract(cycle, "end_date")}}

        if operation == "delete_cycle":
            audit_log("project_admin.delete_cycle", workspace_slug, {"project_id": project_id, "cycle_id": cycle_id})
            client.cycles.delete(workspace_slug=workspace_slug, project_id=project_id, cycle_id=cycle_id)
            return {"ok": True, "data": {"id": cycle_id, "status": "deleted"}}

        if operation == "add_cycle_work_items":
            audit_log("project_admin.add_cycle_work_items", workspace_slug, {"project_id": project_id, "cycle_id": cycle_id, "count": len(work_item_ids or [])})
            client.cycles.add_work_items(
                workspace_slug=workspace_slug,
                project_id=project_id,
                cycle_id=cycle_id,
                issue_ids=work_item_ids or [],
            )
            return {"ok": True, "data": {"cycle_id": cycle_id, "added_count": len(work_item_ids or []), "work_item_ids": work_item_ids or []}}

        if operation == "remove_cycle_work_item":
            audit_log("project_admin.remove_cycle_work_item", workspace_slug, {"project_id": project_id, "cycle_id": cycle_id, "work_item_id": work_item_id})
            client.cycles.remove_work_item(
                workspace_slug=workspace_slug,
                project_id=project_id,
                cycle_id=cycle_id,
                work_item_id=work_item_id,
            )
            return {"ok": True, "data": {"cycle_id": cycle_id, "removed_work_item_id": work_item_id}}

        if operation == "list_modules":
            items = normalize_list(client.modules.list(workspace_slug=workspace_slug, project_id=project_id))
            return {"ok": True, "data": _simple_items(items, ["id", "name", "description", "start_date", "target_date", "status", "created_at"])}

        if operation == "create_module":
            audit_log("project_admin.create_module", workspace_slug, {"project_id": project_id, "name": name})
            module = client.modules.create(
                workspace_slug=workspace_slug,
                project_id=project_id,
                data=CreateModule(
                    name=name,
                    description=description or None,
                    start_date=start_date or None,
                    target_date=target_date or None,
                ),
            )
            return {"ok": True, "data": {"id": extract(module, "id"), "name": extract(module, "name", name), "description": extract(module, "description", description), "start_date": extract(module, "start_date", start_date), "target_date": extract(module, "target_date", target_date)}}

        if operation == "get_module":
            module = client.modules.retrieve(workspace_slug=workspace_slug, project_id=project_id, module_id=module_id)
            work_items = normalize_list(client.modules.list_work_items(workspace_slug=workspace_slug, project_id=project_id, module_id=module_id))
            return {"ok": True, "data": {"module": {key: extract(module, key) for key in ["id", "name", "description", "start_date", "target_date", "status", "created_at", "updated_at"]}, "work_items": [work_item_to_dict(item) for item in work_items]}}

        if operation == "update_module":
            payload = {}
            if name:
                payload["name"] = name
            if description:
                payload["description"] = description
            if start_date:
                payload["start_date"] = start_date
            if target_date:
                payload["target_date"] = target_date
            if not payload:
                return {"ok": False, "error": "At least one of name, description, start_date, or target_date must be provided."}
            audit_log("project_admin.update_module", workspace_slug, {"project_id": project_id, "module_id": module_id})
            module = client.modules.update(
                workspace_slug=workspace_slug,
                project_id=project_id,
                module_id=module_id,
                data=UpdateModule(**payload),
            )
            return {"ok": True, "data": {"id": extract(module, "id", module_id), "name": extract(module, "name"), "description": extract(module, "description"), "start_date": extract(module, "start_date"), "target_date": extract(module, "target_date")}}

        if operation == "delete_module":
            audit_log("project_admin.delete_module", workspace_slug, {"project_id": project_id, "module_id": module_id})
            client.modules.delete(workspace_slug=workspace_slug, project_id=project_id, module_id=module_id)
            return {"ok": True, "data": {"id": module_id, "status": "deleted"}}

        if operation == "add_module_work_items":
            audit_log("project_admin.add_module_work_items", workspace_slug, {"project_id": project_id, "module_id": module_id, "count": len(work_item_ids or [])})
            client.modules.add_work_items(
                workspace_slug=workspace_slug,
                project_id=project_id,
                module_id=module_id,
                issue_ids=work_item_ids or [],
            )
            return {"ok": True, "data": {"module_id": module_id, "added_count": len(work_item_ids or []), "work_item_ids": work_item_ids or []}}

        if operation == "remove_module_work_item":
            audit_log("project_admin.remove_module_work_item", workspace_slug, {"project_id": project_id, "module_id": module_id, "work_item_id": work_item_id})
            client.modules.remove_work_item(
                workspace_slug=workspace_slug,
                project_id=project_id,
                module_id=module_id,
                work_item_id=work_item_id,
            )
            return {"ok": True, "data": {"module_id": module_id, "removed_work_item_id": work_item_id}}

        if operation == "list_estimates":
            path = _estimate_path(workspace_slug, project_id)
            try:
                raw = await api_get(path)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project estimates", path)
                raise
            items = normalize_list(raw)
            results = []
            for item in items:
                points = extract(item, "points", [])
                results.append(
                    {
                        "id": extract(item, "id"),
                        "name": extract(item, "name"),
                        "description": extract(item, "description"),
                        "type": extract(item, "type"),
                        "last_used": extract(item, "last_used", False),
                        "points": [
                            {"id": extract(point, "id"), "key": extract(point, "key"), "value": extract(point, "value")}
                            for point in (points if isinstance(points, list) else [])
                        ],
                    }
                )
            return {"ok": True, "data": results}

        if operation == "create_estimate":
            audit_log("project_admin.create_estimate", workspace_slug, {"project_id": project_id, "name": name})
            path = _estimate_path(workspace_slug, project_id)
            try:
                raw = await api_post(
                    path,
                    {
                        "estimate": {"name": name, "type": estimate_type or "categories"},
                        "estimate_points": estimate_points or [],
                    },
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project estimates", path)
                raise
            return {"ok": True, "data": {"id": extract(raw, "id"), "name": extract(raw, "name", name), "type": extract(raw, "type", estimate_type or "categories")}}

        if operation == "get_estimate":
            path = _estimate_path(workspace_slug, project_id, estimate_id)
            try:
                raw = await api_get(path)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project estimate", path)
                raise
            points = extract(raw, "points", [])
            return {"ok": True, "data": {"id": extract(raw, "id"), "name": extract(raw, "name"), "description": extract(raw, "description"), "type": extract(raw, "type"), "last_used": extract(raw, "last_used", False), "points": [{"id": extract(point, "id"), "key": extract(point, "key"), "value": extract(point, "value")} for point in (points if isinstance(points, list) else [])]}}

        if operation == "update_estimate":
            payload = {}
            estimate_fields = {}
            if name:
                estimate_fields["name"] = name
            if estimate_type:
                estimate_fields["type"] = estimate_type
            if estimate_fields:
                payload["estimate"] = estimate_fields
            if estimate_points is not None:
                payload["estimate_points"] = estimate_points
            if not payload:
                return {"ok": False, "error": "At least one of name, estimate_type, or estimate_points must be provided."}
            audit_log("project_admin.update_estimate", workspace_slug, {"project_id": project_id, "estimate_id": estimate_id})
            path = _estimate_path(workspace_slug, project_id, estimate_id)
            try:
                raw = await api_patch(path, payload)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project estimate", path)
                raise
            return {"ok": True, "data": {"id": extract(raw, "id", estimate_id), "name": extract(raw, "name"), "type": extract(raw, "type")}}

        if operation == "delete_estimate":
            audit_log("project_admin.delete_estimate", workspace_slug, {"project_id": project_id, "estimate_id": estimate_id})
            path = _estimate_path(workspace_slug, project_id, estimate_id)
            try:
                await api_delete(path)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    return not_found_response("project estimate", path)
                raise
            return {"ok": True, "data": {"id": estimate_id, "status": "deleted"}}

        return {"ok": False, "error": f"Unsupported project_admin operation '{operation}'."}
