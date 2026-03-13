"""Tests for stewardos_lib.constants."""

from stewardos_lib.constants import (
    ASSET_TYPE_BY_CLASS,
    OCF_MINIMAL_SCHEMA,
    REAL_ESTATE_SUBCLASSES,
    canonical_asset_type,
)


class TestCanonicalAssetType:
    def test_real_estate_class(self):
        assert canonical_asset_type("real_estate", "") == "real_estate"

    def test_real_estate_subclass(self):
        assert canonical_asset_type("", "real_estate_residential") == "real_estate"

    def test_real_estate_land(self):
        assert canonical_asset_type("other", "real_estate_land") == "real_estate"

    def test_private_equity(self):
        assert canonical_asset_type("private_equity", "") == "securities"

    def test_unknown(self):
        assert canonical_asset_type("crypto", "") == "other"

    def test_empty(self):
        assert canonical_asset_type("", "") == "other"

    def test_whitespace_normalized(self):
        assert canonical_asset_type("  Real_Estate  ", "") == "real_estate"


class TestConstants:
    def test_asset_type_by_class_has_expected_keys(self):
        assert "real_estate" in ASSET_TYPE_BY_CLASS
        assert "private_equity" in ASSET_TYPE_BY_CLASS

    def test_real_estate_subclasses(self):
        expected = {"real_estate_residential", "real_estate_land",
                    "real_estate_commercial", "real_estate_agricultural"}
        assert REAL_ESTATE_SUBCLASSES == expected

    def test_ocf_schema_structure(self):
        assert OCF_MINIMAL_SCHEMA["type"] == "object"
        assert "ocf_version" in OCF_MINIMAL_SCHEMA["required"]
