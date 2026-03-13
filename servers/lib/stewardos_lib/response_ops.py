"""Shared MCP response envelopes for StewardOS servers."""

from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, Literal

from typing_extensions import NotRequired, Required, TypedDict


class ToolErrorItem(TypedDict, total=False):
    message: str
    code: str


class ToolEnvelope(TypedDict, total=False):
    status: Required[Literal["ok", "error"]]
    errors: Required[list[ToolErrorItem]]
    data: Required[Any]
    provenance: NotRequired[dict[str, Any] | None]
    model_quality: NotRequired[str | None]


def _set_enveloped_return_annotation(fn):
    annotations = dict(getattr(fn, "__annotations__", {}))
    annotations["return"] = ToolEnvelope
    fn.__annotations__ = annotations
    fn.__signature__ = inspect.signature(fn).replace(return_annotation=ToolEnvelope)
    return fn


def _error_list(
    errors: str | dict[str, Any] | list[str | dict[str, Any]] | None,
    *,
    code: str | None = None,
) -> list[dict[str, Any]]:
    if errors in (None, "", []):
        return []

    items = errors if isinstance(errors, list) else [errors]
    normalized: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            payload = dict(item)
            payload.setdefault("message", str(payload.get("message") or payload.get("error") or "Unknown error"))
            if code and not payload.get("code"):
                payload["code"] = code
            normalized.append(payload)
        else:
            payload = {"message": str(item)}
            if code:
                payload["code"] = code
            normalized.append(payload)
    return normalized


def ok_response(
    payload: Any,
    *,
    provenance: dict[str, Any] | None = None,
    model_quality: str | None = None,
) -> dict[str, Any]:
    if isinstance(payload, dict):
        if provenance is None and isinstance(payload.get("provenance"), dict):
            provenance = dict(payload["provenance"])
        if model_quality is None and payload.get("model_quality") is not None:
            model_quality = str(payload["model_quality"])
    response = {"status": "ok", "errors": [], "data": payload}
    if provenance is not None:
        response["provenance"] = provenance
    if model_quality is not None:
        response["model_quality"] = model_quality
    return response


def error_response(
    errors: str | dict[str, Any] | list[str | dict[str, Any]],
    *,
    code: str | None = None,
    provenance: dict[str, Any] | None = None,
    model_quality: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if payload:
        if provenance is None and isinstance(payload.get("provenance"), dict):
            provenance = dict(payload["provenance"])
        if model_quality is None and payload.get("model_quality") is not None:
            model_quality = str(payload["model_quality"])
    response: dict[str, Any] = {
        "status": "error",
        "errors": _error_list(errors, code=code),
        "data": payload,
    }
    if provenance is not None:
        response["provenance"] = provenance
    if model_quality is not None:
        response["model_quality"] = model_quality
    return response


def normalize_tool_output(
    value: Any,
    *,
    provenance: dict[str, Any] | None = None,
    model_quality: str | None = None,
) -> dict[str, Any]:
    payload = value
    if isinstance(payload, str):
        stripped = payload.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            raise TypeError("Stringified JSON tool outputs are unsupported; return native payloads")

    if isinstance(payload, dict):
        status = payload.get("status")
        errors = payload.get("errors")
        looks_like_envelope = status in {"ok", "error"} or "errors" in payload or "data" in payload
        if looks_like_envelope:
            if status not in {"ok", "error"} or not isinstance(errors, list) or "data" not in payload:
                raise TypeError("Invalid tool envelope; use ok_response() or error_response()")
        elif "error" in payload:
            raise TypeError("Legacy bare error payloads are unsupported; use error_response()")
        if status in {"ok", "error"} and isinstance(errors, list):
            normalized = {
                "status": status,
                "errors": errors,
                "data": payload.get("data"),
            }
            if "provenance" in payload:
                normalized["provenance"] = payload["provenance"]
            if "model_quality" in payload:
                normalized["model_quality"] = payload["model_quality"]
            if provenance is not None:
                normalized["provenance"] = provenance
            if model_quality is not None:
                normalized["model_quality"] = model_quality
            return normalized

    return ok_response(payload, provenance=provenance, model_quality=model_quality)


def make_enveloped_tool(mcp):
    def decorator(fn):
        if inspect.iscoroutinefunction(fn):
            @wraps(fn)
            async def async_wrapped(*args, **kwargs):
                return normalize_tool_output(await fn(*args, **kwargs))

            return mcp.tool()(_set_enveloped_return_annotation(async_wrapped))

        @wraps(fn)
        def sync_wrapped(*args, **kwargs):
            return normalize_tool_output(fn(*args, **kwargs))

        return mcp.tool()(_set_enveloped_return_annotation(sync_wrapped))

    return decorator
