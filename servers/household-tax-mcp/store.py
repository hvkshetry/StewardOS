"""Persistence and migration helpers for the household-tax exact engine."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from typing import Any
import uuid

from stewardos_lib.migrations import ensure_migrations_sync

from tax_config import AUTHORITY_BUNDLE_VERSIONS, DEFAULT_TAX_YEAR

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None

DOCUMENT_STORE: dict[str, dict[str, Any]] = {}
RUN_STORE: dict[str, dict[str, Any]] = {}
PLAN_STORE: dict[str, dict[str, Any]] = {}

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
DB_REQUIRED = os.environ.get("HOUSEHOLD_TAX_REQUIRE_DATABASE", "false").strip().lower() in {"1", "true", "yes"}
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_DB_READY = False


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    raise TypeError(f"Cannot JSON serialize {value.__class__.__name__}")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, default=_json_default, sort_keys=True)


def _json_loads(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return value


def _db_enabled() -> bool:
    return bool(DATABASE_URL) and psycopg is not None


def durability_mode() -> str:
    return "database" if _db_enabled() else "memory"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _db_conn(*, autocommit: bool = False):
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    if psycopg is None:
        raise RuntimeError("psycopg is required for database persistence")
    return psycopg.connect(DATABASE_URL, autocommit=autocommit)


def _ensure_db_ready() -> None:
    global _DB_READY
    if _DB_READY:
        return
    if DB_REQUIRED and not _db_enabled():
        raise RuntimeError("Database persistence is required but DATABASE_URL/psycopg is unavailable")
    if not _db_enabled():
        return

    migrations = sorted(path for path in MIGRATIONS_DIR.glob("*.sql") if path.is_file())
    if not migrations:
        raise RuntimeError("No household-tax migrations found")
    with _db_conn() as conn:
        ensure_migrations_sync(
            conn,
            migrations_dir=MIGRATIONS_DIR,
            auto_apply=False,
            migration_table="tax.schema_migrations",
            migration_name_column="version",
        )
        conn.commit()
    _DB_READY = True


def _facts_dict(record_or_facts: dict[str, Any]) -> dict[str, Any]:
    facts = record_or_facts.get("facts") if isinstance(record_or_facts, dict) else None
    if isinstance(facts, dict):
        return facts
    if isinstance(record_or_facts, dict):
        return record_or_facts
    return {}


def _persist_document_children(cur, *, document_id: str, facts: dict[str, Any]) -> None:
    cur.execute("DELETE FROM tax.payment_ledger_events WHERE document_id = %s", (document_id,))
    cur.execute("DELETE FROM tax.prior_year_return_facts WHERE document_id = %s", (document_id,))

    prior_year = facts.get("prior_year")
    if isinstance(prior_year, dict):
        cur.execute(
            """
            INSERT INTO tax.prior_year_return_facts(
                document_id,
                total_tax,
                adjusted_gross_income,
                massachusetts_total_tax,
                full_year_return,
                filed,
                first_year_massachusetts_fiduciary,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, now())
            """,
            (
                document_id,
                prior_year.get("total_tax"),
                prior_year.get("adjusted_gross_income"),
                prior_year.get("massachusetts_total_tax"),
                bool(prior_year.get("full_year_return", True)),
                bool(prior_year.get("filed", True)),
                bool(prior_year.get("first_year_massachusetts_fiduciary", False)),
            ),
        )

    payment_rows: list[tuple[str, str, str, str, str, Any, bool | None]] = []
    for idx, event in enumerate(facts.get("estimated_payments", [])):
        if not isinstance(event, dict):
            continue
        payment_rows.append(
            (
                f"{document_id}:estimated_payment:{idx}",
                document_id,
                "estimated_payment",
                event.get("payment_date"),
                event.get("jurisdiction"),
                event.get("amount"),
                None,
            )
        )
    for idx, event in enumerate(facts.get("withholding_events", [])):
        if not isinstance(event, dict):
            continue
        payment_rows.append(
            (
                f"{document_id}:withholding:{idx}",
                document_id,
                "withholding",
                event.get("payment_date"),
                event.get("jurisdiction"),
                event.get("amount"),
                bool(event.get("treat_as_ratable", True)),
            )
        )

    for event_id, doc_id, event_type, payment_date, jurisdiction, amount, treat_as_ratable in payment_rows:
        cur.execute(
            """
            INSERT INTO tax.payment_ledger_events(
                event_id,
                document_id,
                event_type,
                payment_date,
                jurisdiction,
                amount,
                treat_as_ratable
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event_id,
                doc_id,
                event_type,
                payment_date,
                jurisdiction,
                amount,
                treat_as_ratable,
            ),
        )


def persist_document(record: dict[str, Any]) -> None:
    DOCUMENT_STORE[record["document_id"]] = record
    if not _db_enabled():
        return
    _ensure_db_ready()
    facts = _facts_dict(record)
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tax.return_fact_documents(
                    document_id,
                    entity_type,
                    tax_year,
                    source_name,
                    source_path,
                    facts,
                    support_assessment,
                    ingested_at
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now())
                ON CONFLICT (document_id) DO UPDATE SET
                    source_name = EXCLUDED.source_name,
                    source_path = EXCLUDED.source_path,
                    facts = EXCLUDED.facts,
                    support_assessment = EXCLUDED.support_assessment
                """,
                (
                    record["document_id"],
                    record["entity_type"],
                    int(record["tax_year"]),
                    record.get("source_name"),
                    record.get("source_path"),
                    _json_dumps(facts),
                    _json_dumps(record["support_assessment"]),
                ),
            )
            _persist_document_children(cur, document_id=record["document_id"], facts=facts)
        conn.commit()


def persist_run(record: dict[str, Any]) -> None:
    RUN_STORE[record["run_id"]] = record
    if not _db_enabled():
        return
    _ensure_db_ready()
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tax.exact_runs(
                    run_id,
                    tool_name,
                    entity_type,
                    tax_year,
                    authority_bundle_version,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, now())
                ON CONFLICT (run_id) DO UPDATE SET
                    tool_name = EXCLUDED.tool_name,
                    entity_type = EXCLUDED.entity_type,
                    tax_year = EXCLUDED.tax_year,
                    authority_bundle_version = EXCLUDED.authority_bundle_version
                """,
                (
                    record["run_id"],
                    record["tool_name"],
                    record["entity_type"],
                    int(record["tax_year"]),
                    record.get(
                        "authority_bundle_version",
                        AUTHORITY_BUNDLE_VERSIONS.get(int(record.get("tax_year", DEFAULT_TAX_YEAR)), AUTHORITY_BUNDLE_VERSIONS[DEFAULT_TAX_YEAR]),
                    ),
                ),
            )
            cur.execute(
                """
                INSERT INTO tax.exact_results(
                    run_id,
                    facts,
                    result,
                    created_at
                ) VALUES (%s, %s::jsonb, %s::jsonb, now())
                ON CONFLICT (run_id) DO UPDATE SET
                    facts = EXCLUDED.facts,
                    result = EXCLUDED.result
                """,
                (
                    record["run_id"],
                    _json_dumps(_facts_dict(record)),
                    _json_dumps(record["result"]),
                ),
            )
        conn.commit()


def persist_plan(record: dict[str, Any]) -> None:
    PLAN_STORE[record["plan_id"]] = record
    if not _db_enabled():
        return
    _ensure_db_ready()
    with _db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tax.safe_harbor_plans(
                    plan_id,
                    tool_name,
                    entity_type,
                    tax_year,
                    authority_bundle_version,
                    facts,
                    plan,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, now())
                ON CONFLICT (plan_id) DO UPDATE SET
                    authority_bundle_version = EXCLUDED.authority_bundle_version,
                    facts = EXCLUDED.facts,
                    plan = EXCLUDED.plan
                """,
                (
                    record["plan_id"],
                    record["tool_name"],
                    record["entity_type"],
                    int(record["tax_year"]),
                    record.get(
                        "authority_bundle_version",
                        AUTHORITY_BUNDLE_VERSIONS.get(int(record.get("tax_year", DEFAULT_TAX_YEAR)), AUTHORITY_BUNDLE_VERSIONS[DEFAULT_TAX_YEAR]),
                    ),
                    _json_dumps(_facts_dict(record)),
                    _json_dumps(record["plan"]),
                ),
            )
        conn.commit()


def load_document(document_id: str) -> dict[str, Any] | None:
    if document_id in DOCUMENT_STORE:
        return DOCUMENT_STORE[document_id]
    if not _db_enabled():
        return None
    _ensure_db_ready()
    with _db_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT document_id, entity_type, tax_year, source_name, source_path, facts, support_assessment, ingested_at
                FROM tax.return_fact_documents
                WHERE document_id = %s
                """,
                (document_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "document_id": row[0],
        "entity_type": row[1],
        "tax_year": int(row[2]),
        "source_name": row[3],
        "source_path": row[4],
        "facts": _json_loads(row[5]),
        "support_assessment": _json_loads(row[6]),
        "ingested_at": str(row[7]),
    }


def load_run(run_id: str) -> dict[str, Any] | None:
    if run_id in RUN_STORE:
        return RUN_STORE[run_id]
    if not _db_enabled():
        return None
    _ensure_db_ready()
    with _db_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT r.tool_name,
                       r.entity_type,
                       r.tax_year,
                       r.authority_bundle_version,
                       x.facts,
                       x.result,
                       r.created_at
                FROM tax.exact_runs r
                JOIN tax.exact_results x ON x.run_id = r.run_id
                WHERE r.run_id = %s
                """,
                (run_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "run_id": run_id,
        "tool_name": row[0],
        "entity_type": row[1],
        "tax_year": int(row[2]),
        "authority_bundle_version": row[3],
        "facts": _json_loads(row[4]),
        "result": _json_loads(row[5]),
        "created_at": str(row[6]),
    }


def load_plan(plan_id: str) -> dict[str, Any] | None:
    if plan_id in PLAN_STORE:
        return PLAN_STORE[plan_id]
    if not _db_enabled():
        return None
    _ensure_db_ready()
    with _db_conn(autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tool_name, entity_type, tax_year, authority_bundle_version, facts, plan, created_at
                FROM tax.safe_harbor_plans
                WHERE plan_id = %s
                """,
                (plan_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "plan_id": plan_id,
        "tool_name": row[0],
        "entity_type": row[1],
        "tax_year": int(row[2]),
        "authority_bundle_version": row[3],
        "facts": _json_loads(row[4]),
        "plan": _json_loads(row[5]),
        "created_at": str(row[6]),
    }


def reset_memory_stores() -> None:
    DOCUMENT_STORE.clear()
    RUN_STORE.clear()
    PLAN_STORE.clear()
