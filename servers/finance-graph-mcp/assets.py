import json
import os
from datetime import date

import httpx
from dotenv import load_dotenv

from stewardos_lib.constants import canonical_asset_type as _canonical_asset_type
from stewardos_lib.db import float_or_none as _float_or_none, row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import (
    insert_valuation_observation as _insert_valuation_observation,
    normalize_currency_code as _normalize_currency_code,
    parse_iso_date as _parse_iso_date,
    resolve_exact_one_owner as _resolve_exact_one_owner,
)
from stewardos_lib.json_utils import coerce_json_input as _coerce_json_input, extract_numeric_value as _extract_numeric_value
from stewardos_lib.response_ops import error_response as _error_response, make_enveloped_tool as _make_enveloped_tool
from valuation_services import promote_current_valuation_observation as _promote_current_valuation_observation

load_dotenv()

RENTCAST_API_KEY = os.environ.get("RENTCAST_API_KEY", "").strip()
RENTCAST_BASE_URL = os.environ.get("RENTCAST_BASE_URL", "https://api.rentcast.io/v1").rstrip("/")


def register_assets_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def list_assets(
        asset_class_code: str | None = None,
        asset_subclass_code: str | None = None,
        jurisdiction: str | None = None,
        owner_entity_id: int | None = None,
        owner_person_id: int | None = None,
    ) -> list[dict]:
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
            SELECT a.id, a.name, a.asset_type, a.current_valuation_observation_id,
                   cvo.value_amount AS current_valuation_amount,
                   cvo.value_currency AS valuation_currency,
                   cvo.valuation_date AS valuation_date,
                   j.code AS jurisdiction,
                   COALESCE(e.name, p.legal_name) AS owner_name,
                   ac.code AS asset_class_code,
                   ascb.code AS asset_subclass_code,
                   at.country_code,
                   at.region_code,
                   rea.property_type
            FROM assets a
            LEFT JOIN valuation_observations cvo ON cvo.id = a.current_valuation_observation_id
            LEFT JOIN jurisdictions j ON a.jurisdiction_id = j.id
            LEFT JOIN entities e ON a.owner_entity_id = e.id
            LEFT JOIN people p ON a.owner_person_id = p.id
            LEFT JOIN asset_taxonomy at ON at.asset_id = a.id
            LEFT JOIN asset_classes ac ON at.asset_class_id = ac.id
            LEFT JOIN asset_subclasses ascb ON at.asset_subclass_id = ascb.id
            LEFT JOIN real_estate_assets rea ON rea.asset_id = a.id
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
        valuation_currency: str | None = None,
        owner_entity_id: int | None = None,
        owner_person_id: int | None = None,
        current_valuation_amount: float | None = None,
        valuation_date: str | None = None,
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
    ) -> dict:
        """Create or update an asset using normalized class/subclass taxonomy.

        This is a breaking interface by design:
        - `asset_class_code` and `asset_subclass_code` are required.
        - `jurisdiction_code` is required.
        - Legacy free-text `asset_type` input is no longer accepted.
        - When `current_valuation_amount` is provided, the tool records a
          `manual_mark` valuation observation and force-promotes the canonical
          current valuation pointer. `valuation_currency` is only used for that
          observation and is not stored on the asset row.

        Args:
            name: Asset name.
            asset_class_code: Normalized asset class code.
            asset_subclass_code: Normalized asset subclass code.
            jurisdiction_code: Jurisdiction code.
            valuation_currency: ISO-4217 currency code for the optional current valuation mark.
            owner_entity_id: Owning entity ID (provide this OR owner_person_id).
            owner_person_id: Owning person ID (provide this OR owner_entity_id).
            current_valuation_amount: Current market value.
            valuation_date: Date of valuation (YYYY-MM-DD).
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
        normalized_currency = _normalize_currency_code(valuation_currency) if valuation_currency else None

        if not normalized_class:
            return _error_response("asset_class_code is required", code="validation_error")
        if not normalized_subclass:
            return _error_response("asset_subclass_code is required", code="validation_error")
        if not normalized_jurisdiction:
            return _error_response("jurisdiction_code is required", code="validation_error")
        if valuation_currency and not normalized_currency:
            return _error_response(
                "valuation_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)",
                code="validation_error",
            )

        class_row = await pool.fetchrow(
            "SELECT id, code FROM asset_classes WHERE code = $1",
            normalized_class,
        )
        if not class_row:
            class_codes = await pool.fetch("SELECT code FROM asset_classes ORDER BY code")
            return _error_response(
                f"Unknown asset_class_code: {normalized_class}",
                code="validation_error",
                payload={"valid_asset_class_codes": [str(row["code"]) for row in class_codes]},
            )

        subclass_row = await pool.fetchrow(
            "SELECT id, asset_class_id, code FROM asset_subclasses WHERE code = $1",
            normalized_subclass,
        )
        if not subclass_row:
            subclass_codes = await pool.fetch(
                """SELECT code
                   FROM asset_subclasses
                   WHERE asset_class_id = $1
                   ORDER BY code""",
                int(class_row["id"]),
            )
            return _error_response(
                f"Unknown asset_subclass_code: {normalized_subclass}",
                code="validation_error",
                payload={"valid_asset_subclass_codes_for_class": [str(row["code"]) for row in subclass_codes]},
            )
        if int(subclass_row["asset_class_id"]) != int(class_row["id"]):
            return _error_response(
                "asset_subclass_code does not belong to asset_class_code",
                code="validation_error",
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
            return _error_response(f"Unknown jurisdiction_code: {normalized_jurisdiction}", code="validation_error")

        existing_asset = None
        if asset_id is not None:
            existing_asset = await pool.fetchrow(
                "SELECT id, owner_entity_id, owner_person_id FROM assets WHERE id = $1",
                asset_id,
            )
            if existing_asset is None:
                return _error_response(f"Asset {asset_id} not found", code="not_found")

        try:
            vd = _parse_iso_date(valuation_date, "valuation_date")
            ad = _parse_iso_date(acquisition_date, "acquisition_date")
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")
        if vd is not None and current_valuation_amount is None:
            return _error_response(
                "valuation_date requires current_valuation_amount",
                code="validation_error",
            )
        if current_valuation_amount is not None and not normalized_currency:
            return _error_response(
                "valuation_currency is required when current_valuation_amount is provided",
                code="validation_error",
            )

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
            return _error_response(str(exc), code="validation_error")

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
                code="validation_error",
                payload={
                    "hint": "Provide country_code explicitly or use a jurisdiction_code with country prefix (e.g. US-CA).",
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
                           jurisdiction_id, acquisition_date, acquisition_cost, paperless_doc_id, ghostfolio_account_id,
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
                    """INSERT INTO asset_taxonomy (
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
                        """INSERT INTO real_estate_assets (
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

                promotion_payload = {
                    "promoted_to_current": False,
                    "current_valuation_observation_id": None,
                }
                if current_valuation_amount is not None:
                    observation = await _insert_valuation_observation(
                        pool=conn,
                        asset_id=resolved_asset_id,
                        method_code="manual_mark",
                        source="asset_upsert",
                        value_amount=current_valuation_amount,
                        value_currency=normalized_currency,
                        valuation_date=vd or date.today(),
                        confidence_score=None,
                        notes="Direct asset upsert valuation",
                        evidence={"origin": "upsert_asset"},
                    )
                    promotion_payload = await _promote_current_valuation_observation(
                        conn,
                        asset_id=resolved_asset_id,
                        observation_row=observation,
                        promote_to_current="force",
                    )
                elif asset_id:
                    existing_current = await conn.fetchval(
                        "SELECT current_valuation_observation_id FROM assets WHERE id = $1",
                        resolved_asset_id,
                    )
                    promotion_payload["current_valuation_observation_id"] = (
                        int(existing_current) if existing_current is not None else None
                    )

                asset_view = await conn.fetchrow(
                    """SELECT a.id, a.name, a.asset_type, a.current_valuation_observation_id,
                              cvo.value_amount AS current_valuation_amount,
                              cvo.value_currency AS valuation_currency,
                              cvo.valuation_date AS valuation_date
                       FROM assets a
                       LEFT JOIN valuation_observations cvo ON cvo.id = a.current_valuation_observation_id
                       WHERE a.id = $1""",
                    resolved_asset_id,
                )

        payload = _row_to_dict(row)
        payload["asset_id"] = resolved_asset_id
        payload["taxonomy_updated"] = True
        payload["asset_class_code"] = normalized_class
        payload["asset_subclass_code"] = normalized_subclass
        payload["jurisdiction_code"] = normalized_jurisdiction
        payload["asset_type"] = derived_asset_type
        payload["real_estate_details_updated"] = bool(should_upsert_real_estate and resolved_country)
        payload["current_valuation_observation_id"] = asset_view["current_valuation_observation_id"]
        payload["current_valuation_amount"] = _float_or_none(asset_view["current_valuation_amount"])
        payload["valuation_currency"] = asset_view["valuation_currency"]
        payload["valuation_date"] = (
            asset_view["valuation_date"].isoformat() if asset_view["valuation_date"] is not None else None
        )
        payload.update(promotion_payload)
        return payload

    @_tool
    async def refresh_us_property_valuation(
        asset_id: int,
        valuation_date: str | None = None,
        value_currency: str = "USD",
    ) -> dict:
        """Fetch a US property valuation from RentCast and persist it as a valuation observation."""
        if not RENTCAST_API_KEY:
            return _error_response(
                "RENTCAST_API_KEY is not configured",
                code="configuration_error",
                payload={"hint": "Set RENTCAST_API_KEY in finance-graph-mcp environment."},
            )

        normalized_currency = _normalize_currency_code(value_currency)
        if not normalized_currency:
            return _error_response(
                "value_currency must be a valid ISO-4217 3-letter code (e.g. USD, INR)",
                code="validation_error",
            )

        pool = await get_pool()
        row = await pool.fetchrow(
            """SELECT a.id, a.name, a.address,
                      r.country_code, r.state_code, r.city, r.postal_code, r.address_line1
               FROM assets a
               LEFT JOIN real_estate_assets r ON r.asset_id = a.id
               WHERE a.id = $1""",
            asset_id,
        )
        if not row:
            return _error_response(f"Asset {asset_id} not found", code="not_found")
        row_dict = dict(row)

        country_code_val = (row_dict.get("country_code") or "").upper() if isinstance(row_dict.get("country_code"), str) else ""
        if country_code_val and country_code_val != "US":
            return _error_response(
                "Only US automated valuation is supported",
                code="validation_error",
                payload={"asset_id": asset_id, "country_code": country_code_val},
            )

        structured_address = ", ".join(
            part for part in [
                row_dict.get("address_line1"),
                row_dict.get("city"),
                row_dict.get("state_code"),
                row_dict.get("postal_code"),
            ] if isinstance(part, str) and part.strip()
        )
        address_query = structured_address or row_dict.get("address")
        if not address_query:
            return _error_response(
                "No address available for asset",
                code="validation_error",
                payload={"asset_id": asset_id},
            )

        headers = {"Accept": "application/json", "X-Api-Key": RENTCAST_API_KEY}
        endpoints = [
            ("/avm/value", {"address": address_query}),
            ("/avm", {"address": address_query}),
            ("/properties", {"address": address_query, "limit": 1}),
        ]

        last_error: str | None = None
        for endpoint, params in endpoints:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    response = await client.get(f"{RENTCAST_BASE_URL}{endpoint}", params=params, headers=headers)
                response.raise_for_status()
                resp_payload = response.json()
                candidate_payload = resp_payload[0] if isinstance(resp_payload, list) and resp_payload else resp_payload
                if not isinstance(candidate_payload, dict):
                    last_error = f"{endpoint}: unsupported payload type"
                    continue
                extracted_value = _extract_numeric_value(candidate_payload)
                if extracted_value is None:
                    last_error = f"{endpoint}: no numeric valuation field found"
                    continue

                vd = date.fromisoformat(valuation_date) if valuation_date else date.today()
                try:
                    async with pool.acquire() as conn:
                        async with conn.transaction():
                            observation = await _insert_valuation_observation(
                                pool=conn,
                                asset_id=asset_id,
                                method_code="rentcast_avm",
                                source="rentcast",
                                value_amount=extracted_value,
                                value_currency=normalized_currency,
                                valuation_date=vd,
                                confidence_score=None,
                                notes="Automated valuation refresh",
                                evidence={
                                    "provider": "rentcast",
                                    "endpoint": endpoint,
                                    "params": params,
                                    "payload": candidate_payload,
                                },
                            )
                            promotion_payload = await _promote_current_valuation_observation(
                                conn,
                                asset_id=asset_id,
                                observation_row=observation,
                                promote_to_current="auto",
                            )
                except ValueError as exc:
                    return _error_response(str(exc), code="validation_error", payload={"asset_id": asset_id})
                return {
                    "asset_id": asset_id,
                    "valuation_observation_id": observation["id"],
                    "value_amount": extracted_value,
                    "value_currency": normalized_currency,
                    "provider": "rentcast",
                    "endpoint": endpoint,
                    **promotion_payload,
                }
            except Exception as exc:
                last_error = f"{endpoint}: {exc}"

        return _error_response(
            "RentCast valuation lookup failed",
            code="external_lookup_failed",
            payload={
                "asset_id": asset_id,
                "address_query": address_query,
                "last_error": last_error,
            },
        )
