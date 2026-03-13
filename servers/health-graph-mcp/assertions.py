from __future__ import annotations

from assertion_tool_ops import (
    add_literature_evidence_tool,
    get_polygenic_context_tool,
    get_wellness_recommendations_tool,
    ingest_clinical_assertions_tool,
    ingest_trait_associations_tool,
    query_evidence_graph_tool,
    query_variant_assertions_tool,
)
from stewardos_lib.response_ops import make_enveloped_tool as _make_enveloped_tool


def register_assertion_tools(mcp, get_pool, ensure_initialized):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def ingest_clinical_assertions(
        source_name: str,
        assertions_json: str | dict | list,
        subject_id: int = 0,
    ) -> dict:
        """Ingest clinical assertions from curated sources."""
        return await ingest_clinical_assertions_tool(
            get_pool=get_pool,
            ensure_initialized=ensure_initialized,
            source_name=source_name,
            assertions_json=assertions_json,
            subject_id=subject_id,
        )

    @_tool
    async def query_variant_assertions(
        rsid: str = "",
        gene_symbol: str = "",
        evidence_tier_max: int = 4,
        limit: int = 100,
    ) -> list[dict]:
        """Query clinical assertions by variant or gene."""
        return await query_variant_assertions_tool(
            get_pool=get_pool,
            ensure_initialized=ensure_initialized,
            rsid=rsid,
            gene_symbol=gene_symbol,
            evidence_tier_max=evidence_tier_max,
            limit=limit,
        )

    @_tool
    async def ingest_trait_associations(
        source_name: str,
        associations_json: str | dict | list,
        subject_id: int = 0,
    ) -> dict:
        """Ingest GWAS/PGS-style trait associations with subject-grounded variant checks."""
        return await ingest_trait_associations_tool(
            get_pool=get_pool,
            ensure_initialized=ensure_initialized,
            source_name=source_name,
            associations_json=associations_json,
            subject_id=subject_id,
        )

    @_tool
    async def get_polygenic_context(subject_id: int, limit: int = 100) -> dict:
        """Retrieve association and polygenic context, with research-mode flags."""
        return await get_polygenic_context_tool(
            get_pool=get_pool,
            ensure_initialized=ensure_initialized,
            subject_id=subject_id,
            limit=limit,
        )

    @_tool
    async def add_literature_evidence(
        source_name: str,
        external_id: str,
        title: str,
        url: str = "",
        published_at: str = "",
        abstract_text: str = "",
        assertion_id: int = 0,
        variant_id: int = 0,
        trait_association_id: int = 0,
        notes: str = "",
    ) -> dict:
        """Store literature evidence and link it to assertions/variants/associations."""
        return await add_literature_evidence_tool(
            get_pool=get_pool,
            ensure_initialized=ensure_initialized,
            source_name=source_name,
            external_id=external_id,
            title=title,
            url=url,
            published_at=published_at,
            abstract_text=abstract_text,
            assertion_id=assertion_id,
            variant_id=variant_id,
            trait_association_id=trait_association_id,
            notes=notes,
        )

    @_tool
    async def query_evidence_graph(
        assertion_id: int = 0,
        variant_id: int = 0,
        limit: int = 200,
    ) -> list[dict]:
        """Query evidence links with optional filters."""
        return await query_evidence_graph_tool(
            get_pool=get_pool,
            ensure_initialized=ensure_initialized,
            assertion_id=assertion_id,
            variant_id=variant_id,
            limit=limit,
        )

    @_tool
    async def get_wellness_recommendations(subject_id: int) -> dict:
        """Return policy-gated recommendation summary for wellness advisor."""
        return await get_wellness_recommendations_tool(
            get_pool=get_pool,
            ensure_initialized=ensure_initialized,
            subject_id=subject_id,
        )
