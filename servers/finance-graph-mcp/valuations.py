from stewardos_lib.response_ops import make_enveloped_tool as _make_enveloped_tool

from valuation_services import (
    get_ocf_positions as _get_ocf_positions,
    ingest_ocf_document as _ingest_ocf_document,
    list_valuation_methods as _list_valuation_methods,
    list_valuation_observations as _list_valuation_observations,
    record_valuation_observation as _record_valuation_observation,
    set_manual_comp_valuation as _set_manual_comp_valuation,
    upsert_financial_statement_period as _upsert_financial_statement_period,
    upsert_statement_line_items as _upsert_statement_line_items,
    upsert_xbrl_facts_core as _upsert_xbrl_facts_core,
    validate_ocf_document as _validate_ocf_document,
)


def register_valuations_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def list_valuation_methods():
        """List supported valuation methods."""
        return await _list_valuation_methods(get_pool=get_pool)

    @_tool
    async def record_valuation_observation(
        asset_id: int,
        method_code: str,
        value_amount: float,
        value_currency: str = "USD",
        source: str = "manual",
        valuation_date: str | None = None,
        confidence_score: float | None = None,
        notes: str | None = None,
        evidence: dict | str | None = None,
        promote_to_current: str = "auto",
    ):
        """Record a valuation observation and optionally promote it to the canonical current mark."""
        return await _record_valuation_observation(
            get_pool=get_pool,
            asset_id=asset_id,
            method_code=method_code,
            value_amount=value_amount,
            value_currency=value_currency,
            source=source,
            valuation_date=valuation_date,
            confidence_score=confidence_score,
            notes=notes,
            evidence=evidence,
            promote_to_current=promote_to_current,
        )

    @_tool
    async def list_valuation_observations(
        asset_id: int | None = None,
        limit: int = 100,
    ):
        """List valuation observations across assets or for a single asset."""
        return await _list_valuation_observations(
            get_pool=get_pool,
            asset_id=asset_id,
            limit=limit,
        )

    @_tool
    async def set_manual_comp_valuation(
        asset_id: int,
        value_amount: float,
        value_currency: str = "USD",
        valuation_date: str | None = None,
        confidence_score: float | None = None,
        notes: str | None = None,
        comps: list[dict] | str | None = None,
        promote_to_current: str = "auto",
    ):
        """Set a manual comp-based valuation, with optional individual comp records and promotion control."""
        return await _set_manual_comp_valuation(
            get_pool=get_pool,
            asset_id=asset_id,
            value_amount=value_amount,
            value_currency=value_currency,
            valuation_date=valuation_date,
            confidence_score=confidence_score,
            notes=notes,
            comps=comps,
            promote_to_current=promote_to_current,
        )

    @_tool
    async def upsert_financial_statement_period(
        asset_id: int,
        period_start: str,
        period_end: str,
        fiscal_year: int | None = None,
        fiscal_period: str | None = None,
        statement_currency: str = "USD",
        source: str = "manual",
        reporting_period_id: int | None = None,
    ):
        """Create or update a reporting period used by PL/CFS/BS statement fact tables."""
        return await _upsert_financial_statement_period(
            get_pool=get_pool,
            asset_id=asset_id,
            period_start=period_start,
            period_end=period_end,
            fiscal_year=fiscal_year,
            fiscal_period=fiscal_period,
            statement_currency=statement_currency,
            source=source,
            reporting_period_id=reporting_period_id,
        )

    @_tool
    async def upsert_statement_line_items(
        reporting_period_id: int,
        statement_type: str,
        line_items: dict | str,
        source: str = "manual",
        value_currency: str = "USD",
        overwrite: bool = True,
    ):
        """Upsert statement line items for PL/CFS/BS tables."""
        return await _upsert_statement_line_items(
            get_pool=get_pool,
            reporting_period_id=reporting_period_id,
            statement_type=statement_type,
            line_items=line_items,
            source=source,
            value_currency=value_currency,
            overwrite=overwrite,
        )

    @_tool
    async def upsert_xbrl_facts_core(
        accession_number: str,
        facts: list[dict] | str,
        asset_id: int | None = None,
        filing_date: str | None = None,
        cik: str | None = None,
        ticker: str | None = None,
        source: str = "sec-edgar",
    ):
        """Insert XBRL core facts (report/concept/context/unit/fact) for illiquid valuation workflows."""
        return await _upsert_xbrl_facts_core(
            get_pool=get_pool,
            accession_number=accession_number,
            facts=facts,
            asset_id=asset_id,
            filing_date=filing_date,
            cik=cik,
            ticker=ticker,
            source=source,
        )

    @_tool
    async def validate_ocf_document(document: dict | str):
        """Validate an OCF document against a minimal pinned schema contract."""
        return await _validate_ocf_document(document=document)

    @_tool
    async def ingest_ocf_document(
        document: dict | str,
        asset_id: int | None = None,
        run_validation: bool = True,
    ):
        """Store an OCF document payload and derive instrument/position rows."""
        return await _ingest_ocf_document(
            get_pool=get_pool,
            document=document,
            asset_id=asset_id,
            run_validation=run_validation,
        )

    @_tool
    async def get_ocf_positions(
        ocf_document_id: int | None = None,
        asset_id: int | None = None,
        limit: int = 500,
    ):
        """Return OCF-derived position rows."""
        return await _get_ocf_positions(
            get_pool=get_pool,
            ocf_document_id=ocf_document_id,
            asset_id=asset_id,
            limit=limit,
        )
