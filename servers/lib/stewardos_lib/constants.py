"""Shared constants across estate-planning and finance-graph servers."""

import re

ASSET_TYPE_BY_CLASS = {
    "real_estate": "real_estate",
    "private_equity": "securities",
}

REAL_ESTATE_SUBCLASSES = {
    "real_estate_residential",
    "real_estate_land",
    "real_estate_commercial",
    "real_estate_agricultural",
}

OCF_MINIMAL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "ocf_version": {"type": "string"},
    },
    "required": ["ocf_version"],
}

ISO_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def canonical_asset_type(asset_class_code: str, asset_subclass_code: str) -> str:
    """Determine the canonical asset type from class/subclass codes."""
    class_code = (asset_class_code or "").strip().lower()
    subclass_code = (asset_subclass_code or "").strip().lower()
    if class_code == "real_estate" or subclass_code in REAL_ESTATE_SUBCLASSES:
        return "real_estate"
    return ASSET_TYPE_BY_CLASS.get(class_code, "other")
