"""Shared label helpers for Plane work items."""

from __future__ import annotations

from typing import Any

from plane.models.labels import CreateLabel

from tools._helpers import extract, normalize_list


def fetch_existing_labels(
    client: Any,
    workspace_slug: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """Fetch all project labels and normalize them to plain dicts."""
    items = normalize_list(
        client.labels.list(workspace_slug=workspace_slug, project_id=project_id)
    )
    results = []
    for label in items:
        results.append({
            "id": extract(label, "id"),
            "name": extract(label, "name"),
            "color": extract(label, "color"),
        })
    return results


def ensure_label_exists(
    client: Any,
    workspace_slug: str,
    project_id: str,
    label_name: str,
    existing_labels: list[dict[str, Any]],
) -> str:
    """Find or create a label by name, returning its ID."""
    for label in existing_labels:
        if extract(label, "name") == label_name:
            return extract(label, "id")

    new_label = client.labels.create(
        workspace_slug=workspace_slug,
        project_id=project_id,
        data=CreateLabel(name=label_name, color="#6366f1"),
    )
    label_id = extract(new_label, "id")
    existing_labels.append({
        "id": label_id,
        "name": label_name,
        "color": "#6366f1",
    })
    return label_id


def resolve_label_ids(
    client: Any,
    workspace_slug: str,
    project_id: str,
    label_names: list[str],
    existing_labels: list[dict[str, Any]],
) -> list[str]:
    """Resolve label names to IDs, creating any missing labels."""
    ids = []
    for label_name in label_names:
        ids.append(
            ensure_label_exists(
                client,
                workspace_slug,
                project_id,
                label_name,
                existing_labels,
            )
        )
    return ids


def resolve_label_query(
    existing_labels: list[dict[str, Any]],
    query: str,
) -> tuple[str | None, str | None]:
    """Resolve a label name or ID to a canonical label ID."""
    normalized = query.strip().lower()
    if not normalized:
        return None, "Label query cannot be empty."

    exact_matches = [
        label
        for label in existing_labels
        if str(extract(label, "id", "")).lower() == normalized
        or str(extract(label, "name", "")).lower() == normalized
    ]
    if len(exact_matches) == 1:
        return extract(exact_matches[0], "id"), None
    if len(exact_matches) > 1:
        return None, f"Label query '{query}' matched multiple labels."

    fuzzy_matches = [
        label
        for label in existing_labels
        if normalized in str(extract(label, "name", "")).lower()
    ]
    if len(fuzzy_matches) == 1:
        return extract(fuzzy_matches[0], "id"), None
    if len(fuzzy_matches) > 1:
        names = ", ".join(str(extract(label, "name")) for label in fuzzy_matches[:5])
        return None, f"Label query '{query}' is ambiguous: {names}"

    return None, f"No project label matched '{query}'."
