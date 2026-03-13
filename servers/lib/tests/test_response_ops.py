import pytest

from stewardos_lib.response_ops import error_response, normalize_tool_output, ok_response


def test_normalize_tool_output_wraps_raw_payload():
    assert normalize_tool_output({"value": 1}) == {
        "status": "ok",
        "errors": [],
        "data": {"value": 1},
    }


def test_normalize_tool_output_passes_through_valid_envelope():
    payload = ok_response({"value": 1}, provenance={"source": "unit"}, model_quality="high")
    assert normalize_tool_output(payload) == payload


def test_normalize_tool_output_passes_through_error_envelope():
    payload = error_response("bad input", code="validation_error", payload={"field": "name"})
    assert normalize_tool_output(payload) == payload


def test_normalize_tool_output_rejects_stringified_json():
    with pytest.raises(TypeError, match="Stringified JSON tool outputs are unsupported"):
        normalize_tool_output('{"error": "bad"}')


def test_normalize_tool_output_rejects_legacy_bare_error_payload():
    with pytest.raises(TypeError, match="Legacy bare error payloads are unsupported"):
        normalize_tool_output({"error": "bad"})


def test_normalize_tool_output_rejects_malformed_envelope():
    with pytest.raises(TypeError, match="Invalid tool envelope"):
        normalize_tool_output({"status": "ok", "errors": []})
