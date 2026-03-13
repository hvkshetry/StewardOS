from helpers import _infer_zygosity, _variant_key


def test_infer_zygosity_cases():
    assert _infer_zygosity("AA") == "homozygous"
    assert _infer_zygosity("AG") == "heterozygous"
    assert _infer_zygosity("--") == "no_call"
    assert _infer_zygosity("A") == "unknown"


def test_variant_key_stability():
    key1 = _variant_key("GRCh37", "1", 12345, "rs1")
    key2 = _variant_key("GRCh37", "1", 12345, "rs1")
    assert key1 == key2
    assert key1 == "GRCh37:1:12345:rs1"
