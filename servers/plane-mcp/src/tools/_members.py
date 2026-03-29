"""Shared member resolution helpers for Plane collaboration tools."""

from __future__ import annotations

from typing import Any

from tools._helpers import extract, normalize_list

_IDENTITY_EMAIL_MAP = {
    "cos": "steward.agent+cos@example.com",
    "chief-of-staff": "steward.agent+cos@example.com",
    "chief of staff": "steward.agent+cos@example.com",
    "chief of staff agent": "steward.agent+cos@example.com",
    "estate": "steward.agent+estate@example.com",
    "estate-counsel": "steward.agent+estate@example.com",
    "estate counsel": "steward.agent+estate@example.com",
    "hc": "steward.agent+hc@example.com",
    "comptroller": "steward.agent+hc@example.com",
    "household comptroller": "steward.agent+hc@example.com",
    "hd": "steward.agent+hd@example.com",
    "director": "steward.agent+hd@example.com",
    "household director": "steward.agent+hd@example.com",
    "io": "steward.agent+io@example.com",
    "investment": "steward.agent+io@example.com",
    "investment officer": "steward.agent+io@example.com",
    "portfolio manager": "steward.agent+io@example.com",
    "wellness": "steward.agent+wellness@example.com",
    "wellness advisor": "steward.agent+wellness@example.com",
    "insurance": "steward.agent+insurance@example.com",
    "insurance advisor": "steward.agent+insurance@example.com",
    "ra": "steward.agent+ra@example.com",
    "research": "steward.agent+ra@example.com",
    "research analyst": "steward.agent+ra@example.com",
    "Principal": "principal@example.com",
    "Principal Family": "principal@example.com",
    "principal@example.com": "principal@example.com",
    "Spouse": "spouse@example.com",
    "Spouse singh": "spouse@example.com",
    "spouse@example.com": "spouse@example.com",
}


def member_to_dict(member: Any) -> dict[str, Any]:
    """Normalize a Plane member object to a plain dict."""
    return {
        "id": extract(member, "id"),
        "display_name": extract(member, "display_name"),
        "email": extract(member, "email"),
        "role": extract(member, "role"),
    }


def list_project_members(
    client: Any,
    workspace_slug: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """Return normalized project members."""
    members = normalize_list(
        client.projects.get_members(
            workspace_slug=workspace_slug,
            project_id=project_id,
        )
    )
    return [member_to_dict(member) for member in members]


def list_workspace_members(
    client: Any,
    workspace_slug: str,
) -> list[dict[str, Any]]:
    """Return normalized workspace members."""
    members = normalize_list(
        client.workspaces.get_members(
            workspace_slug=workspace_slug,
        )
    )
    return [member_to_dict(member) for member in members]


def resolve_member(
    client: Any,
    workspace_slug: str,
    project_id: str = "",
    query: str = "",
    member_id: str = "",
) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a project/workspace member by ID, email, display name, or persona alias."""
    members = (
        list_project_members(client, workspace_slug, project_id)
        if project_id
        else list_workspace_members(client, workspace_slug)
    )

    if member_id:
        for member in members:
            if str(extract(member, "id", "")).lower() == member_id.lower():
                return member, None
        return None, f"No member with id '{member_id}' is assignable in this scope."

    normalized_query = query.strip().lower()
    if not normalized_query:
        return None, "Member query cannot be empty."

    queries = {normalized_query}
    alias_email = _IDENTITY_EMAIL_MAP.get(normalized_query)
    if alias_email:
        queries.add(alias_email.lower())

    exact_matches = []
    for member in members:
        member_id_value = str(extract(member, "id", "")).lower()
        display_name = str(extract(member, "display_name", "")).lower()
        email = str(extract(member, "email", "")).lower()
        if member_id_value in queries or display_name in queries or email in queries:
            exact_matches.append(member)

    if len(exact_matches) == 1:
        return exact_matches[0], None
    if len(exact_matches) > 1:
        candidates = ", ".join(
            f"{extract(member, 'display_name')} <{extract(member, 'email')}>"
            for member in exact_matches[:5]
        )
        return None, f"Member query '{query}' is ambiguous: {candidates}"

    fuzzy_matches = []
    for member in members:
        display_name = str(extract(member, "display_name", "")).lower()
        email = str(extract(member, "email", "")).lower()
        if any(token in display_name or token in email for token in queries):
            fuzzy_matches.append(member)

    if len(fuzzy_matches) == 1:
        return fuzzy_matches[0], None
    if len(fuzzy_matches) > 1:
        candidates = ", ".join(
            f"{extract(member, 'display_name')} <{extract(member, 'email')}>"
            for member in fuzzy_matches[:5]
        )
        return None, f"Member query '{query}' is ambiguous: {candidates}"

    return None, f"No member matched '{query}' in this scope."
