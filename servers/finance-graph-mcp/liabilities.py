from liability_tool_ops import (
    analyze_heloc_economics as _analyze_heloc_economics,
    analyze_refinance_npv as _analyze_refinance_npv,
    generate_liability_amortization as _generate_liability_amortization,
    get_liability_summary as _get_liability_summary,
    get_refi_opportunities as _get_refi_opportunities,
    list_liabilities as _list_liabilities,
    list_liability_types as _list_liability_types,
    record_liability_payment as _record_liability_payment,
    record_liability_rate_reset as _record_liability_rate_reset,
    record_refinance_offer as _record_refinance_offer,
    upsert_liability as _upsert_liability,
)
from stewardos_lib.response_ops import make_enveloped_tool as _make_enveloped_tool


def register_liabilities_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def list_liability_types() -> list[dict]:
        """List supported liability types."""
        return await _list_liability_types(await get_pool())

    @_tool
    async def upsert_liability(
        name: str,
        liability_type_code: str,
        outstanding_principal: float,
        currency: str,
        liability_id: int | None = None,
        borrower_person_id: int | None = None,
        borrower_entity_id: int | None = None,
        jurisdiction_code: str | None = None,
        collateral_asset_id: int | None = None,
        lender_name: str | None = None,
        account_number_last4: str | None = None,
        origination_date: str | None = None,
        maturity_date: str | None = None,
        original_principal: float | None = None,
        credit_limit: float | None = None,
        rate_type: str = "fixed",
        rate_index: str | None = None,
        interest_rate: float | None = None,
        rate_spread_bps: float | None = None,
        amortization_months: int | None = None,
        remaining_term_months: int | None = None,
        payment_frequency: str = "monthly",
        scheduled_payment: float | None = None,
        escrow_payment: float | None = None,
        next_payment_date: str | None = None,
        prepayment_penalty: float | None = None,
        status: str = "active",
        metadata: dict | str | None = None,
    ) -> dict:
        """Create or update a long-term liability (mortgage/HELOC/etc.)."""
        return await _upsert_liability(
            await get_pool(),
            name=name,
            liability_type_code=liability_type_code,
            outstanding_principal=outstanding_principal,
            currency=currency,
            liability_id=liability_id,
            borrower_person_id=borrower_person_id,
            borrower_entity_id=borrower_entity_id,
            jurisdiction_code=jurisdiction_code,
            collateral_asset_id=collateral_asset_id,
            lender_name=lender_name,
            account_number_last4=account_number_last4,
            origination_date=origination_date,
            maturity_date=maturity_date,
            original_principal=original_principal,
            credit_limit=credit_limit,
            rate_type=rate_type,
            rate_index=rate_index,
            interest_rate=interest_rate,
            rate_spread_bps=rate_spread_bps,
            amortization_months=amortization_months,
            remaining_term_months=remaining_term_months,
            payment_frequency=payment_frequency,
            scheduled_payment=scheduled_payment,
            escrow_payment=escrow_payment,
            next_payment_date=next_payment_date,
            prepayment_penalty=prepayment_penalty,
            status=status,
            metadata=metadata,
        )

    @_tool
    async def list_liabilities(
        status: str | None = None,
        borrower_person_id: int | None = None,
        borrower_entity_id: int | None = None,
        collateral_asset_id: int | None = None,
        jurisdiction_code: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        """List liabilities with optional filters."""
        return await _list_liabilities(
            await get_pool(),
            status=status,
            borrower_person_id=borrower_person_id,
            borrower_entity_id=borrower_entity_id,
            collateral_asset_id=collateral_asset_id,
            jurisdiction_code=jurisdiction_code,
            limit=limit,
        )

    @_tool
    async def record_liability_rate_reset(
        liability_id: int,
        effective_date: str,
        rate_type: str,
        interest_rate: float,
        rate_index: str | None = None,
        rate_spread_bps: float | None = None,
        cap_rate: float | None = None,
        floor_rate: float | None = None,
        reset_frequency_months: int | None = None,
        notes: str | None = None,
        metadata: dict | str | None = None,
    ) -> dict:
        """Record a new rate term (ARM/variable reset) and update current liability rate fields."""
        return await _record_liability_rate_reset(
            await get_pool(),
            liability_id=liability_id,
            effective_date=effective_date,
            rate_type=rate_type,
            interest_rate=interest_rate,
            rate_index=rate_index,
            rate_spread_bps=rate_spread_bps,
            cap_rate=cap_rate,
            floor_rate=floor_rate,
            reset_frequency_months=reset_frequency_months,
            notes=notes,
            metadata=metadata,
        )

    @_tool
    async def record_liability_payment(
        liability_id: int,
        payment_date: str,
        amount_total: float,
        amount_principal: float | None = None,
        amount_interest: float | None = None,
        amount_escrow: float | None = None,
        idempotency_key: str | None = None,
        source: str = "manual",
        reference: str | None = None,
        metadata: dict | str | None = None,
    ) -> dict:
        """Record an idempotent payment and update outstanding principal."""
        return await _record_liability_payment(
            await get_pool(),
            liability_id=liability_id,
            payment_date=payment_date,
            amount_total=amount_total,
            amount_principal=amount_principal,
            amount_interest=amount_interest,
            amount_escrow=amount_escrow,
            idempotency_key=idempotency_key,
            source=source,
            reference=reference,
            metadata=metadata,
        )

    @_tool
    async def generate_liability_amortization(
        liability_id: int,
        scenario_tag: str = "base",
        months: int | None = None,
        annual_rate_override: float | None = None,
        payment_total_override: float | None = None,
        escrow_payment_override: float | None = None,
        start_date: str | None = None,
    ) -> dict:
        """Generate amortization schedule rows for a liability and scenario."""
        return await _generate_liability_amortization(
            await get_pool(),
            liability_id=liability_id,
            scenario_tag=scenario_tag,
            months=months,
            annual_rate_override=annual_rate_override,
            payment_total_override=payment_total_override,
            escrow_payment_override=escrow_payment_override,
            start_date=start_date,
        )

    @_tool
    async def record_refinance_offer(
        liability_id: int,
        offer_date: str,
        offered_rate: float,
        offered_term_months: int,
        lender_name: str | None = None,
        product_type: str = "rate_term_refi",
        rate_type: str = "fixed",
        offered_principal: float | None = None,
        points_cost: float = 0.0,
        lender_fees: float = 0.0,
        third_party_fees: float = 0.0,
        prepayment_penalty_cost: float = 0.0,
        cash_out_amount: float = 0.0,
        metadata: dict | str | None = None,
    ) -> dict:
        """Record a refinance/cash-out/HELOC offer for later economics analysis."""
        return await _record_refinance_offer(
            await get_pool(),
            liability_id=liability_id,
            offer_date=offer_date,
            offered_rate=offered_rate,
            offered_term_months=offered_term_months,
            lender_name=lender_name,
            product_type=product_type,
            rate_type=rate_type,
            offered_principal=offered_principal,
            points_cost=points_cost,
            lender_fees=lender_fees,
            third_party_fees=third_party_fees,
            prepayment_penalty_cost=prepayment_penalty_cost,
            cash_out_amount=cash_out_amount,
            metadata=metadata,
        )

    @_tool
    async def analyze_refinance_npv(
        liability_id: int,
        refinance_offer_id: int,
        discount_rate_annual: float = 0.05,
    ) -> dict:
        """Analyze refinance economics and persist a recommendation run."""
        return await _analyze_refinance_npv(
            await get_pool(),
            liability_id=liability_id,
            refinance_offer_id=refinance_offer_id,
            discount_rate_annual=discount_rate_annual,
        )

    @_tool
    async def analyze_heloc_economics(
        liability_id: int,
        draw_amount: float,
        draw_term_months: int,
        heloc_rate: float,
        alternative_rate: float | None = None,
        discount_rate_annual: float = 0.05,
        origination_cost: float = 0.0,
    ) -> dict:
        """Compare a prospective HELOC draw to an alternative borrowing rate."""
        return await _analyze_heloc_economics(
            await get_pool(),
            liability_id=liability_id,
            draw_amount=draw_amount,
            draw_term_months=draw_term_months,
            heloc_rate=heloc_rate,
            alternative_rate=alternative_rate,
            discount_rate_annual=discount_rate_annual,
            origination_cost=origination_cost,
        )

    @_tool
    async def get_refi_opportunities(
        min_npv_savings: float = 0.0,
        max_break_even_months: float = 36.0,
        discount_rate_annual: float = 0.05,
        include_hold: bool = False,
    ) -> dict:
        """Rank active liabilities with latest refi offers by projected NPV savings."""
        return await _get_refi_opportunities(
            await get_pool(),
            min_npv_savings=min_npv_savings,
            max_break_even_months=max_break_even_months,
            discount_rate_annual=discount_rate_annual,
            include_hold=include_hold,
        )

    @_tool
    async def get_liability_summary(
        status: str = "active",
        jurisdiction: str | None = None,
        borrower_person_id: int | None = None,
        borrower_entity_id: int | None = None,
    ) -> dict:
        """Return aggregated debt exposure and weighted-rate summary."""
        return await _get_liability_summary(
            await get_pool(),
            status=status,
            jurisdiction=jurisdiction,
            borrower_person_id=borrower_person_id,
            borrower_entity_id=borrower_entity_id,
        )
