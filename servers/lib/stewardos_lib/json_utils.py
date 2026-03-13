"""JSON parsing utilities shared across MCP servers."""

import json

from stewardos_lib.db import float_or_none


def coerce_json_input(value) -> dict:
    """Coerce a value to a dict, parsing JSON strings if needed."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def extract_numeric_value(payload: dict) -> float | None:
    """Best-effort extraction from heterogeneous valuation payloads."""
    if not isinstance(payload, dict):
        return None

    scalar_keys = (
        "price",
        "value",
        "avm",
        "estimate",
        "estimatedValue",
        "estimated_value",
    )
    for key in scalar_keys:
        maybe = float_or_none(payload.get(key))
        if maybe is not None:
            return maybe

    nested_keys = ("data", "valuation", "result", "results")
    for key in nested_keys:
        nested = payload.get(key)
        if isinstance(nested, dict):
            maybe = extract_numeric_value(nested)
            if maybe is not None:
                return maybe
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    maybe = extract_numeric_value(item)
                    if maybe is not None:
                        return maybe
    return None
