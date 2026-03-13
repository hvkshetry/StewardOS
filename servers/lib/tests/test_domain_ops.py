"""Tests for stewardos_lib.domain_ops — pure logic, no database."""

from datetime import date

import pytest

from stewardos_lib.domain_ops import (
    normalize_currency_code,
    normalize_identifier_type,
    parse_iso_date,
)


class TestNormalizeCurrencyCode:
    def test_valid(self):
        assert normalize_currency_code("USD") == "USD"

    def test_lowercase(self):
        assert normalize_currency_code("usd") == "USD"

    def test_whitespace(self):
        assert normalize_currency_code("  INR  ") == "INR"

    def test_too_short(self):
        assert normalize_currency_code("US") is None

    def test_too_long(self):
        assert normalize_currency_code("USDD") is None

    def test_none(self):
        assert normalize_currency_code(None) is None

    def test_non_string(self):
        assert normalize_currency_code(123) is None


class TestParseIsoDate:
    def test_valid(self):
        assert parse_iso_date("2024-03-15", "test") == date(2024, 3, 15)

    def test_none(self):
        assert parse_iso_date(None, "test") is None

    def test_empty(self):
        assert parse_iso_date("", "test") is None

    def test_invalid(self):
        with pytest.raises(ValueError, match="Invalid test"):
            parse_iso_date("not-a-date", "test")


class TestNormalizeIdentifierType:
    def test_basic(self):
        assert normalize_identifier_type("ssn") == "SSN"

    def test_with_spaces(self):
        assert normalize_identifier_type("tax id") == "TAX_ID"

    def test_empty(self):
        assert normalize_identifier_type("") == ""

    def test_none(self):
        assert normalize_identifier_type(None) == ""
