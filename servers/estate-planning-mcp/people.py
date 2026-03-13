from stewardos_lib.db import row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import list_people_query as _list_people_query, parse_iso_date as _parse_iso_date
from stewardos_lib.response_ops import (
    error_response as _error_response,
    make_enveloped_tool as _make_enveloped_tool,
)


def register_people_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def list_people() -> list[dict]:
        """List all family members in the estate-planning graph."""
        pool = await get_pool()
        rows = await _list_people_query(pool, include_estate_fields=True)
        return _rows_to_list(rows)

    @_tool
    async def get_person(person_id: int) -> dict:
        """Get full details for a person including their entity ownership and documents.

        Args:
            person_id: The person's database ID.
        """
        pool = await get_pool()
        person = await pool.fetchrow("SELECT * FROM people WHERE id = $1", person_id)
        if not person:
            return _error_response(f"Person {person_id} not found")

        ownership = await pool.fetch(
            "SELECT * FROM v_ownership_summary WHERE owner_type = 'person' "
            "AND owner_name = $1",
            person["legal_name"],
        )
        docs = await pool.fetch(
            """SELECT dm.paperless_doc_id,
                      COALESCE(dm.source_snapshot_title, d.title) AS title,
                      dm.doc_purpose_type,
                      dm.status,
                      dm.effective_date,
                      dm.expiry_date,
                      dm.last_reviewed
               FROM document_metadata dm
               LEFT JOIN documents d ON d.paperless_doc_id = dm.paperless_doc_id
               WHERE dm.person_id = $1
               ORDER BY dm.paperless_doc_id""",
            person_id,
        )
        relationships = await pool.fetch(
            """SELECT id, person_id, related_person_id, relationship_type,
                      start_date, end_date, jurisdiction_code
               FROM person_relationships
               WHERE person_id = $1 OR related_person_id = $1
               ORDER BY relationship_type, start_date NULLS FIRST""",
            person_id,
        )
        result = _row_to_dict(person)
        result["ownership"] = _rows_to_list(ownership)
        result["documents"] = _rows_to_list(docs)
        result["relationships"] = _rows_to_list(relationships)
        return result

    @_tool
    async def upsert_person(
        legal_name: str,
        preferred_name: str | None = None,
        date_of_birth: str | None = None,
        death_date: str | None = None,
        place_of_birth: str | None = None,
        citizenship: list[str] | None = None,
        tax_residencies: list[str] | None = None,
        residency_status: str | None = None,
        incapacity_status: str | None = None,
        tax_id: str | None = None,
        tax_id_type: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        notes: str | None = None,
        person_id: int | None = None,
    ) -> dict:
        """Create or update a family member. Pass person_id to update existing.

        Args:
            legal_name: Full legal name.
            preferred_name: Preferred/nickname.
            date_of_birth: Date of birth (YYYY-MM-DD).
            death_date: Date of death (YYYY-MM-DD).
            place_of_birth: Place of birth text.
            citizenship: List of country codes (e.g. ['US', 'IN']).
            tax_residencies: Tax residency country codes (e.g. ['US', 'IN']).
            residency_status: citizen, resident, nri, oci.
            incapacity_status: legal_capacity, limited_capacity, incapacitated.
            tax_id: SSN, PAN, etc.
            tax_id_type: SSN, PAN.
            email: Email address.
            phone: Phone number.
            notes: Free-text notes.
            person_id: If provided, updates existing person.
        """
        pool = await get_pool()
        try:
            dob = _parse_iso_date(date_of_birth, "date_of_birth")
            dod = _parse_iso_date(death_date, "death_date")
        except ValueError as exc:
            return _error_response(str(exc))

        if person_id:
            row = await pool.fetchrow(
                """UPDATE people SET legal_name=$1, preferred_name=$2, date_of_birth=$3,
                   death_date=$4, place_of_birth=$5, citizenship=$6, tax_residencies=$7,
                   residency_status=$8, incapacity_status=$9, tax_id=$10, tax_id_type=$11,
                   email=$12, phone=$13, notes=$14, updated_at=now()
                   WHERE id=$15 RETURNING id, legal_name""",
                legal_name, preferred_name, dob, dod, place_of_birth, citizenship, tax_residencies,
                residency_status, incapacity_status, tax_id, tax_id_type,
                email, phone, notes, person_id,
            )
        else:
            row = await pool.fetchrow(
                """INSERT INTO people (legal_name, preferred_name, date_of_birth,
                   death_date, place_of_birth, citizenship, tax_residencies, residency_status,
                   incapacity_status, tax_id, tax_id_type, email, phone, notes)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING id, legal_name""",
                legal_name, preferred_name, dob, dod, place_of_birth, citizenship, tax_residencies,
                residency_status, incapacity_status, tax_id, tax_id_type, email, phone, notes,
            )
        return _row_to_dict(row)

    @_tool
    async def set_person_relationship(
        person_id: int,
        related_person_id: int,
        relationship_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
        jurisdiction_code: str | None = None,
        source_paperless_doc_id: int | None = None,
        notes: str | None = None,
    ) -> dict:
        """Create a first-class family relationship edge used for succession workflows."""
        if person_id == related_person_id:
            return _error_response("person_id and related_person_id must differ")

        pool = await get_pool()
        try:
            sd = _parse_iso_date(start_date, "start_date")
            ed = _parse_iso_date(end_date, "end_date")
        except ValueError as exc:
            return _error_response(str(exc))

        if sd and ed and ed < sd:
            return _error_response("end_date cannot be before start_date")

        row = await pool.fetchrow(
            """INSERT INTO person_relationships (
                   person_id, related_person_id, relationship_type, start_date, end_date,
                   jurisdiction_code, source_paperless_doc_id, notes
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               RETURNING *""",
            person_id,
            related_person_id,
            relationship_type.strip().lower(),
            sd,
            ed,
            jurisdiction_code,
            source_paperless_doc_id,
            notes,
        )
        return _row_to_dict(row)
