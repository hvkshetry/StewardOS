"""Exact-scope household-tax error helpers."""

from __future__ import annotations

from typing import Iterable

from stewardos_lib.response_ops import error_response


class UnsupportedExactCase(ValueError):
    """Raised when facts fall outside the hard-cut exact support surface."""

    def __init__(self, reasons: Iterable[str]):
        self.reasons = [str(reason) for reason in reasons if str(reason).strip()]
        super().__init__("; ".join(self.reasons) or "unsupported_exact_case")


def error_response_for_exact_case(exc: UnsupportedExactCase) -> dict:
    return error_response(
        [{"message": reason, "code": "unsupported_exact_case"} for reason in exc.reasons],
        code="unsupported_exact_case",
        payload={"unsupported_reasons": exc.reasons},
    )
