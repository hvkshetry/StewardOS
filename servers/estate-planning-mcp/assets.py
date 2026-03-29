import json

from stewardos_lib.constants import canonical_asset_type as _canonical_asset_type
from stewardos_lib.db import row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import (
    parse_iso_date as _parse_iso_date,
    resolve_exact_one_owner as _resolve_exact_one_owner,
)
from stewardos_lib.json_utils import coerce_json_input as _coerce_json_input
from stewardos_lib.response_ops import (
    error_response as _error_response,
    make_enveloped_tool as _make_enveloped_tool,
)


def register_assets_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def list_assets(
        asset_class_code: str | None = None,
        asset_subclass_code: str | None = None,
        jurisdiction: str | None = None,
        owner_entity_id: int | None = None,
        owner_person_id: int | None = None,
    ):
        """List assets with optional normalized taxonomy filters.

        Args:
            asset_class_code: Filter by normalized class code.
            asset_subclass_code: Filter by normalized subclass code.
            jurisdiction: Filter by jurisdiction code.
            owner_entity_id: Filter by owning entity ID.
            owner_person_id: Filter by owning person ID.
        """
        pool = await get_pool()
        query = """
            SELECT a.id, a.name, a.asset_type,
                   cvo.value_amount AS current_valuation_amount,
                   cvo.value_currency AS valuation_currency,
                   cvo.valuation_date,
                   j.code AS jurisdiction,
                   COALESCE(e.name, p.legal_name) AS owner_name,
                   ac.code AS asset_class_code,
                   ascb.code AS asset_subclass_code,
                   at.country_code,
                   at.region_code,
                   rea.property_type
            FROM assets a
            LEFT JOIN finance.valuation_observations cvo
                   ON cvo.asset_id = a.id AND cvo.is_current = true
            LEFT JOIN jurisdictions j ON a.jurisdiction_id = j.id
            LEFT JOIN entities e ON a.owner_entity_id = e.id
            LEFT JOIN people p ON a.owner_person_id = p.id
            LEFT JOIN finance.asset_taxonomy at ON at.asset_id = a.id
            LEFT JOIN finance.asset_classes ac ON at.asset_class_id = ac.id
            LEFT JOIN finance.asset_subclasses ascb ON at.asset_subclass_id = ascb.id
            LEFT JOIN finance.real_estate_assets rea ON rea.asset_id = a.id
            WHERE 1=1
        """
        params = []
        idx = 1
        if asset_class_code:
            query += f" AND ac.code = ${idx}"
            params.append(asset_class_code.strip().lower())
            idx += 1
        if asset_subclass_code:
            query += f" AND ascb.code = ${idx}"
            params.append(asset_subclass_code.strip().lower())
            idx += 1
        if jurisdiction:
            query += f" AND j.code = ${idx}"
            params.append(jurisdiction)
            idx += 1
        if owner_entity_id:
            query += f" AND a.owner_entity_id = ${idx}"
            params.append(owner_entity_id)
            idx += 1
        if owner_person_id:
            query += f" AND a.owner_person_id = ${idx}"
            params.append(owner_person_id)
            idx += 1
        query += " ORDER BY a.name"
        rows = await pool.fetch(query, *params)
        return _rows_to_list(rows)

    @_tool
    async def upsert_asset(
        name: str,
        asset_class_code: str,
        asset_subclass_code: str,
        jurisdiction_code: str,
        owner_entity_id: int | None = None,
        owner_person_id: int | None = None,
        acquisition_date: str | None = None,
        acquisition_cost: float | None = None,
        paperless_doc_id: int | None = None,
        ghostfolio_account_id: str | None = None,
        address: str | None = None,
        description: str | None = None,
        notes: str | None = None,
        country_code: str | None = None,
        state_code: str | None = None,
        city: str | None = None,
        postal_code: str | None = None,
        address_line1: str | None = None,
        property_type: str | None = None,
        land_area: float | None = None,
        land_area_unit: str | None = None,
        building_area: float | None = None,
        building_area_unit: str | None = None,
        bedrooms: int | None = None,
        bathrooms: float | None = None,
        year_built: int | None = None,
        parcel_id: str | None = None,
        metadata: dict | str | None = None,
        asset_id: int | None = None,
    ):
        """Create or update an asset using normalized class/subclass taxonomy.

        This is a breaking interface by design:
        - `asset_class_code` and `asset_subclass_code` are required.
        - `jurisdiction_code` is required.
        - Legacy free-text `asset_type` input is no longer accepted.
        - Valuation recording is managed via finance tools (record_valuation_observation).

        Args:
            name: Asset name.
            asset_class_code: Normalized asset class code.
            asset_subclass_code: Normalized asset subclass code.
            jurisdiction_code: Jurisdiction code.
            owner_entity_id: Owning entity ID (provide this OR owner_person_id).
            owner_person_id: Owning person ID (provide this OR owner_entity_id).
            acquisition_date: Date acquired (YYYY-MM-DD).
            acquisition_cost: Original cost basis.
            paperless_doc_id: Link to Paperless-ngx document.
            ghostfolio_account_id: Link to Ghostfolio account.
            address: Physical address (for real estate).
            description: Description.
            notes: Free-text notes.
            country_code: Optional ISO country code for real-estate detail row.
            state_code: Optional state/province code.
            city: Optional city.
            postal_code: Optional postal/ZIP code.
            address_line1: Optional structured address line.
            property_type: Optional property type (residential, land, commercial, ag).
            land_area: Optional land area numeric value.
            land_area_unit: Unit for land area.
            building_area: Optional building area numeric value.
            building_area_unit: Unit for building area.
            bedrooms: Optional bedroom count.
            bathrooms: Optional bathroom count.
            year_built: Optional construction year.
            parcel_id: Optional parcel identifier.
            metadata: Optional JSON metadata payload for real-estate extension.
            asset_id: If provided, updates existing asset.
        """
        pool = await get_pool()
        normalized_class = (asset_class_code or "").strip().lower()
        normalized_subclass = (asset_subclass_code or "").strip().lower()
        normalized_jurisdiction = (jurisdiction_code or "").strip().upper()
        if not normalized_class:
            return _error_response("asset_class_code is required")
        if not normalized_subclass:
            return _error_response("asset_subclass_code is required")
        if not normalized_jurisdiction:
            return _error_response("jurisdiction_code is required")

        class_row = await pool.fetchrow(
            "SELECT id, code FROM finance.asset_classes WHERE code = $1",
            normalized_class,
        )
        if not class_row:
            class_codes = await pool.fetch("SELECT code FROM finance.asset_classes ORDER BY code")
            return _error_response(
                f"Unknown asset_class_code: {normalized_class}",
                payload={"valid_asset_class_codes": [str(row["code"]) for row in class_codes]},
            )

        subclass_row = await pool.fetchrow(
            "SELECT id, asset_class_id, code FROM finance.asset_subclasses WHERE code = $1",
            normalized_subclass,
        )
        if not subclass_row:
            subclass_codes = await pool.fetch(
                """SELECT code
                   FROM finance.asset_subclasses
                   WHERE asset_class_id = $1
                   ORDER BY code""",
                int(class_row["id"]),
            )
            return _error_response(
                f"Unknown asset_subclass_code: {normalized_subclass}",
                payload={
                    "valid_asset_subclass_codes_for_class": [str(row["code"]) for row in subclass_codes]
                },
            )
        if int(subclass_row["asset_class_id"]) != int(class_row["id"]):
            return _error_response(
                "asset_subclass_code does not belong to asset_class_code",
                payload={
                    "asset_class_code": normalized_class,
                    "asset_subclass_code": normalized_subclass,
                },
            )

        jid = await pool.fetchval(
            "SELECT id FROM jurisdictions WHERE code = $1",
            normalized_jurisdiction,
        )
        if not jid:
            return _error_response(f"Unknown jurisdiction_code: {normalized_jurisdiction}")

        existing_asset = None
        if asset_id is not None:
            existing_asset = await pool.fetchrow(
                "SELECT id, owner_entity_id, owner_person_id FROM assets WHERE id = $1",
                asset_id,
            )
            if existing_asset is None:
                return _error_response(f"Asset {asset_id} not found")

        try:
            ad = _parse_iso_date(acquisition_date, "acquisition_date")
        except ValueError as exc:
            return _error_response(str(exc))

        try:
            resolved_owner_entity_id, resolved_owner_person_id = _resolve_exact_one_owner(
                owner_entity_id=owner_entity_id,
                owner_person_id=owner_person_id,
                existing_owner_entity_id=(
                    int(existing_asset["owner_entity_id"]) if existing_asset and existing_asset["owner_entity_id"] is not None else None
                ),
                existing_owner_person_id=(
                    int(existing_asset["owner_person_id"]) if existing_asset and existing_asset["owner_person_id"] is not None else None
                ),
                is_create=asset_id is None,
            )
        except ValueError as exc:
            return _error_response(str(exc))

        derived_asset_type = _canonical_asset_type(normalized_class, normalized_subclass)

        metadata_payload = _coerce_json_input(metadata)
        resolved_country = (country_code or "").strip().upper()
        if not resolved_country and normalized_jurisdiction:
            resolved_country = normalized_jurisdiction.split("-")[0].strip().upper()

        normalized_property_type = (property_type or "").strip().lower() or None
        if not normalized_property_type:
            if normalized_subclass == "real_estate_residential":
                normalized_property_type = "residential"
            elif normalized_subclass == "real_estate_land":
                normalized_property_type = "land"

        should_upsert_real_estate = (
            derived_asset_type == "real_estate"
            or any(
                v is not None
                for v in [
                    state_code,
                    city,
                    postal_code,
                    address_line1,
                    property_type,
                    land_area,
                    building_area,
                    bedrooms,
                    bathrooms,
                    year_built,
                    parcel_id,
                ]
            )
        )
        if should_upsert_real_estate and not resolved_country:
            return _error_response(
                "country_code could not be derived for real-estate asset",
                payload={
                    "hint": (
                        "Provide country_code explicitly or use a jurisdiction_code "
                        "with country prefix (e.g. US-CA)."
                    )
                },
            )

        async with pool.acquire() as conn:
            async with conn.transaction():
                if asset_id:
                    row = await conn.fetchrow(
                        """UPDATE assets SET name=$1, asset_type=$2,
                           owner_entity_id=$3,
                           owner_person_id=$4,
                           jurisdiction_id=$5, acquisition_date=$6,
                           acquisition_cost=$7, paperless_doc_id=$8, ghostfolio_account_id=$9,
                           address=$10, description=$11, notes=$12, updated_at=now()
                           WHERE id=$13 RETURNING id, name""",
                        name,
                        derived_asset_type,
                        resolved_owner_entity_id,
                        resolved_owner_person_id,
                        jid,
                        ad,
                        acquisition_cost,
                        paperless_doc_id,
                        ghostfolio_account_id,
                        address,
                        description,
                        notes,
                        asset_id,
                    )
                else:
                    row = await conn.fetchrow(
                        """INSERT INTO assets (name, asset_type, owner_entity_id, owner_person_id,
                           jurisdiction_id, acquisition_date, acquisition_cost,
                           paperless_doc_id, ghostfolio_account_id,
                           address, description, notes)
                           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                           RETURNING id, name""",
                        name,
                        derived_asset_type,
                        resolved_owner_entity_id,
                        resolved_owner_person_id,
                        jid,
                        ad,
                        acquisition_cost,
                        paperless_doc_id,
                        ghostfolio_account_id,
                        address,
                        description,
                        notes,
                    )
                assert row is not None
                resolved_asset_id = int(row["id"])

                await conn.execute(
                    """INSERT INTO finance.asset_taxonomy (
                           asset_id, asset_class_id, asset_subclass_id, country_code, region_code
                       ) VALUES ($1, $2, $3, $4, $5)
                       ON CONFLICT (asset_id) DO UPDATE SET
                           asset_class_id = EXCLUDED.asset_class_id,
                           asset_subclass_id = EXCLUDED.asset_subclass_id,
                           country_code = EXCLUDED.country_code,
                           region_code = EXCLUDED.region_code,
                           updated_at = now()""",
                    resolved_asset_id,
                    int(class_row["id"]),
                    int(subclass_row["id"]),
                    (country_code or "").strip().upper() or None,
                    (state_code or "").strip().upper() or None,
                )

                if should_upsert_real_estate and resolved_country:
                    await conn.execute(
                        """INSERT INTO finance.real_estate_assets (
                               asset_id, country_code, state_code, city, postal_code, address_line1,
                               property_type, land_area, land_area_unit, building_area, building_area_unit,
                               bedrooms, bathrooms, year_built, parcel_id, metadata
                           ) VALUES (
                               $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16
                           )
                           ON CONFLICT (asset_id) DO UPDATE SET
                               country_code = EXCLUDED.country_code,
                               state_code = EXCLUDED.state_code,
                               city = EXCLUDED.city,
                               postal_code = EXCLUDED.postal_code,
                               address_line1 = EXCLUDED.address_line1,
                               property_type = EXCLUDED.property_type,
                               land_area = EXCLUDED.land_area,
                               land_area_unit = EXCLUDED.land_area_unit,
                               building_area = EXCLUDED.building_area,
                               building_area_unit = EXCLUDED.building_area_unit,
                               bedrooms = EXCLUDED.bedrooms,
                               bathrooms = EXCLUDED.bathrooms,
                               year_built = EXCLUDED.year_built,
                               parcel_id = EXCLUDED.parcel_id,
                               metadata = EXCLUDED.metadata,
                               updated_at = now()""",
                        resolved_asset_id,
                        resolved_country,
                        state_code,
                        city,
                        postal_code,
                        address_line1 or address,
                        normalized_property_type,
                        land_area,
                        land_area_unit,
                        building_area,
                        building_area_unit,
                        bedrooms,
                        bathrooms,
                        year_built,
                        parcel_id,
                        json.dumps(metadata_payload),
                    )

        payload = _row_to_dict(row)
        payload["asset_id"] = resolved_asset_id
        payload["taxonomy_updated"] = True
        payload["asset_class_code"] = normalized_class
        payload["asset_subclass_code"] = normalized_subclass
        payload["jurisdiction_code"] = normalized_jurisdiction
        payload["asset_type"] = derived_asset_type
        payload["real_estate_details_updated"] = bool(should_upsert_real_estate and resolved_country)
        return payload
