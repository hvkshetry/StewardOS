from stewardos_lib.response_ops import make_enveloped_tool as _make_enveloped_tool

from ips_target_services import (
    activate_ips_target_profile as _activate_ips_target_profile,
    get_ips_target_profile as _get_ips_target_profile,
    list_ips_bucket_lookthrough as _list_ips_bucket_lookthrough,
    list_ips_bucket_overrides as _list_ips_bucket_overrides,
    list_ips_target_profiles as _list_ips_target_profiles,
    resolve_ips_target_profile as _resolve_ips_target_profile,
    upsert_ips_bucket_lookthrough as _upsert_ips_bucket_lookthrough,
    upsert_ips_bucket_override as _upsert_ips_bucket_override,
    upsert_ips_target_allocations as _upsert_ips_target_allocations,
    upsert_ips_target_profile as _upsert_ips_target_profile,
)


def register_ips_targets_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def upsert_ips_target_profile(
        profile_code: str,
        name: str,
        effective_from: str,
        status: str = "draft",
        profile_id: int | None = None,
        effective_to: str | None = None,
        base_currency: str = "USD",
        scope_entity: str = "all",
        scope_wrapper: str = "all",
        scope_owner: str = "all",
        scope_account_types: list[str] | str | None = None,
        drift_threshold: float = 0.03,
        rebalance_band_abs: float | None = None,
        review_cadence: str | None = None,
        notes: str | None = None,
        metadata: dict | str | None = None,
    ):
        """Create or update an IPS target profile with scope and rebalancing policy metadata."""
        return await _upsert_ips_target_profile(
            get_pool=get_pool,
            profile_code=profile_code,
            name=name,
            effective_from=effective_from,
            status=status,
            profile_id=profile_id,
            effective_to=effective_to,
            base_currency=base_currency,
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_owner=scope_owner,
            scope_account_types=scope_account_types,
            drift_threshold=drift_threshold,
            rebalance_band_abs=rebalance_band_abs,
            review_cadence=review_cadence,
            notes=notes,
            metadata=metadata,
        )

    @_tool
    async def upsert_ips_target_allocations(
        profile_id: int,
        allocations: list[dict] | str,
        overwrite: bool = True,
    ):
        """Upsert IPS allocation rows for a profile (bucket targets + optional min/max bands)."""
        return await _upsert_ips_target_allocations(
            get_pool=get_pool,
            profile_id=profile_id,
            allocations=allocations,
            overwrite=overwrite,
        )

    @_tool
    async def activate_ips_target_profile(
        profile_id: int,
        tolerance: float = 0.0001,
    ):
        """Validate and activate an IPS profile. Activation requires bucket weights summing to 100%."""
        return await _activate_ips_target_profile(
            get_pool=get_pool,
            profile_id=profile_id,
            tolerance=tolerance,
        )

    @_tool
    async def list_ips_target_profiles(
        status: str | None = None,
        scope_entity: str | None = None,
        scope_wrapper: str | None = None,
        scope_owner: str | None = None,
        as_of: str | None = None,
        limit: int = 200,
    ):
        """List IPS target profiles with optional status/scope/effective-date filters."""
        return await _list_ips_target_profiles(
            get_pool=get_pool,
            status=status,
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_owner=scope_owner,
            as_of=as_of,
            limit=limit,
        )

    @_tool
    async def get_ips_target_profile(profile_id: int):
        """Get one IPS profile with allocations, active bucket overrides, and lookthrough rows."""
        return await _get_ips_target_profile(get_pool=get_pool, profile_id=profile_id)

    @_tool
    async def resolve_ips_target_profile(
        as_of: str | None = None,
        scope_entity: str = "all",
        scope_wrapper: str = "all",
        scope_owner: str = "all",
        scope_account_types: list[str] | str | None = None,
    ):
        """Resolve the best active IPS profile for a scope using deterministic precedence rules."""
        return await _resolve_ips_target_profile(
            get_pool=get_pool,
            as_of=as_of,
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_owner=scope_owner,
            scope_account_types=scope_account_types,
        )

    @_tool
    async def upsert_ips_bucket_override(
        symbol: str,
        override_bucket_key: str,
        data_source: str = "YAHOO",
        override_id: int | None = None,
        scope_entity: str = "all",
        scope_wrapper: str = "all",
        scope_owner: str = "all",
        scope_account_types: list[str] | str | None = None,
        active: bool = True,
        notes: str | None = None,
    ):
        """Create or update a symbol-level bucket override rule for IPS bucket drift mapping."""
        return await _upsert_ips_bucket_override(
            get_pool=get_pool,
            symbol=symbol,
            override_bucket_key=override_bucket_key,
            data_source=data_source,
            override_id=override_id,
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_owner=scope_owner,
            scope_account_types=scope_account_types,
            active=active,
            notes=notes,
        )

    @_tool
    async def list_ips_bucket_overrides(
        symbol: str | None = None,
        data_source: str | None = None,
        active_only: bool = True,
        scope_entity: str | None = None,
        scope_wrapper: str | None = None,
        scope_owner: str | None = None,
        limit: int = 500,
    ):
        """List IPS symbol-to-bucket override rules."""
        return await _list_ips_bucket_overrides(
            get_pool=get_pool,
            symbol=symbol,
            data_source=data_source,
            active_only=active_only,
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_owner=scope_owner,
            limit=limit,
        )

    @_tool
    async def upsert_ips_bucket_lookthrough(
        symbol: str,
        allocations: list[dict] | str,
        data_source: str = "YAHOO",
        scope_entity: str = "all",
        scope_wrapper: str = "all",
        scope_owner: str = "all",
        scope_account_types: list[str] | str | None = None,
        source_as_of: str | None = None,
        active: bool = True,
        notes: str | None = None,
        metadata: dict | str | None = None,
        overwrite: bool = True,
    ):
        """Create or update symbol-level IPS lookthrough rules with fractional bucket weights."""
        return await _upsert_ips_bucket_lookthrough(
            get_pool=get_pool,
            symbol=symbol,
            allocations=allocations,
            data_source=data_source,
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_owner=scope_owner,
            scope_account_types=scope_account_types,
            source_as_of=source_as_of,
            active=active,
            notes=notes,
            metadata=metadata,
            overwrite=overwrite,
        )

    @_tool
    async def list_ips_bucket_lookthrough(
        symbol: str | None = None,
        data_source: str | None = None,
        active_only: bool = True,
        scope_entity: str | None = None,
        scope_wrapper: str | None = None,
        scope_owner: str | None = None,
        limit: int = 1000,
    ):
        """List IPS symbol lookthrough rows used for fractional bucket classification."""
        return await _list_ips_bucket_lookthrough(
            get_pool=get_pool,
            symbol=symbol,
            data_source=data_source,
            active_only=active_only,
            scope_entity=scope_entity,
            scope_wrapper=scope_wrapper,
            scope_owner=scope_owner,
            limit=limit,
        )
