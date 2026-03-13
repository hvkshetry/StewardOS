"""Characterization tests for shared estate/finance domain functions.

Tests cover:
- Pure-logic shared library functions (row_to_dict, float_or_none, etc.)
- SQL-level characterization of domain_ops (insert_valuation_observation,
  list_entities_query, get_ownership_graph_query) via mock pool
"""

import json
from datetime import date
from unittest.mock import AsyncMock

import pytest

from test_support.db import FakeRecord, mock_asyncpg_pool

from stewardos_lib.constants import (
    ASSET_TYPE_BY_CLASS,
    OCF_MINIMAL_SCHEMA,
    REAL_ESTATE_SUBCLASSES,
    canonical_asset_type as _canonical_asset_type,
)
from stewardos_lib.db import float_or_none as _float_or_none, row_to_dict as _row_to_dict
from stewardos_lib.domain_ops import normalize_currency_code as _normalize_currency_code
from stewardos_lib.json_utils import (
    coerce_json_input as _coerce_json_input,
    extract_numeric_value as _extract_numeric_value,
)


class TestRowToDict:
    def test_empty_record(self):
        from datetime import date
        from decimal import Decimal

        class FakeRecord(dict):
            pass

        record = FakeRecord()
        assert _row_to_dict(record) == {}

    def test_date_serialization(self):
        from datetime import date

        class FakeRecord(dict):
            pass

        record = FakeRecord(created=date(2024, 1, 15))
        result = _row_to_dict(record)
        assert result["created"] == "2024-01-15"

    def test_decimal_to_float(self):
        from decimal import Decimal

        class FakeRecord(dict):
            pass

        record = FakeRecord(amount=Decimal("123.45"))
        result = _row_to_dict(record)
        assert result["amount"] == 123.45
        assert isinstance(result["amount"], float)

    def test_json_string_parsing(self):
        class FakeRecord(dict):
            pass

        record = FakeRecord(meta='{"key": "value"}')
        result = _row_to_dict(record)
        assert result["meta"] == {"key": "value"}

    def test_json_array_string_parsing(self):
        class FakeRecord(dict):
            pass

        record = FakeRecord(tags='["a", "b"]')
        result = _row_to_dict(record)
        assert result["tags"] == ["a", "b"]

    def test_plain_string_preserved(self):
        class FakeRecord(dict):
            pass

        record = FakeRecord(name="hello world")
        result = _row_to_dict(record)
        assert result["name"] == "hello world"

    def test_none_preserved(self):
        class FakeRecord(dict):
            pass

        record = FakeRecord(value=None)
        result = _row_to_dict(record)
        assert result["value"] is None


class TestFloatOrNone:
    def test_valid_float(self):
        assert _float_or_none(42.5) == 42.5

    def test_valid_int(self):
        assert _float_or_none(10) == 10.0

    def test_valid_string(self):
        assert _float_or_none("3.14") == 3.14

    def test_none_returns_none(self):
        assert _float_or_none(None) is None

    def test_invalid_string(self):
        assert _float_or_none("not_a_number") is None


class TestExtractNumericValue:
    def test_direct_price(self):
        assert _extract_numeric_value({"price": 250000}) == 250000.0

    def test_direct_value(self):
        assert _extract_numeric_value({"value": 100.5}) == 100.5

    def test_nested_data(self):
        assert _extract_numeric_value({"data": {"price": 300000}}) == 300000.0

    def test_nested_list(self):
        assert _extract_numeric_value({"results": [{"value": 42}]}) == 42.0

    def test_no_numeric(self):
        assert _extract_numeric_value({"description": "no numbers"}) is None

    def test_non_dict(self):
        assert _extract_numeric_value("not a dict") is None

    def test_avm_key(self):
        assert _extract_numeric_value({"avm": 500000}) == 500000.0


class TestCoerceJsonInput:
    def test_dict_passthrough(self):
        assert _coerce_json_input({"a": 1}) == {"a": 1}

    def test_none_returns_empty(self):
        assert _coerce_json_input(None) == {}

    def test_json_string(self):
        assert _coerce_json_input('{"b": 2}') == {"b": 2}

    def test_invalid_json(self):
        assert _coerce_json_input("not json") == {}

    def test_json_array_returns_empty(self):
        assert _coerce_json_input("[1, 2, 3]") == {}


class TestCanonicalAssetType:
    def test_real_estate(self):
        assert _canonical_asset_type("real_estate", "") == "real_estate"

    def test_real_estate_subclass(self):
        assert _canonical_asset_type("", "real_estate_residential") == "real_estate"

    def test_private_equity(self):
        assert _canonical_asset_type("private_equity", "") == "securities"

    def test_unknown_type(self):
        assert _canonical_asset_type("crypto", "") == "other"

    def test_empty_returns_other(self):
        assert _canonical_asset_type("", "") == "other"


class TestNormalizeCurrencyCode:
    def test_valid_code(self):
        assert _normalize_currency_code("USD") == "USD"

    def test_lowercase_normalized(self):
        assert _normalize_currency_code("usd") == "USD"

    def test_with_whitespace(self):
        assert _normalize_currency_code("  INR  ") == "INR"

    def test_invalid_code(self):
        assert _normalize_currency_code("US") is None

    def test_none_returns_none(self):
        assert _normalize_currency_code(None) is None


class TestConstants:
    def test_asset_type_by_class_keys(self):
        assert "real_estate" in ASSET_TYPE_BY_CLASS
        assert "private_equity" in ASSET_TYPE_BY_CLASS

    def test_real_estate_subclasses(self):
        assert "real_estate_residential" in REAL_ESTATE_SUBCLASSES
        assert "real_estate_commercial" in REAL_ESTATE_SUBCLASSES

    def test_ocf_minimal_schema_structure(self):
        assert OCF_MINIMAL_SCHEMA["type"] == "object"
        assert "ocf_version" in OCF_MINIMAL_SCHEMA["required"]


# ── SQL-level characterization tests for domain_ops ─────────────────────────

from stewardos_lib.domain_ops import (
    insert_valuation_observation,
    get_ownership_graph_query,
    list_entities_query,
)


class TestInsertValuationObservation:
    """Characterize SQL shape and validation of insert_valuation_observation."""

    async def test_rejects_empty_method_code(self):
        pool = mock_asyncpg_pool()
        with pytest.raises(ValueError, match="method_code must be non-empty"):
            await insert_valuation_observation(
                pool=pool, asset_id=1, method_code="",
                source="test", value_amount=100.0,
                value_currency="USD", valuation_date=date(2024, 1, 15),
            )

    async def test_rejects_unknown_method_code(self):
        pool = mock_asyncpg_pool()
        pool.fetchval.return_value = None  # method not found
        pool.fetch.return_value = [FakeRecord(code="appraisal"), FakeRecord(code="market")]
        with pytest.raises(ValueError, match="Unknown method_code"):
            await insert_valuation_observation(
                pool=pool, asset_id=1, method_code="bogus",
                source="test", value_amount=100.0,
                value_currency="USD", valuation_date=date(2024, 1, 15),
            )

    async def test_rejects_invalid_currency(self):
        pool = mock_asyncpg_pool()
        pool.fetchval.return_value = 1  # method exists
        with pytest.raises(ValueError, match="ISO-4217"):
            await insert_valuation_observation(
                pool=pool, asset_id=1, method_code="appraisal",
                source="test", value_amount=100.0,
                value_currency="X", valuation_date=date(2024, 1, 15),
            )

    async def test_inserts_with_correct_sql_shape(self):
        pool = mock_asyncpg_pool()
        pool.fetchval.return_value = 1  # method exists
        pool.fetchrow.return_value = FakeRecord(
            id=42, asset_id=1, method_code="appraisal", source="test",
            value_amount=500000.0, value_currency="USD",
            valuation_date=date(2024, 1, 15), confidence_score=0.9, notes=None,
        )
        result = await insert_valuation_observation(
            pool=pool, asset_id=1, method_code="APPRAISAL",
            source="test", value_amount=500000.0,
            value_currency="usd", valuation_date=date(2024, 1, 15),
            confidence_score=0.9,
        )
        # Verify method_code was normalized to lowercase
        call_args = pool.fetchrow.call_args
        sql = call_args[0][0]
        assert "INSERT INTO valuation_observations" in sql
        assert "RETURNING" in sql
        # Positional params: asset_id, method, source, amount, currency, date, confidence, notes, evidence
        assert call_args[0][2] == "appraisal"  # normalized
        assert call_args[0][5] == "USD"  # normalized
        assert result["id"] == 42

    async def test_evidence_serialized_as_json(self):
        pool = mock_asyncpg_pool()
        pool.fetchval.return_value = 1
        pool.fetchrow.return_value = FakeRecord(id=1)
        await insert_valuation_observation(
            pool=pool, asset_id=1, method_code="market",
            source="zillow", value_amount=300000.0,
            value_currency="USD", valuation_date=date(2024, 6, 1),
            evidence={"url": "https://example.com"},
        )
        call_args = pool.fetchrow.call_args
        # Last positional arg is evidence JSON string
        assert json.loads(call_args[0][9]) == {"url": "https://example.com"}


class TestGetOwnershipGraphQuery:
    """Characterize SQL shape of get_ownership_graph_query."""

    async def test_full_graph_uses_view(self):
        pool = mock_asyncpg_pool()
        pool.fetch.return_value = [FakeRecord(owner_name="Alice", owned_name="LLC")]
        result = await get_ownership_graph_query(pool)
        sql = pool.fetch.call_args[0][0]
        assert "v_ownership_summary" in sql
        assert "ORDER BY owner_name" in sql
        assert len(result) == 1

    async def test_person_filtered_uses_function(self):
        pool = mock_asyncpg_pool()
        pool.fetch.return_value = []
        await get_ownership_graph_query(pool, person_id=7)
        sql = pool.fetch.call_args[0][0]
        assert "get_transitive_ownership" in sql
        assert pool.fetch.call_args[0][1] == 7


class TestListEntitiesQuery:
    """Characterize SQL shape and filter behavior of list_entities_query."""

    async def test_unfiltered_query_shape(self):
        pool = mock_asyncpg_pool()
        pool.fetch.return_value = []
        await list_entities_query(pool)
        sql = pool.fetch.call_args[0][0]
        assert "FROM entities e" in sql
        assert "JOIN entity_types et" in sql
        assert "JOIN jurisdictions j" in sql
        assert "ORDER BY e.name" in sql

    async def test_filters_append_where_clauses(self):
        pool = mock_asyncpg_pool()
        pool.fetch.return_value = []
        await list_entities_query(pool, entity_type="llc", jurisdiction="US", status="active")
        call_args = pool.fetch.call_args[0]
        sql = call_args[0]
        assert "et.code = $1" in sql
        assert "j.code = $2" in sql
        assert "e.status = $3" in sql
        assert call_args[1] == "llc"
        assert call_args[2] == "US"
        assert call_args[3] == "active"

    async def test_partial_filters(self):
        pool = mock_asyncpg_pool()
        pool.fetch.return_value = []
        await list_entities_query(pool, jurisdiction="IN")
        call_args = pool.fetch.call_args[0]
        sql = call_args[0]
        assert "j.code = $1" in sql
        assert "$2" not in sql
        assert call_args[1] == "IN"
