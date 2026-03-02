#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".codex" / "config.toml"
HOLDINGS_PATH = Path("/tmp/ghostfolio_jan2026_holdings.json")
SUMMARY_PATH = Path("/tmp/ghostfolio_jan2026_import_summary.json")

UBS_ACCOUNT_ID = "43e79c81-e6a7-4426-9191-7d9d0b05cc31"
VANGUARD_ACCOUNT_ID = "f17b8ccd-e3e5-4a1f-8894-19652c3d000a"

ACCOUNT_IMPORT_SETTINGS = {
    UBS_ACCOUNT_ID: {
        "balance": 30269.66,
        "comment": (
            "source:ubs_irrevocable_trust.pdf account:NE55344 as_of:2026-01-30 "
            "ingestion_state:orders_loaded entity:trust tax_wrapper:taxable "
            "account_type:trust_irrevocable"
        ),
    },
    VANGUARD_ACCOUNT_ID: {
        "balance": 0.0,
        "comment": (
            "source:irrevocable_trust_vanguard.csv as_of:2026-01-31 "
            "ingestion_state:orders_loaded cash_balance_unavailable:set_to_0 "
            "entity:trust tax_wrapper:taxable account_type:trust_irrevocable"
        ),
    },
}


class ApiError(RuntimeError):
    pass


def load_ghostfolio_credentials() -> tuple[str, str]:
    raw = CONFIG_PATH.read_bytes()
    cfg = tomllib.loads(raw.decode("utf-8"))
    env = cfg["mcp_servers"]["ghostfolio"]["env"]
    base_url = env["GHOSTFOLIO_URL"].rstrip("/")
    token = env["GHOSTFOLIO_TOKEN"]
    return base_url, token


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
    body: bytes | None = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url=url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise ApiError(f"{method} {path} failed ({exc.code}): {details}") from exc
    except urllib.error.URLError as exc:
        raise ApiError(f"{method} {path} failed: {exc}") from exc


def load_holdings() -> dict[str, Any]:
    return json.loads(HOLDINGS_PATH.read_text())


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
    raise ApiError(f"Unexpected delete response for account {account_id}: {result!r}")


def order_symbol_candidates(symbol: str, symbol_map: dict[str, str]) -> list[str]:
    candidates: list[str] = []
    mapped = symbol_map.get(symbol)
    if mapped:
        candidates.append(mapped)
    candidates.append(symbol)
    if "." in symbol:
        candidates.append(symbol.replace(".", "-"))
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def create_order_with_fallback(
    *,
    base_url: str,
    token: str,
    account_id: str,
    as_of: str,
    symbol: str,
    quantity: float,
    unit_price: float,
    symbol_map: dict[str, str],
) -> dict[str, Any]:
    last_error: str | None = None
    for candidate_symbol in order_symbol_candidates(symbol, symbol_map):
        payload = {
            "accountId": account_id,
            "currency": "USD",
            "dataSource": "YAHOO",
            "date": as_of,
            "fee": 0,
            "quantity": quantity,
            "symbol": candidate_symbol,
            "type": "BUY",
            "unitPrice": unit_price,
        }
        try:
            created = api_request(
                method="POST",
                base_url=base_url,
                token=token,
                path="/api/v1/order",
                payload=payload,
            )
            return {
                "ok": True,
                "requested_symbol": symbol,
                "used_symbol": candidate_symbol,
                "order_id": created.get("id"),
            }
        except ApiError as exc:
            last_error = str(exc)
            continue
    return {
        "ok": False,
        "requested_symbol": symbol,
        "error": last_error or "unknown error",
    }


def update_account_metadata(
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
    if not isinstance(current, dict):
        raise ApiError(f"Unexpected account response for {account_id}: {current!r}")

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
    if isinstance(data, dict):
        return int(data.get("count", 0))
    return 0


def main() -> int:
    base_url, token = load_ghostfolio_credentials()
    holdings = load_holdings()
    symbol_map = holdings.get("meta", {}).get("symbol_map", {})

    datasets = {
        UBS_ACCOUNT_ID: holdings["ubs"],
        VANGUARD_ACCOUNT_ID: holdings["vanguard"],
    }

    summary: dict[str, Any] = {
        "base_url": base_url,
        "accounts": {},
        "failures": [],
    }

    # Idempotent import: remove existing activities for the target accounts first.
    for account_id in datasets:
        deleted_count = delete_orders_for_account(base_url, token, account_id)
        summary["accounts"].setdefault(account_id, {})
        summary["accounts"][account_id]["deleted_orders"] = deleted_count

    # Create one BUY order per symbol using aggregated cost basis.
    for account_id, dataset in datasets.items():
        as_of = dataset["as_of"]
        created = 0
        failed = 0
        for position in dataset["positions"]:
            quantity = float(position["quantity"])
            cost_basis = float(position["cost_basis"])
            if quantity <= 0 or cost_basis < 0:
                continue
            unit_price = cost_basis / quantity if quantity else 0.0
            result = create_order_with_fallback(
                base_url=base_url,
                token=token,
                account_id=account_id,
                as_of=as_of,
                symbol=position["symbol"],
                quantity=quantity,
                unit_price=unit_price,
                symbol_map=symbol_map,
            )
            if result["ok"]:
                created += 1
            else:
                failed += 1
                failure = {
                    "account_id": account_id,
                    "symbol": result["requested_symbol"],
                    "error": result["error"],
                }
                summary["failures"].append(failure)
        summary["accounts"].setdefault(account_id, {})
        summary["accounts"][account_id]["created_orders"] = created
        summary["accounts"][account_id]["failed_orders"] = failed

    # Update account balance/comment to avoid double-counting prior placeholder balances.
    for account_id, settings in ACCOUNT_IMPORT_SETTINGS.items():
        update_account_metadata(
            base_url=base_url,
            token=token,
            account_id=account_id,
            balance=float(settings["balance"]),
            comment=str(settings["comment"]),
        )
        summary["accounts"].setdefault(account_id, {})
        summary["accounts"][account_id]["updated_balance"] = settings["balance"]
        summary["accounts"][account_id]["order_count_after_import"] = count_orders(
            base_url, token, account_id
        )

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2))
    print(f"Ghostfolio URL: {base_url}")
    print(f"Summary written: {SUMMARY_PATH}")
    for account_id, data in summary["accounts"].items():
        print(
            f"{account_id}: deleted={data.get('deleted_orders', 0)} "
            f"created={data.get('created_orders', 0)} "
            f"failed={data.get('failed_orders', 0)} "
            f"final_orders={data.get('order_count_after_import', 0)}"
        )
    print(f"total_failures={len(summary['failures'])}")
    return 0 if not summary["failures"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ApiError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
