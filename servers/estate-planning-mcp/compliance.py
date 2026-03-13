import json
from datetime import date, datetime

from stewardos_lib.db import row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import parse_iso_date as _parse_iso_date
from stewardos_lib.json_utils import coerce_json_input as _coerce_json_input
from stewardos_lib.response_ops import (
    error_response as _error_response,
    make_enveloped_tool as _make_enveloped_tool,
)


def _exactly_one(values: list[object]) -> bool:
    return sum(v is not None for v in values) == 1


def register_compliance_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def upsert_compliance_obligation(
        title: str,
        obligation_type: str,
        recurrence: str = "annual",
        jurisdiction_code: str | None = None,
        entity_type_code: str | None = None,
        due_rule: str | None = None,
        grace_days: int = 0,
        penalty_notes: str | None = None,
        default_owner_person_id: int | None = None,
        active: bool = True,
        obligation_id: int | None = None,
    ):
        """Create or update a compliance obligation definition."""
        pool = await get_pool()
        jid = None
        if jurisdiction_code:
            jid = await pool.fetchval("SELECT id FROM jurisdictions WHERE code = $1", jurisdiction_code)
            if not jid:
                return _error_response(f"Unknown jurisdiction_code: {jurisdiction_code}")

        entity_type_id = None
        if entity_type_code:
            entity_type_id = await pool.fetchval("SELECT id FROM entity_types WHERE code = $1", entity_type_code)
            if not entity_type_id:
                return _error_response(f"Unknown entity_type_code: {entity_type_code}")

        if obligation_id:
            row = await pool.fetchrow(
                """UPDATE compliance_obligations
                   SET title=$1,
                       obligation_type=$2,
                       jurisdiction_id=$3,
                       entity_type_id=$4,
                       recurrence=$5,
                       due_rule=$6,
                       grace_days=$7,
                       penalty_notes=$8,
                       default_owner_person_id=$9,
                       active=$10,
                       updated_at=now()
                   WHERE id=$11
                   RETURNING *""",
                title,
                obligation_type.strip().lower(),
                jid,
                entity_type_id,
                recurrence.strip().lower(),
                due_rule,
                grace_days,
                penalty_notes,
                default_owner_person_id,
                active,
                obligation_id,
            )
        else:
            row = await pool.fetchrow(
                """INSERT INTO compliance_obligations (
                       title, obligation_type, jurisdiction_id, entity_type_id,
                       recurrence, due_rule, grace_days, penalty_notes, default_owner_person_id, active
                   ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                   RETURNING *""",
                title,
                obligation_type.strip().lower(),
                jid,
                entity_type_id,
                recurrence.strip().lower(),
                due_rule,
                grace_days,
                penalty_notes,
                default_owner_person_id,
                active,
            )
        return _row_to_dict(row)

    @_tool
    async def update_compliance_instance_status(
        compliance_instance_id: int,
        status: str,
        assigned_to_person_id: int | None = None,
        rejection_reason: str | None = None,
        completion_notes: str | None = None,
    ):
        """Update lifecycle status for a compliance instance."""
        normalized_status = (status or "").strip().lower()
        valid_statuses = {"pending", "in_progress", "submitted", "accepted", "rejected", "waived"}
        if normalized_status not in valid_statuses:
            return _error_response(
                f"Invalid status: {status}",
                payload={"valid_statuses": sorted(valid_statuses)},
            )

        submitted_at = None
        accepted_at = None
        rejected_at = None
        if normalized_status == "submitted":
            submitted_at = datetime.utcnow()
        elif normalized_status == "accepted":
            accepted_at = datetime.utcnow()
        elif normalized_status == "rejected":
            rejected_at = datetime.utcnow()

        pool = await get_pool()
        row = await pool.fetchrow(
            """UPDATE compliance_instances
               SET status=$1,
                   assigned_to_person_id=COALESCE($2, assigned_to_person_id),
                   rejection_reason=COALESCE($3, rejection_reason),
                   completion_notes=COALESCE($4, completion_notes),
                   submitted_at=COALESCE($5, submitted_at),
                   accepted_at=COALESCE($6, accepted_at),
                   rejected_at=COALESCE($7, rejected_at),
                   updated_at=now()
               WHERE id=$8
               RETURNING *""",
            normalized_status,
            assigned_to_person_id,
            rejection_reason,
            completion_notes,
            submitted_at,
            accepted_at,
            rejected_at,
            compliance_instance_id,
        )
        if not row:
            return _error_response(f"Compliance instance {compliance_instance_id} not found")
        return _row_to_dict(row)

    @_tool
    async def link_compliance_evidence(
        compliance_instance_id: int,
        evidence_type: str,
        paperless_doc_id: int | None = None,
        evidence_ref: str | None = None,
        status: str = "submitted",
        notes: str | None = None,
    ):
        """Attach filing evidence to a compliance instance."""
        pool = await get_pool()
        row = await pool.fetchrow(
            """INSERT INTO compliance_evidence (
                   compliance_instance_id, paperless_doc_id, evidence_type, evidence_ref, status, notes
               ) VALUES ($1,$2,$3,$4,$5,$6)
               RETURNING *""",
            compliance_instance_id,
            paperless_doc_id,
            evidence_type.strip().lower(),
            evidence_ref,
            status.strip().lower(),
            notes,
        )
        return _row_to_dict(row)

    @_tool
    async def upsert_succession_plan(
        name: str,
        governing_law_jurisdiction_code: str | None = None,
        grantor_person_id: int | None = None,
        sponsor_entity_id: int | None = None,
        primary_instrument_paperless_doc_id: int | None = None,
        status: str = "active",
        effective_date: str | None = None,
        termination_date: str | None = None,
        notes: str | None = None,
        succession_plan_id: int | None = None,
    ):
        """Create or update a succession plan."""
        pool = await get_pool()
        gl_jid = None
        if governing_law_jurisdiction_code:
            gl_jid = await pool.fetchval(
                "SELECT id FROM jurisdictions WHERE code = $1",
                governing_law_jurisdiction_code,
            )
            if not gl_jid:
                return _error_response(
                    f"Unknown governing_law_jurisdiction_code: {governing_law_jurisdiction_code}"
                )

        try:
            eff = _parse_iso_date(effective_date, "effective_date")
            term = _parse_iso_date(termination_date, "termination_date")
        except ValueError as exc:
            return _error_response(str(exc))

        if succession_plan_id:
            row = await pool.fetchrow(
                """UPDATE succession_plans
                   SET name=$1,
                       governing_law_jurisdiction_id=COALESCE($2, governing_law_jurisdiction_id),
                       grantor_person_id=COALESCE($3, grantor_person_id),
                       sponsor_entity_id=COALESCE($4, sponsor_entity_id),
                       primary_instrument_paperless_doc_id=COALESCE($5, primary_instrument_paperless_doc_id),
                       status=$6,
                       effective_date=COALESCE($7, effective_date),
                       termination_date=COALESCE($8, termination_date),
                       notes=COALESCE($9, notes),
                       updated_at=now()
                   WHERE id=$10
                   RETURNING *""",
                name,
                gl_jid,
                grantor_person_id,
                sponsor_entity_id,
                primary_instrument_paperless_doc_id,
                status.strip().lower(),
                eff,
                term,
                notes,
                succession_plan_id,
            )
        else:
            row = await pool.fetchrow(
                """INSERT INTO succession_plans (
                       name, governing_law_jurisdiction_id, grantor_person_id, sponsor_entity_id,
                       primary_instrument_paperless_doc_id, status, effective_date, termination_date, notes
                   ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                   RETURNING *""",
                name,
                gl_jid,
                grantor_person_id,
                sponsor_entity_id,
                primary_instrument_paperless_doc_id,
                status.strip().lower(),
                eff,
                term,
                notes,
            )
        return _row_to_dict(row)

    @_tool
    async def set_beneficiary_designation(
        succession_plan_id: int,
        beneficiary_person_id: int | None = None,
        beneficiary_entity_id: int | None = None,
        beneficiary_class: str = "primary",
        share_percentage: float | None = None,
        per_stirpes: bool = False,
        per_capita: bool = False,
        anti_lapse: bool = False,
        condition_json: dict | str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        source_paperless_doc_id: int | None = None,
        notes: str | None = None,
        designation_id: int | None = None,
    ):
        """Create or update a beneficiary designation for a succession plan."""
        if not _exactly_one([beneficiary_person_id, beneficiary_entity_id]):
            return _error_response("Provide exactly one of beneficiary_person_id or beneficiary_entity_id")

        try:
            sd = _parse_iso_date(start_date, "start_date")
            ed = _parse_iso_date(end_date, "end_date")
        except ValueError as exc:
            return _error_response(str(exc))

        pool = await get_pool()
        if designation_id:
            row = await pool.fetchrow(
                """UPDATE beneficiary_designations
                   SET succession_plan_id=$1,
                       beneficiary_person_id=$2,
                       beneficiary_entity_id=$3,
                       beneficiary_class=$4,
                       share_percentage=$5,
                       per_stirpes=$6,
                       per_capita=$7,
                       anti_lapse=$8,
                       condition_json=$9,
                       start_date=$10,
                       end_date=$11,
                       source_paperless_doc_id=$12,
                       notes=$13,
                       updated_at=now()
                   WHERE id=$14
                   RETURNING *""",
                succession_plan_id,
                beneficiary_person_id,
                beneficiary_entity_id,
                beneficiary_class.strip().lower(),
                share_percentage,
                per_stirpes,
                per_capita,
                anti_lapse,
                json.dumps(_coerce_json_input(condition_json)),
                sd,
                ed,
                source_paperless_doc_id,
                notes,
                designation_id,
            )
        else:
            row = await pool.fetchrow(
                """INSERT INTO beneficiary_designations (
                       succession_plan_id, beneficiary_person_id, beneficiary_entity_id,
                       beneficiary_class, share_percentage, per_stirpes, per_capita, anti_lapse,
                       condition_json, start_date, end_date, source_paperless_doc_id, notes
                   ) VALUES (
                       $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13
                   )
                   RETURNING *""",
                succession_plan_id,
                beneficiary_person_id,
                beneficiary_entity_id,
                beneficiary_class.strip().lower(),
                share_percentage,
                per_stirpes,
                per_capita,
                anti_lapse,
                json.dumps(_coerce_json_input(condition_json)),
                sd,
                ed,
                source_paperless_doc_id,
                notes,
            )
        return _row_to_dict(row)
