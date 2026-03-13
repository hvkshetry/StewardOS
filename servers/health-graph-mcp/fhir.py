from __future__ import annotations

from datetime import datetime

from stewardos_lib.response_ops import error_response as _error_response, make_enveloped_tool as _make_enveloped_tool

from helpers import (
    _contains_placeholder,
    _finish_run,
    _first_nonempty,
    _read_json_input,
    _start_run,
    _to_json,
    _validate_source_name,
)


def _subject_reference_to_id(ref: str) -> int | None:
    if not ref:
        return None
    if ref.startswith("Patient/"):
        raw = ref.split("/", 1)[1]
        if raw.isdigit():
            return int(raw)
    return None


def register_fhir_tools(mcp, get_pool, ensure_initialized):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def ingest_fhir_bundle(
        source_name: str,
        bundle_json: str | dict,
        default_subject_id: int = 0,
    ) -> dict:
        """Ingest targeted FHIR resources (Observation, DiagnosticReport, Coverage, Claim family)."""
        await ensure_initialized()

        try:
            _validate_source_name(source_name)
        except ValueError as exc:
            return _error_response(str(exc), code="validation_error")

        payload = _read_json_input(bundle_json)
        if not isinstance(payload, dict):
            return _error_response("FHIR payload must be object", code="validation_error")
        if _contains_placeholder(payload):
            return _error_response(
                "FHIR payload appears to contain placeholder/test content",
                code="validation_error",
            )

        entries = payload.get("entry", [])
        if not isinstance(entries, list):
            return _error_response("FHIR bundle entry must be list", code="validation_error")

        pool = await get_pool()
        rows_written = 0
        skipped_placeholder = 0
        skipped_missing_subject = 0

        async with pool.acquire() as conn:
            run_id = await _start_run(conn, source_name=source_name, run_type="fhir_ingest")
            try:
                report_map: dict[str, int] = {}
                coverage_map: dict[str, int] = {}
                claim_map: dict[str, int] = {}
                claim_response_map: dict[str, int] = {}

                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    resource = entry.get("resource")
                    if not isinstance(resource, dict):
                        continue
                    if _contains_placeholder(resource):
                        skipped_placeholder += 1
                        continue

                    rtype = resource.get("resourceType")
                    if not isinstance(rtype, str):
                        continue

                    subject_id = default_subject_id if default_subject_id > 0 else None
                    subject_ref = (
                        resource.get("subject", {}).get("reference")
                        if isinstance(resource.get("subject"), dict)
                        else None
                    )
                    parsed_subject = _subject_reference_to_id(subject_ref or "")
                    if parsed_subject is not None:
                        subject_id = parsed_subject

                    requires_subject = rtype in {
                        "DiagnosticReport",
                        "Observation",
                        "Coverage",
                        "CoverageEligibilityRequest",
                        "CoverageEligibilityResponse",
                        "Claim",
                        "ClaimResponse",
                        "ExplanationOfBenefit",
                    }
                    if requires_subject and not subject_id:
                        skipped_missing_subject += 1
                        continue

                    if rtype == "DiagnosticReport":
                        row = await conn.fetchrow(
                            """INSERT INTO diagnostic_reports (
                                   subject_id, report_id, status, code, effective_at, issued_at, source_name, payload
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)
                               RETURNING id""",
                            subject_id,
                            resource.get("id"),
                            resource.get("status"),
                            _first_nonempty(resource.get("code", {}).get("coding", [{}])[0].get("code"))
                            if isinstance(resource.get("code"), dict)
                            else None,
                            datetime.fromisoformat(resource["effectiveDateTime"].replace("Z", "+00:00")) if resource.get("effectiveDateTime") else None,
                            datetime.fromisoformat(resource["issued"].replace("Z", "+00:00")) if resource.get("issued") else None,
                            source_name,
                            _to_json(resource),
                        )
                        assert row is not None
                        if resource.get("id"):
                            report_map[str(resource["id"])] = int(row["id"])
                        rows_written += 1

                    elif rtype == "Observation":
                        report_id_fk = None
                        if isinstance(resource.get("partOf"), list) and resource["partOf"]:
                            part = resource["partOf"][0]
                            if isinstance(part, dict):
                                ref = part.get("reference")
                                if isinstance(ref, str) and ref.startswith("DiagnosticReport/"):
                                    rid = ref.split("/", 1)[1]
                                    report_id_fk = report_map.get(rid)

                        value_numeric = None
                        value_text = None
                        unit = None
                        if isinstance(resource.get("valueQuantity"), dict):
                            value_numeric = resource["valueQuantity"].get("value")
                            unit = resource["valueQuantity"].get("unit")
                        if resource.get("valueString"):
                            value_text = str(resource["valueString"])

                        await conn.execute(
                            """INSERT INTO observations (
                                   subject_id, diagnostic_report_id, observation_id, status, category, code,
                                   display_name, value_numeric, value_text, unit, effective_at, source_name, payload
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13::jsonb)""",
                            subject_id,
                            report_id_fk,
                            resource.get("id"),
                            resource.get("status"),
                            _first_nonempty(resource.get("category", [{}])[0].get("coding", [{}])[0].get("code"))
                            if isinstance(resource.get("category"), list) and resource["category"]
                            else None,
                            _first_nonempty(resource.get("code", {}).get("coding", [{}])[0].get("code"))
                            if isinstance(resource.get("code"), dict)
                            else None,
                            _first_nonempty(resource.get("code", {}).get("text"))
                            if isinstance(resource.get("code"), dict)
                            else None,
                            float(value_numeric) if value_numeric is not None else None,
                            value_text,
                            unit,
                            datetime.fromisoformat(resource["effectiveDateTime"].replace("Z", "+00:00")) if resource.get("effectiveDateTime") else None,
                            source_name,
                            _to_json(resource),
                        )
                        rows_written += 1

                    elif rtype == "Coverage":
                        row = await conn.fetchrow(
                            """INSERT INTO coverages (
                                   subject_id, coverage_id, status, payer_name, plan_name, member_id, group_id,
                                   start_date, end_date, source_name, payload
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb)
                               RETURNING id""",
                            subject_id,
                            resource.get("id"),
                            resource.get("status"),
                            _first_nonempty(resource.get("payor", [{}])[0].get("display"))
                            if isinstance(resource.get("payor"), list) and resource["payor"]
                            else None,
                            _first_nonempty(resource.get("type", {}).get("text")) if isinstance(resource.get("type"), dict) else None,
                            _first_nonempty(resource.get("subscriberId")),
                            _first_nonempty(resource.get("class", [{}])[0].get("value"))
                            if isinstance(resource.get("class"), list) and resource["class"]
                            else None,
                            datetime.strptime(resource.get("period", {}).get("start"), "%Y-%m-%d").date()
                            if isinstance(resource.get("period"), dict) and resource.get("period", {}).get("start")
                            else None,
                            datetime.strptime(resource.get("period", {}).get("end"), "%Y-%m-%d").date()
                            if isinstance(resource.get("period"), dict) and resource.get("period", {}).get("end")
                            else None,
                            source_name,
                            _to_json(resource),
                        )
                        assert row is not None
                        if resource.get("id"):
                            coverage_map[str(resource["id"])] = int(row["id"])
                        rows_written += 1

                    elif rtype == "InsurancePlan":
                        await conn.execute(
                            """INSERT INTO insurance_plans (
                                   plan_id, payer_name, plan_name, plan_type, source_name, payload
                               ) VALUES ($1,$2,$3,$4,$5,$6::jsonb)""",
                            resource.get("id"),
                            _first_nonempty(resource.get("ownedBy", {}).get("display"))
                            if isinstance(resource.get("ownedBy"), dict)
                            else None,
                            _first_nonempty(resource.get("name")),
                            _first_nonempty(resource.get("type", [{}])[0].get("text"))
                            if isinstance(resource.get("type"), list) and resource["type"]
                            else None,
                            source_name,
                            _to_json(resource),
                        )
                        rows_written += 1

                    elif rtype == "CoverageEligibilityRequest":
                        coverage_fk = None
                        if isinstance(resource.get("insurance"), list) and resource["insurance"]:
                            coverage_ref = _first_nonempty(resource["insurance"][0].get("coverage", {}).get("reference"))
                            if coverage_ref and coverage_ref.startswith("Coverage/"):
                                coverage_fk = coverage_map.get(coverage_ref.split("/", 1)[1])
                        await conn.execute(
                            """INSERT INTO coverage_eligibility_requests (
                                   subject_id, coverage_id, request_id, purpose, service_code, source_name, payload
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)""",
                            subject_id,
                            coverage_fk,
                            resource.get("id"),
                            _first_nonempty(resource.get("purpose", [None])[0]) if isinstance(resource.get("purpose"), list) else None,
                            _first_nonempty(resource.get("item", [{}])[0].get("productOrService", {}).get("coding", [{}])[0].get("code"))
                            if isinstance(resource.get("item"), list) and resource["item"]
                            else None,
                            source_name,
                            _to_json(resource),
                        )
                        rows_written += 1

                    elif rtype == "CoverageEligibilityResponse":
                        coverage_fk = None
                        if isinstance(resource.get("insurance"), list) and resource["insurance"]:
                            coverage_ref = _first_nonempty(resource["insurance"][0].get("coverage", {}).get("reference"))
                            if coverage_ref and coverage_ref.startswith("Coverage/"):
                                coverage_fk = coverage_map.get(coverage_ref.split("/", 1)[1])
                        await conn.execute(
                            """INSERT INTO coverage_eligibility_responses (
                                   subject_id, coverage_id, response_id, outcome, inforce, source_name, payload
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)""",
                            subject_id,
                            coverage_fk,
                            resource.get("id"),
                            _first_nonempty(resource.get("outcome")),
                            bool(resource.get("insurance", [{}])[0].get("inforce"))
                            if isinstance(resource.get("insurance"), list) and resource["insurance"]
                            else None,
                            source_name,
                            _to_json(resource),
                        )
                        rows_written += 1

                    elif rtype == "Claim":
                        coverage_fk = None
                        if isinstance(resource.get("insurance"), list) and resource["insurance"]:
                            coverage_ref = _first_nonempty(resource["insurance"][0].get("coverage", {}).get("reference"))
                            if coverage_ref and coverage_ref.startswith("Coverage/"):
                                coverage_fk = coverage_map.get(coverage_ref.split("/", 1)[1])
                        row = await conn.fetchrow(
                            """INSERT INTO claims (
                                   subject_id, coverage_id, claim_id, status, use_type, priority,
                                   service_code, source_name, payload
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                               RETURNING id""",
                            subject_id,
                            coverage_fk,
                            resource.get("id"),
                            _first_nonempty(resource.get("status")),
                            _first_nonempty(resource.get("use")),
                            _first_nonempty(resource.get("priority", {}).get("coding", [{}])[0].get("code"))
                            if isinstance(resource.get("priority"), dict)
                            else None,
                            _first_nonempty(resource.get("item", [{}])[0].get("productOrService", {}).get("coding", [{}])[0].get("code"))
                            if isinstance(resource.get("item"), list) and resource["item"]
                            else None,
                            source_name,
                            _to_json(resource),
                        )
                        assert row is not None
                        if resource.get("id"):
                            claim_map[str(resource["id"])] = int(row["id"])
                        rows_written += 1

                    elif rtype == "ClaimResponse":
                        claim_fk = None
                        claim_ref = _first_nonempty(resource.get("claim", {}).get("reference")) if isinstance(resource.get("claim"), dict) else None
                        if claim_ref and claim_ref.startswith("Claim/"):
                            claim_fk = claim_map.get(claim_ref.split("/", 1)[1])

                        row = await conn.fetchrow(
                            """INSERT INTO claim_responses (
                                   subject_id, claim_id, response_id, outcome, disposition, source_name, payload
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
                               RETURNING id""",
                            subject_id,
                            claim_fk,
                            resource.get("id"),
                            _first_nonempty(resource.get("outcome")),
                            _first_nonempty(resource.get("disposition")),
                            source_name,
                            _to_json(resource),
                        )
                        assert row is not None
                        if resource.get("id"):
                            claim_response_map[str(resource["id"])] = int(row["id"])
                        rows_written += 1

                    elif rtype == "ExplanationOfBenefit":
                        claim_fk = None
                        claim_resp_fk = None
                        claim_ref = _first_nonempty(resource.get("claim", {}).get("reference")) if isinstance(resource.get("claim"), dict) else None
                        if claim_ref and claim_ref.startswith("Claim/"):
                            claim_fk = claim_map.get(claim_ref.split("/", 1)[1])

                        claim_resp_ref = (
                            _first_nonempty(resource.get("claimResponse", {}).get("reference"))
                            if isinstance(resource.get("claimResponse"), dict)
                            else None
                        )
                        if claim_resp_ref and claim_resp_ref.startswith("ClaimResponse/"):
                            claim_resp_fk = claim_response_map.get(claim_resp_ref.split("/", 1)[1])

                        await conn.execute(
                            """INSERT INTO explanations_of_benefit (
                                   subject_id, claim_id, claim_response_id, eob_id, status,
                                   outcome, source_name, payload
                               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)""",
                            subject_id,
                            claim_fk,
                            claim_resp_fk,
                            resource.get("id"),
                            _first_nonempty(resource.get("status")),
                            _first_nonempty(resource.get("outcome")),
                            source_name,
                            _to_json(resource),
                        )
                        rows_written += 1

                await _finish_run(conn, run_id, "success", len(entries), rows_written)
                return {
                    "ingestion_run_id": run_id,
                    "entries_read": len(entries),
                    "rows_written": rows_written,
                    "skipped_placeholder": skipped_placeholder,
                    "skipped_missing_subject": skipped_missing_subject,
                }
            except Exception as exc:  # noqa: BLE001
                await _finish_run(conn, run_id, "error", len(entries), rows_written, str(exc))
                return _error_response(
                    str(exc),
                    code="ingestion_error",
                    payload={
                        "ingestion_run_id": run_id,
                        "rows_written": rows_written,
                        "skipped_placeholder": skipped_placeholder,
                        "skipped_missing_subject": skipped_missing_subject,
                    },
                )
