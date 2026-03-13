"""Tests for stewardos_lib.json_utils."""

from stewardos_lib.json_utils import coerce_json_input, extract_numeric_value


class TestCoerceJsonInput:
    def test_dict_passthrough(self):
        assert coerce_json_input({"a": 1}) == {"a": 1}

    def test_none(self):
        assert coerce_json_input(None) == {}

    def test_json_string(self):
        assert coerce_json_input('{"b": 2}') == {"b": 2}

    def test_invalid_json(self):
        assert coerce_json_input("not json") == {}

    def test_json_array_string(self):
        assert coerce_json_input("[1, 2]") == {}

    def test_integer(self):
        assert coerce_json_input(42) == {}


class TestExtractNumericValue:
    def test_price_key(self):
        assert extract_numeric_value({"price": 250000}) == 250000.0

    def test_value_key(self):
        assert extract_numeric_value({"value": 100.5}) == 100.5

    def test_avm_key(self):
        assert extract_numeric_value({"avm": 500000}) == 500000.0

    def test_estimated_value_key(self):
        assert extract_numeric_value({"estimatedValue": 300000}) == 300000.0

    def test_nested_data(self):
        assert extract_numeric_value({"data": {"price": 300000}}) == 300000.0

    def test_nested_list(self):
        assert extract_numeric_value({"results": [{"value": 42}]}) == 42.0

    def test_no_numeric(self):
        assert extract_numeric_value({"desc": "none"}) is None

    def test_non_dict(self):
        assert extract_numeric_value("string") is None

    def test_deep_nesting(self):
        payload = {"data": {"valuation": {"estimate": 999}}}
        assert extract_numeric_value(payload) == 999.0
