from helpers import _first_nonempty, _read_json_input, _extract_rsids


def test_first_nonempty_works_for_nested():
    assert _first_nonempty("", None, {"label": "A"}) == "A"
    assert _first_nonempty([], {"name": "B"}) == "B"
    assert _first_nonempty(None, "  ", ["C"]) == "C"


def test_read_json_input_direct_dict():
    payload = {"a": 1}
    assert _read_json_input(payload) == payload


def test_read_json_input_code_fenced_json():
    payload = "```json\n{\"a\": 1, \"b\": [2, 3]}\n```"
    assert _read_json_input(payload) == {"a": 1, "b": [2, 3]}


def test_read_json_input_nested_json_string():
    payload = "\"{\\\"geneReports\\\": [{\\\"gene\\\": \\\"CYP2C19\\\"}]}\""
    assert _read_json_input(payload) == {"geneReports": [{"gene": "CYP2C19"}]}


def test_extract_rsids_from_nested_payload():
    payload = {"outer": [{"k": "rs4244285"}, {"inner": "prefix rs4149056 suffix"}]}
    rsids = _extract_rsids(payload)
    assert "rs4244285" in rsids
    assert "rs4149056" in rsids
