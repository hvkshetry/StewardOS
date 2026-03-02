"""MCP server for medical documents via Paperless-ngx.

Wraps the existing Paperless-ngx instance, filtering for medical/health
documents using tags and document types. Provides medical-specific views
on top of the general Paperless-ngx API.
"""

import os
from datetime import date, timedelta
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

PAPERLESS_URL = os.environ.get("PAPERLESS_URL", "http://localhost:8223")
PAPERLESS_API_TOKEN = os.environ.get("PAPERLESS_API_TOKEN", "")

# Medical tag names used for filtering
MEDICAL_TAGS = ["medical", "insurance", "lab-results", "prescription", "referral"]

mcp = FastMCP(
    "health-records-mcp",
    instructions=(
        "Medical records and health document server. Wraps Paperless-ngx to "
        "search, upload, and retrieve medical documents, lab results, insurance "
        "paperwork, and prescriptions. All documents are OCR'd and searchable. "
        "Correspondents represent healthcare providers (doctors, clinics, labs)."
    ),
)


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Token {PAPERLESS_API_TOKEN}",
    }


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=PAPERLESS_URL,
        headers=_headers(),
        timeout=60.0,
    )


async def _request(method: str, path: str, **kwargs) -> dict | list | str:
    """Execute an HTTP request against the Paperless-ngx API."""
    try:
        async with _client() as client:
            resp = await client.request(method, path, **kwargs)
            resp.raise_for_status()
            if resp.status_code == 204:
                return {"status": "success"}
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                return resp.json()
            return resp.text
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.RequestError as exc:
        return f"Request failed: {exc}"


async def _get_tag_ids(tag_names: list[str]) -> list[int]:
    """Resolve tag names to IDs."""
    result = await _request("GET", "/api/tags/", params={"page_size": 1000})
    if isinstance(result, str):
        return []
    tags = result.get("results", [])
    name_to_id = {t["name"].lower(): t["id"] for t in tags}
    return [name_to_id[n.lower()] for n in tag_names if n.lower() in name_to_id]


async def _get_correspondent_id(name: str) -> int | None:
    """Resolve a correspondent (provider) name to its ID."""
    result = await _request("GET", "/api/correspondents/", params={"page_size": 1000})
    if isinstance(result, str):
        return None
    for c in result.get("results", []):
        if c["name"].lower() == name.lower():
            return c["id"]
    return None


# ─── Existing tools (enhanced) ───


@mcp.tool()
async def search_medical_documents(query: str = "", limit: int = 20) -> dict | list | str:
    """Search Paperless for documents tagged with any medical tag.

    Optional query string filters further by content/title.
    """
    tag_ids = await _get_tag_ids(MEDICAL_TAGS)
    params: dict = {"page_size": limit, "ordering": "-created"}
    if tag_ids:
        params["tags__id__in"] = ",".join(str(i) for i in tag_ids)
    if query:
        params["query"] = query
    return await _request("GET", "/api/documents/", params=params)


@mcp.tool()
async def get_document_content(document_id: int) -> dict | str:
    """Retrieve the OCR'd text content of a medical document by its ID."""
    result = await _request("GET", f"/api/documents/{document_id}/")
    if isinstance(result, str):
        return result
    return {
        "id": result.get("id"),
        "title": result.get("title", ""),
        "content": result.get("content", ""),
        "created": result.get("created", ""),
        "tags": result.get("tags", []),
        "correspondent": result.get("correspondent"),
        "document_type": result.get("document_type"),
    }


@mcp.tool()
async def get_recent_lab_results(days: int = 90) -> dict | list | str:
    """Get documents tagged 'lab-results' from the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    tag_ids = await _get_tag_ids(["lab-results"])
    params: dict = {
        "page_size": 20,
        "ordering": "-created",
        "created__date__gte": since,
    }
    if tag_ids:
        params["tags__id__in"] = ",".join(str(i) for i in tag_ids)
    return await _request("GET", "/api/documents/", params=params)


@mcp.tool()
async def list_insurance_documents() -> dict | list | str:
    """List documents tagged 'insurance' (policies, EOBs, insurance cards)."""
    tag_ids = await _get_tag_ids(["insurance"])
    params: dict = {"page_size": 50, "ordering": "-created"}
    if tag_ids:
        params["tags__id__in"] = ",".join(str(i) for i in tag_ids)
    return await _request("GET", "/api/documents/", params=params)


# ─── New tools ───


@mcp.tool()
async def upload_medical_document(
    title: str,
    file_path: str,
    tags: list[str] | None = None,
    correspondent: str = "",
    document_type: str = "",
) -> dict | str:
    """Upload a medical document with auto-tagging.

    Args:
        title: Document title
        file_path: Absolute path to the file on disk
        tags: Tag names to apply (e.g., ['medical', 'lab-results']). Defaults to ['medical'].
        correspondent: Provider/clinic name (must exist as a correspondent)
        document_type: Document type name (e.g., 'EOB', 'Prescription', 'Lab Report')
    """
    if tags is None:
        tags = ["medical"]

    path = Path(file_path)
    if not path.is_file():
        return f"File not found: {file_path}"

    try:
        async with _client() as client:
            # Build multipart form fields as list of tuples to support
            # repeated keys (Paperless expects one "tags" field per tag)
            form_fields: list[tuple[str, str]] = [("title", title)]

            tag_ids = await _get_tag_ids(tags)
            for tid in tag_ids:
                form_fields.append(("tags", str(tid)))

            if correspondent:
                corr_id = await _get_correspondent_id(correspondent)
                if corr_id is not None:
                    form_fields.append(("correspondent", str(corr_id)))

            if document_type:
                dt_result = await _request(
                    "GET", "/api/document_types/", params={"page_size": 1000}
                )
                if not isinstance(dt_result, str):
                    for dt in dt_result.get("results", []):
                        if dt["name"].lower() == document_type.lower():
                            form_fields.append(("document_type", str(dt["id"])))
                            break

            files = {"document": (path.name, path.read_bytes())}
            resp = await client.post(
                "/api/documents/post_document/",
                data=form_fields,
                files=files,
            )
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                return resp.json()
            return {"status": "accepted", "task_id": resp.text.strip('"')}
    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code}: {exc.response.text}"
    except httpx.RequestError as exc:
        return f"Request failed: {exc}"


@mcp.tool()
async def update_document_tags(
    document_id: int,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
) -> dict | str:
    """Reclassify a document by adding or removing tags.

    Args:
        document_id: Document ID
        add_tags: Tag names to add
        remove_tags: Tag names to remove
    """
    if add_tags is None:
        add_tags = []
    if remove_tags is None:
        remove_tags = []

    doc = await _request("GET", f"/api/documents/{document_id}/")
    if isinstance(doc, str):
        return doc

    current_tags = set(doc.get("tags", []))
    add_ids = set(await _get_tag_ids(add_tags))
    remove_ids = set(await _get_tag_ids(remove_tags))

    new_tags = list((current_tags | add_ids) - remove_ids)
    return await _request(
        "PATCH",
        f"/api/documents/{document_id}/",
        json={"tags": new_tags},
    )


@mcp.tool()
async def list_providers() -> dict | list | str:
    """List all healthcare providers (correspondents in Paperless-ngx)."""
    return await _request("GET", "/api/correspondents/", params={"page_size": 1000})


@mcp.tool()
async def get_documents_by_provider(
    provider: str,
    limit: int = 20,
) -> dict | list | str:
    """Get medical documents from a specific provider (doctor, clinic, lab).

    Args:
        provider: Provider name (correspondent name in Paperless-ngx)
        limit: Maximum results (default 20)
    """
    corr_id = await _get_correspondent_id(provider)
    if corr_id is None:
        return f"Provider '{provider}' not found"

    medical_tag_ids = await _get_tag_ids(MEDICAL_TAGS)
    params: dict = {
        "page_size": limit,
        "ordering": "-created",
        "correspondent__id": corr_id,
    }
    if medical_tag_ids:
        params["tags__id__in"] = ",".join(str(i) for i in medical_tag_ids)
    return await _request("GET", "/api/documents/", params=params)


@mcp.tool()
async def list_document_types() -> dict | list | str:
    """List all document types (EOB, Prescription, Referral, Lab Report, etc.)."""
    return await _request("GET", "/api/document_types/", params={"page_size": 1000})


@mcp.tool()
async def get_document_suggestions(document_id: int) -> dict | str:
    """Get AI-powered classification suggestions for a document.

    Returns suggested tags, correspondent, and document type.

    Args:
        document_id: Document ID to get suggestions for
    """
    return await _request("GET", f"/api/documents/{document_id}/suggestions/")


@mcp.tool()
async def list_prescriptions(days: int = 365) -> dict | list | str:
    """List prescription documents from the last N days.

    Args:
        days: Number of days to look back (default 365)
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    tag_ids = await _get_tag_ids(["prescription"])
    params: dict = {
        "page_size": 50,
        "ordering": "-created",
        "created__date__gte": since,
    }
    if tag_ids:
        params["tags__id__in"] = ",".join(str(i) for i in tag_ids)
    return await _request("GET", "/api/documents/", params=params)


if __name__ == "__main__":
    mcp.run()
