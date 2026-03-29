#!/usr/bin/env python3
"""Backfill Plane coordination state and Gmail thread identity.

Migrates existing family-office Plane work items away from `target_alias:*`
labels into first-class coordination state, and backfills the canonical
`external_source='gmail_thread'` / `external_id=<thread_id>` linkage for
root cases already tracked in the local orchestration database.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.config import alias_email, settings
from src.main import _ALIAS_WORKSPACE_MAP
from src.session_store import Case, SessionStore

_DONE_STATE_GROUPS = {"completed", "cancelled"}
_MAX_HTTP_RETRIES = 8
_PAGE_DELAY_SECONDS = 0.25

logging.getLogger("httpx").setLevel(logging.WARNING)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", action="append", dest="workspaces", default=[])
    parser.add_argument("--project", action="append", dest="projects", default=[])
    parser.add_argument("--apply", action="store_true", help="Apply changes instead of dry-run output.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of work items to process.")
    return parser.parse_args()


def _plane_headers() -> dict[str, str]:
    return {
        "X-API-Key": settings.plane_api_token,
        "Content-Type": "application/json",
    }


def _known_workspaces(selected: list[str]) -> list[str]:
    if selected:
        return sorted(set(selected))
    return sorted(set(_ALIAS_WORKSPACE_MAP.values()))


def _normalize_route(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower().lstrip("+")
    return normalized or None


def _route_from_assignees(assignees: list[dict[str, Any]]) -> str | None:
    known_agent_emails = {
        alias_email(alias).lower(): alias for alias in settings.alias_persona_map
    }
    for assignee in assignees:
        email = str(assignee.get("email") or "").strip().lower()
        if email in known_agent_emails:
            return known_agent_emails[email]
    for assignee in assignees:
        email = str(assignee.get("email") or "").strip().lower()
        if email:
            return email
        display_name = str(assignee.get("display_name") or "").strip()
        if display_name:
            return display_name
    return None


def _infer_coordination_status(
    state_group: str,
    item: dict[str, Any],
    existing_status: str | None,
) -> str:
    if existing_status:
        return existing_status
    if state_group.lower() in _DONE_STATE_GROUPS:
        return "done"
    haystack = " ".join(
        [
            str(item.get("name") or ""),
            str(item.get("description_stripped") or ""),
            " ".join(
                str(label.get("name") or label if isinstance(label, dict) else label)
                for label in item.get("labels", [])
            ),
        ]
    ).lower()
    if any(token in haystack for token in ("approval", "approve", "approver", "review required")):
        return "awaiting_approval"
    return "triaged"


async def _thread_map() -> dict[str, str]:
    await SessionStore.initialize()
    async with SessionStore._session_maker() as session:  # type: ignore[attr-defined]
        rows = (
            await session.execute(
                select(Case.case_id, Case.thread_id).where(Case.thread_id.is_not(None))
            )
        ).all()
        return {
            str(case_id): str(thread_id)
            for case_id, thread_id in rows
            if case_id and thread_id
        }


async def _list_projects(client: httpx.AsyncClient, workspace_slug: str) -> list[dict[str, Any]]:
    resp = await _request_with_retry(
        client,
        "GET",
        f"{settings.plane_base_url}/api/v1/workspaces/{workspace_slug}/projects/",
        headers=_plane_headers(),
    )
    resp.raise_for_status()
    payload = resp.json()
    projects = payload.get("results", payload) if isinstance(payload, dict) else payload
    return projects if isinstance(projects, list) else []


async def _list_states(client: httpx.AsyncClient, workspace_slug: str, project_id: str) -> dict[str, str]:
    resp = await _request_with_retry(
        client,
        "GET",
        f"{settings.plane_base_url}/api/v1/workspaces/{workspace_slug}/projects/{project_id}/states/",
        headers=_plane_headers(),
    )
    resp.raise_for_status()
    payload = resp.json()
    states = payload.get("results", payload) if isinstance(payload, dict) else payload
    if not isinstance(states, list):
        return {}
    return {
        str(state.get("id")): str(state.get("group") or "")
        for state in states
        if state.get("id")
    }


async def _list_work_items(client: httpx.AsyncClient, workspace_slug: str, project_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor = ""
    seen_cursors: set[str] = set()
    total_count: int | None = None
    while True:
        params = {"expand": "coordination", "per_page": "1000"}
        if cursor:
            if cursor in seen_cursors:
                break
            seen_cursors.add(cursor)
            params["cursor"] = cursor
        resp = await _request_with_retry(
            client,
            "GET",
            f"{settings.plane_base_url}/api/v1/workspaces/{workspace_slug}/projects/{project_id}/work-items/",
            headers=_plane_headers(),
            params=params,
        )
        resp.raise_for_status()
        payload = resp.json()
        if isinstance(payload, dict):
            batch = payload.get("results", [])
            try:
                total_count = int(payload.get("total_count")) if payload.get("total_count") is not None else total_count
            except (TypeError, ValueError):
                total_count = total_count
            cursor = str(payload.get("next_cursor") or "")
        else:
            batch = payload
            cursor = ""
        if isinstance(batch, list):
            items.extend(batch)
        if not batch:
            break
        if total_count is not None and len(items) >= total_count:
            break
        if not cursor:
            break
        await asyncio.sleep(_PAGE_DELAY_SECONDS)
    return items


async def _patch_work_item(
    client: httpx.AsyncClient,
    workspace_slug: str,
    project_id: str,
    work_item_id: str,
    payload: dict[str, Any],
) -> None:
    resp = await _request_with_retry(
        client,
        "PATCH",
        f"{settings.plane_base_url}/api/v1/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/",
        headers=_plane_headers(),
        json=payload,
    )
    resp.raise_for_status()


async def _patch_coordination(
    client: httpx.AsyncClient,
    workspace_slug: str,
    project_id: str,
    work_item_id: str,
    payload: dict[str, Any],
) -> None:
    resp = await _request_with_retry(
        client,
        "PATCH",
        f"{settings.plane_base_url}/api/v1/workspaces/{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/coordination/",
        headers=_plane_headers(),
        json=payload,
    )
    resp.raise_for_status()


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response:
    for attempt in range(1, _MAX_HTTP_RETRIES + 1):
        response = await client.request(method, url, **kwargs)
        if response.status_code not in {429, 500, 502, 503, 504}:
            return response
        if attempt >= _MAX_HTTP_RETRIES:
            return response

        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                sleep_for = max(float(retry_after), _PAGE_DELAY_SECONDS)
            except ValueError:
                sleep_for = _PAGE_DELAY_SECONDS * attempt
        else:
            sleep_for = _PAGE_DELAY_SECONDS * attempt
        await asyncio.sleep(sleep_for)

    return response


async def _run(args: argparse.Namespace) -> int:
    if not settings.plane_base_url or not settings.plane_api_token:
        print("Plane configuration is missing. Set PLANE_BASE_URL and PLANE_API_TOKEN.", file=sys.stderr)
        return 2

    case_threads = await _thread_map()
    changed = 0
    examined = 0

    async with httpx.AsyncClient(timeout=20.0) as client:
        for workspace_slug in _known_workspaces(args.workspaces):
            projects = await _list_projects(client, workspace_slug)
            for project in projects:
                project_id = str(project.get("id") or "")
                if not project_id:
                    continue
                if args.projects and project_id not in set(args.projects):
                    continue

                state_groups = await _list_states(client, workspace_slug, project_id)
                work_items = await _list_work_items(client, workspace_slug, project_id)

                for item in work_items:
                    if args.limit and examined >= args.limit:
                        print(f"Reached limit={args.limit}; stopping.")
                        return 0
                    examined += 1

                    work_item_id = str(item.get("id") or "")
                    if not work_item_id:
                        continue

                    labels = item.get("labels", [])
                    assignees = item.get("assignees", [])
                    coordination = item.get("coordination") or {}
                    state_group = state_groups.get(str(item.get("state") or ""), "")

                    target_alias = None
                    retained_label_ids: list[str] = []
                    removed_target_labels: list[str] = []
                    for label in labels:
                        label_id = str(label.get("id") or "") if isinstance(label, dict) else ""
                        label_name = str(label.get("name") or "") if isinstance(label, dict) else str(label)
                        if label_name.startswith("target_alias:"):
                            target_alias = _normalize_route(label_name.split(":", 1)[1])
                            removed_target_labels.append(label_name)
                            continue
                        if label_id:
                            retained_label_ids.append(label_id)

                    route_to = _normalize_route(coordination.get("route_to")) or target_alias or _route_from_assignees(assignees)
                    reply_identity = _normalize_route(coordination.get("reply_identity")) or (
                        route_to if route_to in settings.alias_persona_map else None
                    )
                    coordination_status = _infer_coordination_status(
                        state_group,
                        item,
                        coordination.get("coordination_status"),
                    )

                    work_item_patch: dict[str, Any] = {}
                    thread_id = case_threads.get(work_item_id)
                    if thread_id and not item.get("external_source") and not item.get("external_id"):
                        work_item_patch["external_source"] = "gmail_thread"
                        work_item_patch["external_id"] = thread_id
                    if removed_target_labels:
                        work_item_patch["labels"] = retained_label_ids

                    coordination_patch: dict[str, Any] = {}
                    if route_to and route_to != _normalize_route(coordination.get("route_to")):
                        coordination_patch["route_to"] = route_to
                    if reply_identity and reply_identity != _normalize_route(coordination.get("reply_identity")):
                        coordination_patch["reply_identity"] = reply_identity
                    if coordination_status != str(coordination.get("coordination_status") or ""):
                        coordination_patch["coordination_status"] = coordination_status
                    if coordination.get("last_transition_at") is None and item.get("updated_at"):
                        coordination_patch["last_transition_at"] = item.get("updated_at")

                    if not work_item_patch and not coordination_patch:
                        continue

                    changed += 1
                    print(
                        f"[{workspace_slug}/{project_id}] {work_item_id} "
                        f"route_to={route_to or '-'} status={coordination_status} "
                        f"thread={'yes' if thread_id else 'no'} remove_labels={removed_target_labels or '[]'}"
                    )
                    if not args.apply:
                        continue

                    if work_item_patch:
                        await _patch_work_item(client, workspace_slug, project_id, work_item_id, work_item_patch)
                    if coordination_patch:
                        await _patch_coordination(client, workspace_slug, project_id, work_item_id, coordination_patch)

    print(
        f"{'Applied' if args.apply else 'Planned'} changes for {changed} work items "
        f"after examining {examined} items."
    )
    return 0


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
