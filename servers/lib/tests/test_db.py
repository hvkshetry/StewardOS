"""Tests for stewardos_lib.db — pure unit tests, no database required."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from stewardos_lib.db import float_or_none, row_to_dict, rows_to_dicts


class FakeRecord(dict):
    """Minimal asyncpg.Record stand-in."""
    pass


class TestRowToDict:
    def test_empty(self):
        assert row_to_dict(FakeRecord()) == {}

    def test_date_iso(self):
        r = FakeRecord(d=date(2024, 3, 15))
        assert row_to_dict(r)["d"] == "2024-03-15"

    def test_datetime_iso(self):
        r = FakeRecord(ts=datetime(2024, 3, 15, 10, 30))
        assert row_to_dict(r)["ts"] == "2024-03-15T10:30:00"

    def test_uuid_to_str(self):
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        r = FakeRecord(uid=u)
        assert row_to_dict(r)["uid"] == str(u)

    def test_decimal_to_float(self):
        r = FakeRecord(amount=Decimal("99.99"))
        result = row_to_dict(r)
        assert result["amount"] == 99.99
        assert isinstance(result["amount"], float)

    def test_json_dict_string(self):
        r = FakeRecord(meta='{"key": "val"}')
        assert row_to_dict(r)["meta"] == {"key": "val"}

    def test_json_array_string(self):
        r = FakeRecord(tags='["a", "b"]')
        assert row_to_dict(r)["tags"] == ["a", "b"]

    def test_plain_string(self):
        r = FakeRecord(name="hello")
        assert row_to_dict(r)["name"] == "hello"

    def test_none_preserved(self):
        r = FakeRecord(v=None)
        assert row_to_dict(r)["v"] is None

    def test_invalid_json_string(self):
        r = FakeRecord(x="{not valid json}")
        assert row_to_dict(r)["x"] == "{not valid json}"


class TestRowsToDicts:
    def test_empty_list(self):
        assert rows_to_dicts([]) == []

    def test_multiple_records(self):
        records = [FakeRecord(a=1), FakeRecord(a=2)]
        result = rows_to_dicts(records)
        assert len(result) == 2
        assert result[0]["a"] == 1
        assert result[1]["a"] == 2


class TestFloatOrNone:
    def test_int(self):
        assert float_or_none(10) == 10.0

    def test_float(self):
        assert float_or_none(3.14) == 3.14

    def test_string(self):
        assert float_or_none("42.5") == 42.5

    def test_none(self):
        assert float_or_none(None) is None

    def test_invalid(self):
        assert float_or_none("abc") is None
