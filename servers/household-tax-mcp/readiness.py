"""Exact support assessment and canonical facts ingestion tools."""

from __future__ import annotations

from typing import Any

from stewardos_lib.response_ops import make_enveloped_tool

from models import (
    parse_entity_type,
    parse_fiduciary_facts,
    parse_individual_facts,
    unsupported_features,
)
from store import durability_mode, new_id, now_iso, persist_document
from tax_config import (
    AUTHORITY_BUNDLE_VERSIONS,
    DEFAULT_TAX_YEAR,
    FEDERAL_FIDUCIARY_KERNELS,
    FEDERAL_INDIVIDUAL_KERNELS,
    FEDERAL_INDIVIDUAL_KERNEL_REASON,
    FIDUCIARY_SUPPORTED_SCOPE,
    INDIVIDUAL_SUPPORTED_SCOPE,
    MASSACHUSETTS_KERNELS,
    SUPPORTED_JURISDICTIONS,
    SUPPORTED_TAX_YEARS,
)


def assess_exact_support_internal(entity_type: str, facts: dict[str, Any]) -> dict[str, Any]:
    normalized_entity = parse_entity_type(entity_type)
    unsupported_reasons = unsupported_features(normalized_entity, facts)

    tax_year = int(facts.get("tax_year", DEFAULT_TAX_YEAR)) if isinstance(facts, dict) else DEFAULT_TAX_YEAR

    try:
        if normalized_entity == "individual":
            parsed = parse_individual_facts(facts)
            tax_year = parsed.tax_year
            normalized_facts = parsed.to_dict()
            supported_scope = list(INDIVIDUAL_SUPPORTED_SCOPE)
            kernels = {
                "federal_kernel": FEDERAL_INDIVIDUAL_KERNELS[tax_year],
                "federal_kernel_reason": FEDERAL_INDIVIDUAL_KERNEL_REASON,
                "massachusetts_kernel": MASSACHUSETTS_KERNELS[tax_year],
            }
        else:
            parsed = parse_fiduciary_facts(facts)
            tax_year = parsed.tax_year
            normalized_facts = parsed.to_dict()
            supported_scope = list(FIDUCIARY_SUPPORTED_SCOPE)
            kernels = {
                "federal_kernel": FEDERAL_FIDUCIARY_KERNELS[tax_year],
                "massachusetts_kernel": MASSACHUSETTS_KERNELS[tax_year],
            }
    except ValueError as exc:
        unsupported_reasons.append(str(exc))
        normalized_facts = None
        supported_scope = []
        kernels = {}

    authority_bundle = AUTHORITY_BUNDLE_VERSIONS.get(tax_year, f"unsupported_{tax_year}")

    return {
        "entity_type": normalized_entity,
        "supported": not unsupported_reasons,
        "unsupported_reasons": unsupported_reasons,
        "tax_year": tax_year,
        "jurisdictions": list(SUPPORTED_JURISDICTIONS),
        "supported_scope": supported_scope,
        "kernels": kernels,
        "authority_bundle_version": authority_bundle,
        "normalized_facts": normalized_facts,
        "provenance": {
            "assessed_at": now_iso(),
            "durability_mode": durability_mode(),
        },
    }


def ingest_return_facts_internal(
    entity_type: str,
    facts: dict[str, Any],
    *,
    source_name: str | None = None,
    source_path: str | None = None,
) -> dict[str, Any]:
    assessment = assess_exact_support_internal(entity_type, facts)
    tax_year = assessment["tax_year"]
    document_id = new_id("return_doc")
    record = {
        "document_id": document_id,
        "entity_type": assessment["entity_type"],
        "tax_year": tax_year,
        "source_name": source_name,
        "source_path": source_path,
        "facts": assessment["normalized_facts"] or facts,
        "support_assessment": {
            "supported": assessment["supported"],
            "unsupported_reasons": assessment["unsupported_reasons"],
            "supported_scope": assessment["supported_scope"],
            "authority_bundle_version": assessment["authority_bundle_version"],
            "kernels": assessment["kernels"],
        },
        "ingested_at": now_iso(),
    }
    persist_document(record)
    return {
        "document_id": document_id,
        "entity_type": record["entity_type"],
        "tax_year": tax_year,
        "source_name": source_name,
        "source_path": source_path,
        "facts": record["facts"],
        "support_assessment": record["support_assessment"],
        "provenance": {
            "ingested_at": record["ingested_at"],
            "durability_mode": durability_mode(),
        },
    }


def register_readiness_tools(mcp) -> None:
    tool = make_enveloped_tool(mcp)

    @tool
    def assess_exact_support(entity_type: str, facts: dict[str, Any]) -> dict[str, Any]:
        """Assess whether facts are inside the exact 2025/2026 US+MA scope."""

        return assess_exact_support_internal(entity_type, facts)

    @tool
    def ingest_return_facts(
        entity_type: str,
        facts: dict[str, Any],
        source_name: str | None = None,
        source_path: str | None = None,
    ) -> dict[str, Any]:
        """Persist canonical facts and the associated exact-support assessment."""

        return ingest_return_facts_internal(
            entity_type,
            facts,
            source_name=source_name,
            source_path=source_path,
        )
