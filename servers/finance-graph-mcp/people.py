from stewardos_lib.db import row_to_dict as _row_to_dict, rows_to_dicts as _rows_to_list
from stewardos_lib.domain_ops import list_people_query as _list_people_query, parse_iso_date as _parse_iso_date
from stewardos_lib.response_ops import error_response as _error_response, make_enveloped_tool as _make_enveloped_tool


def register_people_tools(mcp, get_pool):
    _tool = _make_enveloped_tool(mcp)

    @_tool
    async def list_people() -> list[dict]:
        """List all people in the finance graph."""
        pool = await get_pool()
        rows = await _list_people_query(pool)
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
            return _error_response(f"Person {person_id} not found", code="not_found")

        ownership = await pool.fetch(
            "SELECT * FROM v_ownership_summary WHERE owner_type = 'person' "
            "AND owner_name = $1",
            person["legal_name"],
        )
        docs = await pool.fetch(
            "SELECT id, title, doc_type, expiry_date FROM documents WHERE person_id = $1",
            person_id,
        )
        result = _row_to_dict(person)
        result["ownership"] = _rows_to_list(ownership)
        result["documents"] = _rows_to_list(docs)
        return result

    @_tool
    async def upsert_person(
        legal_name: str,
        preferred_name: str | None = None,
        date_of_birth: str | None = None,
        citizenship: list[str] | None = None,
        residency_status: str | None = None,
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
            citizenship: List of country codes (e.g. ['US', 'IN']).
            residency_status: citizen, resident, nri, oci.
            tax_id: SSN, PAN, etc.
            tax_id_type: SSN, PAN.
            email: Email address.
            phone: Phone number.
            notes: Free-text notes.
            person_id: If provided, updates existing person.
        """
        pool = await get_pool()
        dob = _parse_iso_date(date_of_birth, "date_of_birth")

        if person_id:
            row = await pool.fetchrow(
                """UPDATE people SET legal_name=$1, preferred_name=$2, date_of_birth=$3,
                   citizenship=$4, residency_status=$5, tax_id=$6, tax_id_type=$7,
                   email=$8, phone=$9, notes=$10, updated_at=now()
                   WHERE id=$11 RETURNING id, legal_name""",
                legal_name, preferred_name, dob, citizenship, residency_status,
                tax_id, tax_id_type, email, phone, notes, person_id,
            )
        else:
            row = await pool.fetchrow(
                """INSERT INTO people (legal_name, preferred_name, date_of_birth,
                   citizenship, residency_status, tax_id, tax_id_type, email, phone, notes)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING id, legal_name""",
                legal_name, preferred_name, dob, citizenship, residency_status,
                tax_id, tax_id_type, email, phone, notes,
            )
        return _row_to_dict(row)
