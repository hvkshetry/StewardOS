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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / ".codex" / "config.toml"
SOURCE_DIR = Path("/tmp/household-investments")

FIDELITY_POSITIONS_CSV = SOURCE_DIR / "Portfolio_Positions_Mar-01-2026.csv"
WEALTHFRONT_STATEMENT_PDF = SOURCE_DIR / "STATEMENT_2026-01_8W336473_2026-02-01T22_52_13.562-05_00.pdf"
RSU_PDF = SOURCE_DIR / "rsu.pdf"
ESPP_PDF = SOURCE_DIR / "espp.pdf"
PENSION_PDF = SOURCE_DIR / "pension.pdf"
WHATSAPP_BKR_401K_IMG_1 = SOURCE_DIR / "WhatsApp Image 2026-03-01 at 12.01.12 PM.jpeg"
WHATSAPP_BKR_401K_IMG_2 = SOURCE_DIR / "WhatsApp Image 2026-03-01 at 12.01.12 PM 2.jpeg"

OUTPUT_DIR = ROOT / "output"
PAYLOAD_PATH = OUTPUT_DIR / "household_ingestion_payload.json"
SUMMARY_PATH = OUTPUT_DIR / "household_ingestion_summary.json"

OWNER_PRIMARY = "owner_primary"
OWNER_SECONDARY = "owner_secondary"
OWNERSHIP_SOURCE = "manual_household_mapping"
BKR_401K_AS_OF = "2025-12-31"
BKR_401K_BALANCE = 120966.00


class ApiError(RuntimeError):
    pass


@dataclass
class PositionSeed:
    symbol: str
    quantity: float
    unit_price: float
    source: str
    proxy_for: str | None = None

    @property
    def seeded_value(self) -> float:
        return self.quantity * self.unit_price


@dataclass
class AccountSpec:
    name: str
    as_of: str
    balance: float
    is_excluded: bool
    expected_total: float
    tags: dict[str, str]
    positions: list[PositionSeed]

    def comment(self) -> str:
        return build_comment(self.tags)

    @property
    def seeded_total(self) -> float:
        return self.balance + sum(p.seeded_value for p in self.positions)


def to_float(value: str | None) -> float:
    if value is None:
        return 0.0
    cleaned = value.strip()
    if not cleaned:
        return 0.0
    cleaned = cleaned.replace("$", "").replace(",", "")
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    return float(cleaned)


def ensure_source_files() -> None:
    required = [
        FIDELITY_POSITIONS_CSV,
        WEALTHFRONT_STATEMENT_PDF,
        RSU_PDF,
        ESPP_PDF,
        PENSION_PDF,
        WHATSAPP_BKR_401K_IMG_1,
        WHATSAPP_BKR_401K_IMG_2,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing source files: {', '.join(missing)}")


def run_pdftotext(path: Path) -> str:
    try:
        return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"pdftotext failed for {path}: {exc}") from exc


def iso_from_month_name(date_text: str) -> str:
    dt = datetime.strptime(date_text.strip(), "%B %d, %Y")
    return dt.strftime("%Y-%m-%d")


def iso_from_mon_dd_yyyy(date_text: str) -> str:
    dt = datetime.strptime(date_text.strip(), "%b-%d-%Y")
    return dt.strftime("%Y-%m-%d")


def sanitize_tag_value(value: str) -> str:
    return value.strip().replace(" ", "_")


def build_comment(tags: dict[str, str]) -> str:
    ordered_keys = [
        "source",
        "account",
        "as_of",
        "ingestion_state",
        "owner_person",
        "ownership_source",
        "entity",
        "tax_wrapper",
        "account_type",
        "comp_plan",
        "valuation_mode",
    ]
    parts: list[str] = []
    used: set[str] = set()
    for key in ordered_keys:
        if key in tags and tags[key]:
            parts.append(f"{key}:{sanitize_tag_value(tags[key])}")
            used.add(key)
    for key in sorted(tags):
        if key in used:
            continue
        value = tags[key]
        if value:
            parts.append(f"{key}:{sanitize_tag_value(value)}")
    return " ".join(parts)


def upsert_comment_tags(comment: str, updates: dict[str, str]) -> str:
    tokens = [token for token in comment.split() if token]
    kept: list[str] = []
    for token in tokens:
        if ":" not in token:
            kept.append(token)
            continue
        key = token.split(":", 1)[0]
        if key in updates:
            continue
        kept.append(token)
    for key, value in updates.items():
        kept.append(f"{key}:{sanitize_tag_value(value)}")
    return " ".join(kept).strip()


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


def list_accounts(base_url: str, token: str) -> list[dict[str, Any]]:
    data = api_request(method="GET", base_url=base_url, token=token, path="/api/v1/account")
    if not isinstance(data, dict):
        raise ApiError("Unexpected account list response.")
    accounts = data.get("accounts")
    if not isinstance(accounts, list):
        raise ApiError("Account list did not include 'accounts'.")
    return accounts


def get_account(base_url: str, token: str, account_id: str) -> dict[str, Any]:
    data = api_request(
        method="GET",
        base_url=base_url,
        token=token,
        path=f"/api/v1/account/{account_id}",
    )
    if not isinstance(data, dict):
        raise ApiError(f"Unexpected account response for {account_id}.")
    return data


def create_account(
    *,
    base_url: str,
    token: str,
    name: str,
    balance: float,
    comment: str,
    is_excluded: bool,
) -> dict[str, Any]:
    payload = {
        "name": name,
        "currency": "USD",
        "platformId": "",
        "isExcluded": bool(is_excluded),
        "balance": float(balance),
        "comment": comment,
    }
    return api_request(
        method="POST",
        base_url=base_url,
        token=token,
        path="/api/v1/account",
        payload=payload,
    )


def update_account(
    *,
    base_url: str,
    token: str,
    account_id: str,
    name: str,
    currency: str,
    balance: float,
    comment: str,
    is_excluded: bool,
    platform_id: str | None,
) -> None:
    payload = {
        "id": account_id,
        "name": name,
        "currency": currency or "USD",
        "platformId": platform_id or "",
        "isExcluded": bool(is_excluded),
        "balance": float(balance),
        "comment": comment,
    }
    api_request(
        method="PUT",
        base_url=base_url,
        token=token,
        path=f"/api/v1/account/{account_id}",
        payload=payload,
    )


def ensure_account(
    *,
    base_url: str,
    token: str,
    by_name: dict[str, dict[str, Any]],
    spec: AccountSpec,
) -> dict[str, Any]:
    existing = by_name.get(spec.name)
    if existing:
        update_account(
            base_url=base_url,
            token=token,
            account_id=existing["id"],
            name=existing["name"],
            currency=existing.get("currency") or "USD",
            balance=spec.balance,
            comment=spec.comment(),
            is_excluded=spec.is_excluded,
            platform_id=existing.get("platformId"),
        )
        refreshed = get_account(base_url, token, existing["id"])
        by_name[spec.name] = refreshed
        return refreshed

    created = create_account(
        base_url=base_url,
        token=token,
        name=spec.name,
        balance=spec.balance,
        comment=spec.comment(),
        is_excluded=spec.is_excluded,
    )
    account_id = created.get("id")
    if not isinstance(account_id, str):
        raise ApiError(f"Create account response missing id for {spec.name}: {created!r}")
    refreshed = get_account(base_url, token, account_id)
    by_name[spec.name] = refreshed
    return refreshed


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
    position: PositionSeed,
) -> dict[str, Any]:
    symbol_candidates = [position.symbol]
    if "." in position.symbol:
        dashed = position.symbol.replace(".", "-")
        if dashed not in symbol_candidates:
            symbol_candidates.append(dashed)

    last_error = ""
    for candidate in symbol_candidates:
        payload = {
            "accountId": account_id,
            "currency": "USD",
            "dataSource": "YAHOO",
            "date": as_of,
            "fee": 0,
            "quantity": float(position.quantity),
            "symbol": candidate,
            "type": "BUY",
            "unitPrice": float(position.unit_price),
        }
        try:
            created = api_request(
                method="POST",
                base_url=base_url,
                token=token,
                path="/api/v1/order",
                payload=payload,
            )
            return {"ok": True, "used_symbol": candidate, "order_id": created.get("id")}
        except ApiError as exc:
            last_error = str(exc)

    return {"ok": False, "error": last_error}


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


def quote_price(base_url: str, token: str, symbol: str) -> float:
    data = api_request(
        method="GET",
        base_url=base_url,
        token=token,
        path=f"/api/v1/symbol/YAHOO/{urllib.parse.quote(symbol, safe='')}",
    )
    if not isinstance(data, dict) or data.get("marketPrice") is None:
        raise ApiError(f"Quote missing marketPrice for {symbol}: {data!r}")
    return float(data["marketPrice"])


def parse_wealthfront_statement(path: Path) -> dict[str, Any]:
    text = run_pdftotext(path)

    account_match = re.search(r"Wealthfront:\s*([A-Z0-9]+)", text)
    if not account_match:
        raise RuntimeError("Could not parse Wealthfront account number.")
    account_number = account_match.group(1)

    as_of_match = re.search(r"I\. Holdings as of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", text)
    if not as_of_match:
        raise RuntimeError("Could not parse Wealthfront as-of date.")
    as_of = iso_from_month_name(as_of_match.group(1))

    section = text.split("I. Holdings as of", 1)[1].split("II. Account Activity", 1)[0]
    row_pattern = re.compile(
        r"\n\s*([A-Za-z0-9&.,\- ]{3,}?)\s{2,}([A-Z]{1,6}|TIMXX)\s+([0-9,]+(?:\.[0-9]+)?)\s+\$([0-9,]+\.[0-9]+)\s+\$([0-9,]+\.[0-9]+)"
    )

    positions: list[PositionSeed] = []
    seen: set[tuple[str, float, float]] = set()
    for match in row_pattern.finditer(section):
        description = " ".join(match.group(1).split())
        symbol = match.group(2).strip()
        quantity = to_float(match.group(3))
        unit_price = to_float(match.group(4))
        value = to_float(match.group(5))
        key = (symbol, quantity, value)
        if key in seen:
            continue
        seen.add(key)
        positions.append(
            PositionSeed(
                symbol=symbol,
                quantity=quantity,
                unit_price=unit_price,
                source=f"wealthfront_statement:{description}",
            )
        )

    if len(positions) < 40:
        raise RuntimeError(f"Unexpected Wealthfront parsed positions: {len(positions)}")

    total_match = re.search(r"Total Holdings\s+\$([0-9,]+\.[0-9]{2})", section)
    if not total_match:
        raise RuntimeError("Could not parse Wealthfront total holdings.")
    total_holdings = to_float(total_match.group(1))

    parsed_total = sum(p.seeded_value for p in positions)
    if abs(parsed_total - total_holdings) > 0.05:
        raise RuntimeError(
            f"Wealthfront total mismatch: parsed={parsed_total:.2f} expected={total_holdings:.2f}"
        )

    return {
        "account_number": account_number,
        "as_of": as_of,
        "positions": positions,
        "total_holdings": total_holdings,
    }


def parse_fidelity_positions(path: Path) -> dict[str, Any]:
    raw_text = path.read_text(encoding="utf-8-sig", errors="replace")
    downloaded_match = re.search(r"Date downloaded\s+([A-Za-z]{3}-\d{2}-\d{4})", raw_text)
    if not downloaded_match:
        raise RuntimeError("Could not parse Fidelity download date.")
    as_of = iso_from_mon_dd_yyyy(downloaded_match.group(1))

    accounts: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            account_number = (row.get("Account Number") or "").strip()
            if not re.fullmatch(r"[A-Z0-9]+", account_number):
                continue
            account_name = (row.get("Account Name") or "").strip()
            symbol_raw = (row.get("Symbol") or "").strip()
            symbol_clean = re.sub(r"[^A-Z0-9.-]", "", symbol_raw.upper())
            description = (row.get("Description") or "").strip()
            quantity_text = (row.get("Quantity") or "").strip()
            quantity = to_float(quantity_text) if quantity_text else 0.0
            last_price_text = (row.get("Last Price") or "").strip()
            last_price = to_float(last_price_text) if last_price_text else 0.0
            current_value = to_float(row.get("Current Value"))

            account = accounts.setdefault(
                account_number,
                {"account_name": account_name, "rows": [], "total_value": 0.0},
            )
            account["rows"].append(
                {
                    "symbol_raw": symbol_raw,
                    "symbol_clean": symbol_clean,
                    "description": description,
                    "quantity": quantity,
                    "last_price": last_price,
                    "current_value": current_value,
                }
            )
            account["total_value"] += current_value

    if not accounts:
        raise RuntimeError("No Fidelity accounts were parsed.")

    return {"as_of": as_of, "accounts": accounts}


def build_account_specs(
    *,
    wealthfront: dict[str, Any],
    fidelity: dict[str, Any],
    quote_map: dict[str, float],
) -> list[AccountSpec]:
    fidelity_accounts = fidelity["accounts"]
    fidelity_as_of = fidelity["as_of"]

    def fidelity_account(number: str) -> dict[str, Any]:
        if number not in fidelity_accounts:
            raise RuntimeError(f"Missing Fidelity account {number} in source CSV.")
        return fidelity_accounts[number]

    specs: list[AccountSpec] = []

    # Wealthfront taxable account.
    specs.append(
        AccountSpec(
            name="Maneka - Wealthfront Taxable",
            as_of=wealthfront["as_of"],
            balance=0.0,
            is_excluded=False,
            expected_total=float(wealthfront["total_holdings"]),
            tags={
                "source": WEALTHFRONT_STATEMENT_PDF.name,
                "account": wealthfront["account_number"],
                "as_of": wealthfront["as_of"],
                "ingestion_state": "orders_loaded",
                "owner_person": OWNER_PRIMARY,
                "ownership_source": OWNERSHIP_SOURCE,
                "entity": "personal",
                "tax_wrapper": "taxable",
                "account_type": "brokerage",
                "valuation_mode": "direct",
            },
            positions=list(wealthfront["positions"]),
        )
    )

    # Fidelity TOD taxable account.
    tod = fidelity_account("X78623104")
    tod_positions: list[PositionSeed] = []
    for row in tod["rows"]:
        if row["symbol_clean"] == "ENTG":
            tod_positions.append(
                PositionSeed(
                    symbol="ENTG",
                    quantity=row["quantity"],
                    unit_price=row["last_price"],
                    source="fidelity_csv:ENTEGRIS_INC",
                )
            )
        if row["symbol_clean"] == "SPAXX":
            qty = row["quantity"] if row["quantity"] > 0 else row["current_value"]
            price = row["last_price"] if row["last_price"] > 0 else 1.0
            tod_positions.append(
                PositionSeed(
                    symbol="SPAXX",
                    quantity=qty,
                    unit_price=price,
                    source="fidelity_csv:money_market",
                )
            )
    if not tod_positions:
        raise RuntimeError("Did not recover positions for Fidelity TOD account.")

    specs.append(
        AccountSpec(
            name="Maneka - Fidelity TOD",
            as_of=fidelity_as_of,
            balance=0.0,
            is_excluded=False,
            expected_total=float(tod["total_value"]),
            tags={
                "source": FIDELITY_POSITIONS_CSV.name,
                "account": "X78623104",
                "as_of": fidelity_as_of,
                "ingestion_state": "orders_loaded",
                "owner_person": OWNER_PRIMARY,
                "ownership_source": OWNERSHIP_SOURCE,
                "entity": "personal",
                "tax_wrapper": "taxable",
                "account_type": "brokerage",
                "valuation_mode": "direct",
            },
            positions=tod_positions,
        )
    )

    # IRM 401(k) proxy sleeve.
    irm = fidelity_account("53064")
    irm_row = irm["rows"][0]
    irm_proxy = "TRRNX"
    irm_qty = irm["total_value"] / quote_map[irm_proxy]
    specs.append(
        AccountSpec(
            name="Maneka - IRM 401k",
            as_of=fidelity_as_of,
            balance=0.0,
            is_excluded=False,
            expected_total=float(irm["total_value"]),
            tags={
                "source": FIDELITY_POSITIONS_CSV.name,
                "account": "53064",
                "as_of": fidelity_as_of,
                "ingestion_state": "orders_loaded",
                "owner_person": OWNER_PRIMARY,
                "ownership_source": OWNERSHIP_SOURCE,
                "entity": "personal",
                "tax_wrapper": "tax_deferred",
                "account_type": "401k",
                "valuation_mode": "proxy",
                "proxy_for": irm_row["description"] or "TRP_RETIRE_2055_F",
            },
            positions=[
                PositionSeed(
                    symbol=irm_proxy,
                    quantity=irm_qty,
                    unit_price=quote_map[irm_proxy],
                    source="fidelity_csv:proxy",
                    proxy_for=irm_row["description"] or "TRP RETIRE 2055 F",
                )
            ],
        )
    )

    # Entegris 401(k) proxy sleeve.
    ent_401k = fidelity_account("75433")
    ent_proxy = "VFFVX"
    ent_qty = ent_401k["total_value"] / quote_map[ent_proxy]
    specs.append(
        AccountSpec(
            name="Maneka - Entegris 401k",
            as_of=fidelity_as_of,
            balance=0.0,
            is_excluded=False,
            expected_total=float(ent_401k["total_value"]),
            tags={
                "source": FIDELITY_POSITIONS_CSV.name,
                "account": "75433",
                "as_of": fidelity_as_of,
                "ingestion_state": "orders_loaded",
                "owner_person": OWNER_PRIMARY,
                "ownership_source": OWNERSHIP_SOURCE,
                "entity": "personal",
                "tax_wrapper": "tax_deferred",
                "account_type": "401k",
                "valuation_mode": "proxy",
                "proxy_for": "VANGUARD_TARGET_2055",
            },
            positions=[
                PositionSeed(
                    symbol=ent_proxy,
                    quantity=ent_qty,
                    unit_price=quote_map[ent_proxy],
                    source="fidelity_csv:proxy",
                    proxy_for="VANGUARD TARGET 2055",
                )
            ],
        )
    )

    # GEHC retirement plan proxy sleeves.
    gehc = fidelity_account("99829")
    gehc_mapping = {
        "US LARGE CAP EQUITY": "VV",
        "US SMID CAP EQUITY": "VXF",
        "US LG CAP EQUITY IDX": "IVV",
        "2050 TARGET RET FUND": "VFIFX",
    }
    gehc_positions: list[PositionSeed] = []
    for row in gehc["rows"]:
        description = row["description"]
        proxy_symbol = gehc_mapping.get(description)
        if not proxy_symbol:
            continue
        proxy_price = quote_map[proxy_symbol]
        qty = row["current_value"] / proxy_price
        gehc_positions.append(
            PositionSeed(
                symbol=proxy_symbol,
                quantity=qty,
                unit_price=proxy_price,
                source="fidelity_csv:proxy",
                proxy_for=description,
            )
        )
    if len(gehc_positions) != 4:
        raise RuntimeError("GEHC retirement proxy mapping did not produce four sleeves.")

    specs.append(
        AccountSpec(
            name="Maneka - GEHC 401k",
            as_of=fidelity_as_of,
            balance=0.0,
            is_excluded=False,
            expected_total=float(gehc["total_value"]),
            tags={
                "source": FIDELITY_POSITIONS_CSV.name,
                "account": "99829",
                "as_of": fidelity_as_of,
                "ingestion_state": "orders_loaded",
                "owner_person": OWNER_PRIMARY,
                "ownership_source": OWNERSHIP_SOURCE,
                "entity": "personal",
                "tax_wrapper": "tax_deferred",
                "account_type": "401k",
                "valuation_mode": "proxy",
            },
            positions=gehc_positions,
        )
    )

    # Baker Hughes 401(k) from separate WhatsApp statement images.
    bkr_proxy = "VFIFX"
    bkr_qty = BKR_401K_BALANCE / quote_map[bkr_proxy]
    specs.append(
        AccountSpec(
            name="Maneka - Baker Hughes 401k",
            as_of=BKR_401K_AS_OF,
            balance=0.0,
            is_excluded=False,
            expected_total=BKR_401K_BALANCE,
            tags={
                "source": "whatsapp_bkr_401k_2025q4",
                "account": "participant_23466263",
                "as_of": BKR_401K_AS_OF,
                "ingestion_state": "orders_loaded",
                "owner_person": OWNER_PRIMARY,
                "ownership_source": OWNERSHIP_SOURCE,
                "entity": "personal",
                "tax_wrapper": "tax_deferred",
                "account_type": "401k",
                "valuation_mode": "proxy",
                "proxy_for": "BAKER_HUGHES_2050_TARGET_DATE_FUND",
                "plan_id": "15059_01",
            },
            positions=[
                PositionSeed(
                    symbol=bkr_proxy,
                    quantity=bkr_qty,
                    unit_price=quote_map[bkr_proxy],
                    source="whatsapp_statement:2050_target_date_fund",
                    proxy_for="Baker Hughes 2050 Target Date Fund",
                )
            ],
        )
    )

    # HSA.
    hsa = fidelity_account("239894844")
    hsa_cash = 0.0
    pending = 0.0
    for row in hsa["rows"]:
        if row["symbol_clean"] == "FDRXX":
            hsa_cash = row["current_value"]
        if row["symbol_raw"].strip().lower() == "pending activity":
            pending += row["current_value"]
    if hsa_cash <= 0:
        raise RuntimeError("Failed to recover HSA money market balance.")

    specs.append(
        AccountSpec(
            name="Maneka - HSA",
            as_of=fidelity_as_of,
            balance=pending,
            is_excluded=False,
            expected_total=float(hsa["total_value"]),
            tags={
                "source": FIDELITY_POSITIONS_CSV.name,
                "account": "239894844",
                "as_of": fidelity_as_of,
                "ingestion_state": "orders_loaded",
                "owner_person": OWNER_PRIMARY,
                "ownership_source": OWNERSHIP_SOURCE,
                "entity": "personal",
                "tax_wrapper": "tax_exempt",
                "account_type": "hsa",
                "valuation_mode": "direct",
                "pending_activity_usd": f"{pending:.2f}",
            },
            positions=[
                PositionSeed(
                    symbol="FDRXX",
                    quantity=hsa_cash,
                    unit_price=1.0,
                    source="fidelity_csv:money_market",
                )
            ],
        )
    )

    # Unvested RSU off-book tracker.
    rsu_value = 77053.00
    rsu_shares = 580.0
    rsu_unit_price = rsu_value / rsu_shares
    specs.append(
        AccountSpec(
            name="Maneka - ENTG RSU (Unvested)",
            as_of="2026-03-01",
            balance=0.0,
            is_excluded=True,
            expected_total=rsu_value,
            tags={
                "source": RSU_PDF.name,
                "as_of": "2026-03-01",
                "ingestion_state": "offbook_unvested",
                "owner_person": OWNER_PRIMARY,
                "ownership_source": OWNERSHIP_SOURCE,
                "entity": "personal",
                "tax_wrapper": "taxable",
                "account_type": "equity_comp",
                "comp_plan": "rsu",
                "valuation_mode": "offbook",
                "grant_id": "RSU25R15",
                "granted_shares": "580",
                "vest_2026_04_05": "145",
                "vest_2027_04_05": "145",
                "vest_2028_04_05": "145",
                "vest_2029_04_05": "145",
            },
            positions=[
                PositionSeed(
                    symbol="ENTG",
                    quantity=rsu_shares,
                    unit_price=rsu_unit_price,
                    source="rsu_snapshot",
                )
            ],
        )
    )

    # ESPP contribution off-book tracker.
    specs.append(
        AccountSpec(
            name="Maneka - ENTG ESPP (Contrib)",
            as_of="2026-03-01",
            balance=1769.24,
            is_excluded=True,
            expected_total=1769.24,
            tags={
                "source": ESPP_PDF.name,
                "as_of": "2026-03-01",
                "ingestion_state": "offbook_contrib",
                "owner_person": OWNER_PRIMARY,
                "ownership_source": OWNERSHIP_SOURCE,
                "entity": "personal",
                "tax_wrapper": "taxable",
                "account_type": "equity_comp",
                "comp_plan": "espp",
                "valuation_mode": "offbook",
                "offering_start": "2026_01_01",
                "offering_end": "2026_06_30",
                "next_acq": "2026_06_30",
            },
            positions=[],
        )
    )

    return specs


def summarize_spec(spec: AccountSpec) -> dict[str, Any]:
    return {
        "name": spec.name,
        "as_of": spec.as_of,
        "balance": round(spec.balance, 6),
        "is_excluded": spec.is_excluded,
        "expected_total": round(spec.expected_total, 6),
        "seeded_total": round(spec.seeded_total, 6),
        "comment": spec.comment(),
        "positions": [
            {
                "symbol": p.symbol,
                "quantity": round(p.quantity, 10),
                "unit_price": round(p.unit_price, 10),
                "seeded_value": round(p.seeded_value, 6),
                "source": p.source,
                "proxy_for": p.proxy_for,
            }
            for p in spec.positions
        ],
    }


def main() -> int:
    ensure_source_files()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base_url, token = load_ghostfolio_credentials()
    wealthfront = parse_wealthfront_statement(WEALTHFRONT_STATEMENT_PDF)
    fidelity = parse_fidelity_positions(FIDELITY_POSITIONS_CSV)

    proxy_symbols = ["TRRNX", "VFFVX", "VFIFX", "VV", "VXF", "IVV"]
    quote_map = {symbol: quote_price(base_url, token, symbol) for symbol in proxy_symbols}

    specs = build_account_specs(wealthfront=wealthfront, fidelity=fidelity, quote_map=quote_map)
    spec_by_name = {spec.name: spec for spec in specs}

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_dir": str(SOURCE_DIR),
        "quotes": quote_map,
        "accounts": [summarize_spec(spec) for spec in specs],
        "owner_backfill": {
            "owner_tag_key": "owner_person",
            "new_accounts_owner": OWNER_PRIMARY,
            "existing_accounts_owner": OWNER_SECONDARY,
        },
    }
    PAYLOAD_PATH.write_text(json.dumps(payload, indent=2))

    existing_accounts = list_accounts(base_url, token)
    by_name = {account["name"]: account for account in existing_accounts}

    summary: dict[str, Any] = {
        "base_url": base_url,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "payload_path": str(PAYLOAD_PATH),
        "managed_accounts": {},
        "owner_backfill_updates": [],
        "failures": [],
    }

    managed_ids: set[str] = set()
    for spec in specs:
        account = ensure_account(base_url=base_url, token=token, by_name=by_name, spec=spec)
        account_id = account["id"]
        managed_ids.add(account_id)

        deleted = delete_orders_for_account(base_url, token, account_id)
        created = 0
        failed = 0
        position_results: list[dict[str, Any]] = []
        for position in spec.positions:
            result = create_order(
                base_url=base_url,
                token=token,
                account_id=account_id,
                as_of=spec.as_of,
                position=position,
            )
            if result["ok"]:
                created += 1
                position_results.append(
                    {
                        "symbol": position.symbol,
                        "used_symbol": result["used_symbol"],
                        "quantity": position.quantity,
                        "unit_price": position.unit_price,
                        "proxy_for": position.proxy_for,
                    }
                )
            else:
                failed += 1
                summary["failures"].append(
                    {"account_name": spec.name, "symbol": position.symbol, "error": result["error"]}
                )

        # Re-apply balance/comment after order operations.
        refreshed = get_account(base_url, token, account_id)
        update_account(
            base_url=base_url,
            token=token,
            account_id=account_id,
            name=refreshed["name"],
            currency=refreshed.get("currency") or "USD",
            balance=spec.balance,
            comment=spec.comment(),
            is_excluded=spec.is_excluded,
            platform_id=refreshed.get("platformId"),
        )

        final_account = get_account(base_url, token, account_id)
        summary["managed_accounts"][spec.name] = {
            "account_id": account_id,
            "deleted_orders": deleted,
            "created_orders": created,
            "failed_orders": failed,
            "order_count_after_import": count_orders(base_url, token, account_id),
            "expected_total": round(spec.expected_total, 6),
            "seeded_total": round(spec.seeded_total, 6),
            "seed_vs_expected_diff": round(spec.seeded_total - spec.expected_total, 6),
            "ghostfolio_value": round(float(final_account.get("value") or 0.0), 6),
            "ghostfolio_balance": round(float(final_account.get("balance") or 0.0), 6),
            "comment": final_account.get("comment") or "",
            "positions": position_results,
        }

    # Owner tag backfill across all non-Maneka accounts.
    all_accounts_after = list_accounts(base_url, token)
    for account in all_accounts_after:
        account_id = account["id"]
        account_name = account["name"]
        desired_owner = OWNER_PRIMARY if account_id in managed_ids or account_name in spec_by_name else OWNER_SECONDARY
        current_comment = account.get("comment") or ""
        updated_comment = upsert_comment_tags(
            current_comment,
            {"owner_person": desired_owner, "ownership_source": OWNERSHIP_SOURCE},
        )
        if updated_comment == current_comment:
            continue
        update_account(
            base_url=base_url,
            token=token,
            account_id=account_id,
            name=account_name,
            currency=account.get("currency") or "USD",
            balance=float(account.get("balance") or 0.0),
            comment=updated_comment,
            is_excluded=bool(account.get("isExcluded", False)),
            platform_id=account.get("platformId"),
        )
        summary["owner_backfill_updates"].append(
            {"account_id": account_id, "name": account_name, "owner_person": desired_owner}
        )

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2))

    print(f"Ghostfolio URL: {base_url}")
    print(f"Payload written: {PAYLOAD_PATH}")
    print(f"Summary written: {SUMMARY_PATH}")
    for account_name, details in summary["managed_accounts"].items():
        print(
            f"{account_name}: deleted={details['deleted_orders']} "
            f"created={details['created_orders']} failed={details['failed_orders']} "
            f"orders_after={details['order_count_after_import']}"
        )
    print(f"owner_backfill_updates={len(summary['owner_backfill_updates'])}")
    print(f"failures={len(summary['failures'])}")

    if summary["failures"]:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ApiError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
