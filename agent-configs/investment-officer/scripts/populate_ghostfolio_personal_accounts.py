#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
import subprocess
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".codex" / "config.toml"

ROTH_PDF = Path("/tmp/investments/roth_ira_wealthfront.pdf")
SOLO_PDF = Path("/tmp/investments/solo_401k.pdf")
FIDELITY_529_CSV = Path("/tmp/investments/529_fidelity.csv")
SUMMARY_PATH = Path("/tmp/ghostfolio_personal_import_summary.json")

ROTH_ACCOUNT_ID = "0a22db2f-8dbd-4a68-bd1c-8d50ecb7530d"
SOLO_ACCOUNT_ID = "41b73c11-0984-4ba9-bc17-b17041d38462"
F529_ACCOUNT_ID = "d22242bb-4c4c-4796-ab9f-a9811ac9cdb3"


class ApiError(RuntimeError):
    pass


def to_float(text: str) -> float:
    return float(text.replace(",", "").replace("$", "").strip())


def mmddyyyy_to_iso(date_text: str) -> str:
    month, day, year = date_text.split("/")
    return f"{year}-{int(month):02d}-{int(day):02d}"


def monthname_date_to_iso(date_text: str) -> str:
    month_map = {
        "January": 1,
        "February": 2,
        "March": 3,
        "April": 4,
        "May": 5,
        "June": 6,
        "July": 7,
        "August": 8,
        "September": 9,
        "October": 10,
        "November": 11,
        "December": 12,
    }
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})", date_text.strip())
    if not match:
        raise ValueError(f"Could not parse date: {date_text}")
    month_name, day, year = match.groups()
    month = month_map[month_name]
    return f"{year}-{month:02d}-{int(day):02d}"


def run_pdftotext(path: Path) -> str:
    try:
        return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"pdftotext failed for {path}: {exc}") from exc


def parse_roth_holdings(path: Path) -> dict[str, Any]:
    text = run_pdftotext(path)
    asof_match = re.search(r"Holdings as of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", text)
    if not asof_match:
        raise RuntimeError("Could not locate Roth holdings as-of date.")
    as_of = monthname_date_to_iso(asof_match.group(1))

    section = text.split("I. Holdings as of", 1)[1].split("II. Account Activity", 1)[0]
    pattern = re.compile(
        r"\b([A-Z0-9]{3,6})\s+([0-9,]+\.[0-9]+)\s+\$([0-9,]+\.[0-9]+)\s+\$([0-9,]+\.[0-9]+)\b"
    )

    positions: dict[str, dict[str, float]] = {}
    for match in pattern.finditer(section):
        symbol = match.group(1)
        shares = to_float(match.group(2))
        price = to_float(match.group(3))
        value = to_float(match.group(4))
        if symbol in {"AVDV", "TIMXX"}:
            positions[symbol] = {"quantity": shares, "unit_price": price, "value": value}

    if "AVDV" not in positions or "TIMXX" not in positions:
        raise RuntimeError("Roth holdings parse did not recover both AVDV and TIMXX.")

    ending_match = re.search(r"Ending Balance\s+\$([0-9,]+\.[0-9]{2})", text)
    ending_balance = to_float(ending_match.group(1)) if ending_match else 0.0

    return {
        "as_of": as_of,
        "ending_balance": ending_balance,
        "positions": [
            {
                "symbol": "AVDV",
                "quantity": positions["AVDV"]["quantity"],
                "unit_price": positions["AVDV"]["unit_price"],
            },
            {
                "symbol": "TIMXX",
                "quantity": positions["TIMXX"]["quantity"],
                "unit_price": positions["TIMXX"]["unit_price"],
            },
        ],
    }


def parse_solo_holdings(path: Path) -> dict[str, Any]:
    text = run_pdftotext(path)
    end_date_match = re.search(
        r"Online Statement of Account:\s*\d{2}/\d{2}/\d{4}\s*-\s*(\d{2}/\d{2}/\d{4})",
        text,
    )
    if not end_date_match:
        raise RuntimeError("Could not locate Solo 401k statement end date.")
    as_of = mmddyyyy_to_iso(end_date_match.group(1))

    row_match = re.search(
        r"Vanguard Target Retirement 2055 Fund\s+\$([0-9,]+\.[0-9]{2})\s+\$([0-9,]+\.[0-9]{2})\s+\$([0-9,]+\.[0-9]{2})\s+([0-9,]+\.[0-9]{3})",
        text,
    )
    if not row_match:
        raise RuntimeError("Could not parse Solo 401k fund row.")

    ending_value = to_float(row_match.group(3))
    units = to_float(row_match.group(4))
    if units <= 0:
        raise RuntimeError("Solo 401k parsed units are zero.")

    # Vanguard Target Retirement 2055 Fund public ticker.
    symbol = "VFFVX"

    return {
        "as_of": as_of,
        "ending_balance": ending_value,
        "positions": [
            {
                "symbol": symbol,
                "symbol_candidates": [symbol, "VIVLX"],
                "quantity": units,
                "unit_price": ending_value / units,
            }
        ],
    }


def parse_529_balance(path: Path) -> dict[str, Any]:
    with path.open(newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2 or len(rows[1]) < 5:
        raise RuntimeError("Unexpected 529 CSV structure.")
    ending_mkt_value = to_float(rows[1][4])
    return {"as_of": "2026-02-27", "ending_balance": ending_mkt_value}


def load_ghostfolio_credentials() -> tuple[str, str]:
    cfg = tomllib.loads(CONFIG_PATH.read_text())
    env = cfg["mcp_servers"]["ghostfolio"]["env"]
    return env["GHOSTFOLIO_URL"].rstrip("/"), env["GHOSTFOLIO_TOKEN"]


def api_request(
    *,
    method: str,
    base_url: str,
    token: str,
    path: str,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    url = f"{base_url}{path}{query}"
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url=url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"{method} {path} failed ({exc.code}): {details}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"{method} {path} failed: {exc}") from exc


def delete_orders_for_account(base_url: str, token: str, account_id: str) -> int:
    result = api_request(
        method="DELETE",
        base_url=base_url,
        token=token,
        path="/api/v1/order",
        params={"accounts": account_id},
    )
    if isinstance(result, int):
        return result
    if result is None:
        return 0
    raise ApiError(f"Unexpected delete response for {account_id}: {result!r}")


def create_order(
    *,
    base_url: str,
    token: str,
    account_id: str,
    as_of: str,
    symbol: str,
    quantity: float,
    unit_price: float,
    symbol_candidates: list[str] | None = None,
) -> dict[str, Any]:
    candidates = symbol_candidates[:] if symbol_candidates else [symbol]
    if symbol not in candidates:
        candidates.insert(0, symbol)
    if "." in symbol and symbol.replace(".", "-") not in candidates:
        candidates.append(symbol.replace(".", "-"))

    last_error = ""
    for candidate in candidates:
        payload = {
            "accountId": account_id,
            "currency": "USD",
            "dataSource": "YAHOO",
            "date": as_of,
            "fee": 0,
            "quantity": quantity,
            "symbol": candidate,
            "type": "BUY",
            "unitPrice": unit_price,
        }
        try:
            result = api_request(
                method="POST",
                base_url=base_url,
                token=token,
                path="/api/v1/order",
                payload=payload,
            )
            return {"ok": True, "symbol": symbol, "used_symbol": candidate, "id": result.get("id")}
        except ApiError as exc:
            last_error = str(exc)
    return {"ok": False, "symbol": symbol, "error": last_error}


def update_account(
    *,
    base_url: str,
    token: str,
    account_id: str,
    balance: float,
    comment: str,
) -> None:
    current = api_request(
        method="GET",
        base_url=base_url,
        token=token,
        path=f"/api/v1/account/{account_id}",
    )
    payload = {
        "id": account_id,
        "name": current.get("name"),
        "currency": current.get("currency") or "USD",
        "platformId": current.get("platformId") or "",
        "isExcluded": bool(current.get("isExcluded", False)),
        "balance": balance,
        "comment": comment,
    }
    api_request(
        method="PUT",
        base_url=base_url,
        token=token,
        path=f"/api/v1/account/{account_id}",
        payload=payload,
    )


def count_orders(base_url: str, token: str, account_id: str) -> int:
    data = api_request(
        method="GET",
        base_url=base_url,
        token=token,
        path="/api/v1/order",
        params={"accounts": account_id},
    )
    return int(data.get("count", 0)) if isinstance(data, dict) else 0


def main() -> int:
    base_url, token = load_ghostfolio_credentials()
    roth = parse_roth_holdings(ROTH_PDF)
    solo = parse_solo_holdings(SOLO_PDF)
    f529 = parse_529_balance(FIDELITY_529_CSV)

    import_plan = {
        ROTH_ACCOUNT_ID: {
            "as_of": roth["as_of"],
            "positions": roth["positions"],
            "balance": 0.0,
            "comment": (
                "source:roth_ira_wealthfront.pdf as_of:2026-01-31 "
                "ingestion_state:orders_loaded entity:personal "
                "tax_wrapper:tax_exempt account_type:roth_ira"
            ),
        },
        SOLO_ACCOUNT_ID: {
            "as_of": solo["as_of"],
            "positions": solo["positions"],
            "balance": 0.0,
            "comment": (
                "source:solo_401k.pdf as_of:2026-02-26 "
                "ingestion_state:orders_loaded symbol_inferred:VFFVX "
                "entity:personal tax_wrapper:tax_deferred account_type:solo_401k"
            ),
        },
        F529_ACCOUNT_ID: {
            "as_of": f529["as_of"],
            "positions": [],
            "balance": f529["ending_balance"],
            "comment": (
                "source:529_fidelity.csv as_of:2026-02-27 "
                "ingestion_state:holdings_missing_balance_only "
                "entity:personal tax_wrapper:tax_exempt account_type:529"
            ),
        },
    }

    summary: dict[str, Any] = {"base_url": base_url, "accounts": {}, "failures": []}

    for account_id, plan in import_plan.items():
        deleted = delete_orders_for_account(base_url, token, account_id)
        created = 0
        failed = 0
        for position in plan["positions"]:
            result = create_order(
                base_url=base_url,
                token=token,
                account_id=account_id,
                as_of=plan["as_of"],
                symbol=position["symbol"],
                symbol_candidates=position.get("symbol_candidates"),
                quantity=float(position["quantity"]),
                unit_price=float(position["unit_price"]),
            )
            if result["ok"]:
                created += 1
            else:
                failed += 1
                summary["failures"].append(
                    {
                        "account_id": account_id,
                        "symbol": position["symbol"],
                        "error": result["error"],
                    }
                )

        update_account(
            base_url=base_url,
            token=token,
            account_id=account_id,
            balance=float(plan["balance"]),
            comment=str(plan["comment"]),
        )

        summary["accounts"][account_id] = {
            "as_of": plan["as_of"],
            "deleted_orders": deleted,
            "created_orders": created,
            "failed_orders": failed,
            "updated_balance": plan["balance"],
            "order_count_after_import": count_orders(base_url, token, account_id),
        }

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2))
    print(f"Ghostfolio URL: {base_url}")
    print(f"Summary written: {SUMMARY_PATH}")
    for account_id, data in summary["accounts"].items():
        print(
            f"{account_id}: deleted={data['deleted_orders']} "
            f"created={data['created_orders']} "
            f"failed={data['failed_orders']} "
            f"orders_after={data['order_count_after_import']}"
        )
    print(f"total_failures={len(summary['failures'])}")
    return 0 if not summary["failures"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApiError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
