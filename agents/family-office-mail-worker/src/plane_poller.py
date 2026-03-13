"""Plane work-item polling loop for detecting delegated task completions.

Polls each active PM workspace every PLANE_POLLING_INTERVAL_SECONDS for work
items updated since the last poll.  When all child work items under a case
reach a "done" state, the lead-agent Codex session is resumed to synthesize
results and reply to the human.

Delegation hierarchy is read directly from Plane (parent/child work items)
— no local delegation edges are maintained.
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx

from src.config import alias_email, settings
from src.session_store import SessionStore

logger = logging.getLogger(__name__)

# Plane state group names that indicate completion
_DONE_STATE_GROUPS = {"completed", "cancelled"}

# Track last poll timestamp per workspace
_last_poll_ts: dict[str, str] = {}


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat() + "Z"


def _plane_headers() -> dict[str, str]:
    return {
        "X-API-Key": settings.plane_api_token,
        "Content-Type": "application/json",
    }


async def _fetch_workspace_states(
    client: httpx.AsyncClient,
    workspace_slug: str,
    project_id: str,
) -> dict[str, dict]:
    """Return {state_id: {name, group}} for a project."""
    url = f"{settings.plane_base_url}/api/v1/workspaces/{workspace_slug}/projects/{project_id}/states/"
    resp = await client.get(url, headers=_plane_headers())
    resp.raise_for_status()
    states = resp.json().get("results", resp.json()) if isinstance(resp.json(), dict) else resp.json()
    if isinstance(states, list):
        return {str(s["id"]): {"name": s.get("name", ""), "group": s.get("group", "")} for s in states}
    return {}


async def _fetch_updated_work_items(
    client: httpx.AsyncClient,
    workspace_slug: str,
    project_id: str,
    updated_after: str,
) -> list[dict]:
    """Fetch work items updated after the given ISO timestamp."""
    url = (
        f"{settings.plane_base_url}/api/v1/workspaces/{workspace_slug}"
        f"/projects/{project_id}/work-items/"
    )
    params = {"updated_at__gt": updated_after}
    resp = await client.get(url, headers=_plane_headers(), params=params)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", data) if isinstance(data, dict) else data


async def _fetch_child_work_items(
    client: httpx.AsyncClient,
    workspace_slug: str,
    project_id: str,
    parent_id: str,
) -> list[dict]:
    """Fetch child work items of a parent (case) from Plane."""
    url = (
        f"{settings.plane_base_url}/api/v1/workspaces/{workspace_slug}"
        f"/projects/{project_id}/work-items/"
    )
    params = {"parent": parent_id}
    resp = await client.get(url, headers=_plane_headers(), params=params)
    resp.raise_for_status()
    data = resp.json()
    return data.get("results", data) if isinstance(data, dict) else data


async def _fetch_latest_comment(
    client: httpx.AsyncClient,
    workspace_slug: str,
    project_id: str,
    work_item_id: str,
) -> str:
    """Fetch the most recent comment on a work item (specialist result)."""
    url = (
        f"{settings.plane_base_url}/api/v1/workspaces/{workspace_slug}"
        f"/projects/{project_id}/work-items/{work_item_id}/comments/"
    )
    try:
        resp = await client.get(url, headers=_plane_headers())
        resp.raise_for_status()
        data = resp.json()
        comments = data.get("results", data) if isinstance(data, dict) else data
        if isinstance(comments, list) and comments:
            # Plane returns comments newest-first; take the first element
            latest = comments[0]
            return latest.get("comment_stripped", "") or latest.get("comment_html", "")
    except Exception:
        logger.debug("Failed to fetch comments for work item %s", work_item_id[:12])
    return ""


async def _get_all_poll_workspaces() -> set[str]:
    """Return workspace slugs with active PM sessions."""
    return set(await SessionStore.get_active_pm_workspaces())


async def _get_project_ids_for_workspace(workspace_slug: str) -> set[str]:
    """Get project IDs to poll from active PM sessions in this workspace."""
    from sqlalchemy import select as sa_select

    from src.session_store import PmSession

    await SessionStore.initialize()
    async with SessionStore._session_maker() as session:
        pm_project_ids = (
            await session.execute(
                sa_select(PmSession.project_id).where(
                    PmSession.workspace_slug == workspace_slug,
                    PmSession.status == "active",
                )
            )
        ).scalars().all()
    return set(pm_project_ids)


async def poll_plane_workspaces() -> None:
    """Single poll cycle across all active PM workspaces.

    Called by APScheduler on the configured interval.
    """
    if not settings.plane_base_url or not settings.plane_api_token:
        return

    all_workspaces = await _get_all_poll_workspaces()
    if not all_workspaces:
        return

    now_iso = _utcnow_iso()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for workspace_slug in all_workspaces:
            try:
                await _poll_workspace(client, workspace_slug, now_iso)
            except Exception:
                logger.exception("Plane poll failed for workspace %s", workspace_slug)


async def _poll_workspace(
    client: httpx.AsyncClient,
    workspace_slug: str,
    now_iso: str,
) -> None:
    """Poll a single workspace for updated work items."""
    last_ts = _last_poll_ts.get(workspace_slug)
    if last_ts is None:
        # First poll: look back 10 minutes to catch recent changes
        ten_min_ago = datetime.now(timezone.utc) - timedelta(minutes=10)
        last_ts = ten_min_ago.replace(microsecond=0).isoformat() + "Z"

    project_ids = await _get_project_ids_for_workspace(workspace_slug)
    if not project_ids:
        _last_poll_ts[workspace_slug] = now_iso
        return

    for project_id in project_ids:
        try:
            items = await _fetch_updated_work_items(client, workspace_slug, project_id, last_ts)
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Plane API error polling %s/%s: %s",
                workspace_slug,
                project_id,
                exc.response.status_code,
            )
            continue

        if not items:
            continue

        # Fetch states to check completion
        states = await _fetch_workspace_states(client, workspace_slug, project_id)

        for item in items:
            item_id = str(item.get("id", ""))
            state_id = str(item.get("state", ""))
            state_info = states.get(state_id, {})
            state_group = state_info.get("group", "").lower()

            if state_group not in _DONE_STATE_GROUPS:
                continue

            # Build dedupe key
            updated_at = str(item.get("updated_at", ""))
            dedupe_key = f"{workspace_slug}:{item_id}:{updated_at}"
            if await SessionStore.is_plane_delivery_processed(dedupe_key):
                continue

            await SessionStore.record_plane_delivery(dedupe_key)

            # Check if this completed item is a child of a tracked case.
            # If so, query Plane for all siblings to see if the case is done.
            parent_id = str(item.get("parent", "") or "")
            if not parent_id:
                continue

            pm_session = await SessionStore.get_pm_session_by_case(parent_id)
            if pm_session is None or pm_session["status"] != "active":
                continue

            # All children of this case — check if all are done
            try:
                siblings = await _fetch_child_work_items(
                    client, workspace_slug, project_id, parent_id,
                )
            except httpx.HTTPStatusError:
                logger.warning("Failed to fetch children for case %s", parent_id[:12])
                continue

            all_done = True
            for sibling in siblings:
                sib_state_id = str(sibling.get("state", ""))
                sib_group = states.get(sib_state_id, {}).get("group", "").lower()
                if sib_group not in _DONE_STATE_GROUPS:
                    all_done = False
                    break

            if all_done and siblings:
                logger.info(
                    "All %d child tasks complete for case %s in %s — resuming lead session",
                    len(siblings), parent_id[:12], workspace_slug,
                )
                await _resume_lead_session(
                    client, pm_session, parent_id,
                    workspace_slug=workspace_slug,
                    project_id=project_id,
                    states=states,
                )

    _last_poll_ts[workspace_slug] = now_iso


async def _resume_lead_session(
    client: httpx.AsyncClient,
    pm_session: dict,
    case_id: str,
    *,
    workspace_slug: str,
    project_id: str,
    states: dict[str, dict],
) -> None:
    """Resume the lead-agent Codex session after all delegated tasks complete.

    Reads specialist results from Plane comments on each child work item
    (posted by the worker after specialist completion), then resumes the
    lead persona's Codex session to synthesize and reply to the human.
    """
    from src.codex_caller import call_codex

    lead_alias = pm_session["lead_alias"]
    session_key = pm_session["session_key"]
    snapshot = await SessionStore.get_case_snapshot(case_id)

    agent_config_dir = settings.resolve_persona_dir(lead_alias)
    if not agent_config_dir:
        logger.error("Cannot resume: no config dir for lead alias +%s", lead_alias)
        return

    # Fetch child items to build results summary
    try:
        children = await _fetch_child_work_items(
            client, workspace_slug, project_id, case_id,
        )
    except httpx.HTTPStatusError:
        children = []

    results_lines = []
    for child in children:
        child_id = str(child.get("id", ""))
        child_title = child.get("name", "") or child.get("title", "")
        child_desc = child.get("description_stripped", "") or ""
        # Extract target_alias from labels
        child_alias = "unknown"
        for label in child.get("labels", []):
            label_name = label if isinstance(label, str) else (label.get("name", "") if isinstance(label, dict) else "")
            if label_name.startswith("target_alias:"):
                child_alias = label_name.split(":", 1)[1]
                break
        child_state_id = str(child.get("state", ""))
        child_state = states.get(child_state_id, {}).get("name", "done")
        # Fetch specialist result from the latest comment on this work item
        specialist_output = ""
        if child_id:
            specialist_output = await _fetch_latest_comment(
                client, workspace_slug, project_id, child_id,
            )
        # Use comment (specialist result) if available, otherwise fall back to description
        result_text = specialist_output or child_desc
        results_lines.append(
            f"### +{child_alias}: {child_title}\n"
            f"State: {child_state}\n"
            f"{result_text[:5000]}"
        )
    specialist_results = "\n\n".join(results_lines) if results_lines else "(no child task details available)"

    display_name = settings.alias_display_name_map.get(lead_alias, "Family Office Agent")
    from_email = alias_email(lead_alias)

    resume_prompt = (
        "All delegated tasks for this case have been completed by the specialist personas. "
        "Below are the results from each specialist.\n\n"
        f"{specialist_results}\n\n"
        "Synthesize these results into a coherent final reply and send it to the human "
        "using `google-workspace-agent-rw.reply_gmail_message`. "
        "Follow the same reply formatting rules: HTML body, natural prose, persona sign-off.\n\n"
        f"Required reply parameters:\n"
        f"- body_format: \"html\"\n"
        f"- from_name: \"{display_name}\"\n"
        f"- from_email: \"{from_email}\"\n"
        f"- body: <your synthesized HTML reply>\n"
    )

    # Try to resume the existing Codex session
    codex_session_id = await SessionStore.get_session(session_key)
    result = None

    if codex_session_id:
        result = await call_codex(
            agent_config_dir=agent_config_dir,
            prompt=resume_prompt,
            session_id=codex_session_id,
        )
        if not result.success:
            logger.warning(
                "Codex session resume failed for case %s (session %s): %s — trying fresh session",
                case_id[:12], codex_session_id[:12], result.error,
            )
            result = None

    if result is None:
        # Fresh session fallback — include full context from snapshot
        context_text = snapshot.get("condensed_context", "") if snapshot else ""
        progress_email = snapshot.get("last_human_email_body", "") if snapshot else ""
        progress_section = (
            f"\nProgress email you sent to the human:\n{progress_email}\n"
            if progress_email else ""
        )
        fallback_prompt = (
            f"You are the +{lead_alias} persona. You previously delegated tasks for a case "
            f"and all tasks have now been completed.\n\n"
            f"Case context:\n{context_text}\n\n"
            f"{progress_section}"
            f"Specialist results:\n{specialist_results}\n\n"
            f"Compose a synthesized HTML reply to the human and send it using "
            f"`google-workspace-agent-rw.reply_gmail_message`.\n"
            f"The source email's message_id is in the case context above — use it for the reply.\n\n"
            f"Required reply parameters:\n"
            f"- body_format: \"html\"\n"
            f"- from_name: \"{display_name}\"\n"
            f"- from_email: \"{from_email}\"\n"
            f"- body: <your synthesized HTML reply>\n"
        )
        result = await call_codex(
            agent_config_dir=agent_config_dir,
            prompt=fallback_prompt,
        )

    if result and result.success:
        new_session_id = result.metadata.get("session_id")
        if new_session_id:
            await SessionStore.store_session(session_key, new_session_id)

        # Verify the Gmail reply tool was actually invoked before closing
        from src.main import _GMAIL_REPLY_TOOL, _extract_gmail_tool_completion

        reply_verified = _extract_gmail_tool_completion(
            result.metadata, {_GMAIL_REPLY_TOOL}
        ) is not None

        if reply_verified:
            logger.info("Lead persona +%s completed synthesis for case %s", lead_alias, case_id[:12])
            await SessionStore.upsert_case_snapshot(
                case_id=case_id,
                condensed_context=(
                    (snapshot.get("condensed_context", "") if snapshot else "")
                    + "\n\n--- All delegation tasks resolved ---"
                ),
            )
            await SessionStore.close_pm_session(case_id)
        else:
            logger.warning(
                "Lead persona +%s synthesis succeeded but Gmail reply not verified for case %s "
                "— keeping PM session open for retry",
                lead_alias, case_id[:12],
            )
    else:
        logger.error(
            "Codex resume failed for case %s (lead +%s) — "
            "case stays open; next human email on thread will trigger response",
            case_id[:12], lead_alias,
        )
