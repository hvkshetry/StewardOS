#!/usr/bin/env python3
"""Build deterministic ingestion payloads for Actual and Ghostfolio."""

from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


ROOT_TMP = Path("/tmp")
BANK_DIR = ROOT_TMP / "bank_cc"
INVEST_DIR = ROOT_TMP / "investments"
OUTPUT_PATH = ROOT_TMP / "ingestion_payload.json"
SUMMARY_PATH = ROOT_TMP / "ingestion_summary.json"


ACTUAL_ACCOUNTS = {
    "barclays_cc": "Barclays Credit Card",
    "chase_cc": "Chase Credit Card - Hersh",
    "citizens_checking": "Citizens Checking",
    "everbank_checking": "EverBank Checking",
}

# Canonical remote account ids for deterministic import mapping.
ACTUAL_ACCOUNT_IDS_BY_KEY = {
    "barclays_cc": "8d094a41-e456-43ea-abb7-5aa0a9cc7d13",
    "chase_cc": "5d937ddb-dde2-4149-8b42-9117fff29eb0",
    "citizens_checking": "7852e6d9-a9b4-460a-ad44-3aac17f24e40",
    "everbank_checking": "6c76202c-3b8b-43e2-9e33-707ad9c623fe",
}


CATEGORY_GROUPS = [
    {"name": "Income", "is_income": True, "categories": ["Payroll", "Interest", "Credits/Refunds"]},
    {"name": "Housing & Utilities", "is_income": False, "categories": ["Mortgage", "Utilities", "Telecom", "Taxes"]},
    {"name": "Food & Dining", "is_income": False, "categories": ["Groceries", "Dining"]},
    {"name": "Transportation", "is_income": False, "categories": ["Gas", "Tolls/Parking", "Rideshare", "Travel"]},
    {"name": "Health", "is_income": False, "categories": ["Pharmacy/Medical"]},
    {
        "name": "Shopping & Lifestyle",
        "is_income": False,
        "categories": ["Shopping", "Subscriptions", "Personal Care", "Entertainment"],
    },
    {"name": "Family & Giving", "is_income": False, "categories": ["Gifts/Donations", "Family Activities"]},
    {"name": "Cash & Fees", "is_income": False, "categories": ["ATM/Cash", "Bank & Card Fees"]},
    {"name": "Transfers", "is_income": False, "categories": ["Internal Transfers", "External Transfers"]},
    {"name": "Review", "is_income": False, "categories": ["Uncategorized Review"]},
]


GENERIC_PIPE_PREFIXES = {
    "ACCOUNT DEBIT",
    "ACCOUNT CREDIT",
    "DEBIT",
    "CREDIT",
    "EXTERNAL TRANSFER DR",
    "EXTERNAL TRANSFER CR",
}


SUBSCRIPTION_HINTS = (
    "SPOTIFY",
    "DISNEY",
    "PRIME VIDEO",
    "APPLE.COM/BILL",
    "AMAZON WEB SERVICES",
    "OURARING",
)


DINING_HINTS = (
    "TST*",
    "RESTAURANT",
    "CAFE",
    "BAKERY",
    "POKE BROS",
    "CHIPOTLE",
    "ADELITA",
    "RED HEAT",
    "MARKET - BI",
    "GINGER JAP",
    "STATE STREET",
)


GROCERY_HINTS = ("WHOLEFDS", "WHOLE FOODS", "HUEL", "MARKET BASKET")


@dataclass
class NormalizedTxn:
    source_file: str
    source_row: int
    account_key: str
    date_yyyy_mm_dd: str
    amount_cents: int
    payee_name: str
    imported_payee: str
    category_name: str
    imported_id: str
    is_internal_transfer: bool
    transfer_counterparty_account: str | None
    notes: str

    def as_actual_payload(self) -> dict:
        return {
            "date": self.date_yyyy_mm_dd,
            "amount": self.amount_cents,
            "payee_name": self.payee_name,
            "imported_payee": self.imported_payee,
            "category_name": self.category_name,
            "imported_id": self.imported_id,
            "cleared": True,
            "notes": self.notes,
        }


def parse_money_to_float(value: str | None) -> float:
    if value is None:
        return 0.0
    cleaned = value.replace("$", "").replace(",", "").strip()
    if cleaned == "":
        return 0.0
    return float(cleaned)


def cents(value_float: float) -> int:
    return int(round(value_float * 100))


def parse_date(raw: str, fmt: str) -> str:
    return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def pick_payee(description: str) -> str:
    desc = normalize_space(description)
    if "|" in desc:
        left, right = [part.strip() for part in desc.split("|", 1)]
        if left.upper() in GENERIC_PIPE_PREFIXES:
            desc = right
        else:
            desc = left
    desc = re.sub(r"\s+\d{5,}.*$", "", desc)
    desc = normalize_space(desc)
    return desc[:80] if len(desc) > 80 else desc


def stable_imported_id(
    source_file: str,
    source_row: int,
    account_key: str,
    date_yyyy_mm_dd: str,
    amount_cents: int,
    imported_payee: str,
) -> str:
    raw = f"{source_file}|{source_row}|{account_key}|{date_yyyy_mm_dd}|{amount_cents}|{normalize_space(imported_payee)}"
    return "ingest_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def classify_chase(row: dict) -> tuple[str, bool, str | None]:
    desc = normalize_space(row.get("Description", ""))
    desc_upper = desc.upper()
    category = normalize_space(row.get("Category", ""))
    txn_type = normalize_space(row.get("Type", ""))
    amount = parse_money_to_float(row.get("Amount"))

    if txn_type.upper() == "PAYMENT" and "AUTOMATIC PAYMENT" in desc_upper:
        return ("Internal Transfers", True, "everbank_checking")
    if "E-ZPASS" in desc_upper:
        return ("Tolls/Parking", False, None)
    if "UBER" in desc_upper:
        return ("Rideshare", False, None)
    if "CVS/PHARMACY" in desc_upper or "PHARMACY" in desc_upper:
        return ("Pharmacy/Medical", False, None)
    if "SUPERCUTS" in desc_upper:
        return ("Personal Care", False, None)
    if any(hint in desc_upper for hint in SUBSCRIPTION_HINTS):
        return ("Subscriptions", False, None)
    if any(hint in desc_upper for hint in DINING_HINTS):
        return ("Dining", False, None)
    if any(hint in desc_upper for hint in GROCERY_HINTS):
        return ("Groceries", False, None)
    if "DISCOVERY MUSEUM" in desc_upper:
        return ("Family Activities", False, None)

    category_map = {
        "Shopping": "Shopping",
        "Food & Drink": "Dining",
        "Groceries": "Groceries",
        "Bills & Utilities": "Utilities",
        "Travel": "Travel",
        "Gas": "Gas",
        "Health & Wellness": "Pharmacy/Medical",
        "Personal": "Personal Care",
        "Gifts & Donations": "Gifts/Donations",
        "Entertainment": "Entertainment",
        "Home": "Shopping",
        "Automotive": "Transportation",
        "Fees & Adjustments": "Bank & Card Fees",
    }

    if txn_type.upper() in {"RETURN", "REVERSAL"} and amount > 0:
        return ("Credits/Refunds", False, None)
    if txn_type.upper() == "FEE":
        return ("Bank & Card Fees", False, None)
    if category in category_map:
        return (category_map[category], False, None)
    if txn_type.upper() == "PAYMENT":
        return ("Internal Transfers", True, "everbank_checking")
    return ("Uncategorized Review", False, None)


def classify_barclays(row: dict) -> tuple[str, bool, str | None]:
    desc = normalize_space(row.get("Description", ""))
    desc_upper = desc.upper()
    category = normalize_space(row.get("Category", "")).upper()
    amount = parse_money_to_float(row.get("Amount"))

    if "PAYMENT RECEIVED" in desc_upper and amount > 0:
        return ("Internal Transfers", True, "everbank_checking")
    if "PRIMARY ANNUAL FEE" in desc_upper:
        return ("Bank & Card Fees", False, None)
    if "E-ZPASS" in desc_upper:
        return ("Tolls/Parking", False, None)
    if "CVS/PHARMACY" in desc_upper:
        return ("Pharmacy/Medical", False, None)
    if "NORTHSIDE CONVENIENCE" in desc_upper:
        return ("Gas", False, None)
    if "UBER" in desc_upper:
        return ("Rideshare", False, None)
    if "SPOTIFY" in desc_upper or "OURARING" in desc_upper:
        return ("Subscriptions", False, None)
    if "THORNE RESEARCH" in desc_upper or "CARE - PSI" in desc_upper:
        return ("Pharmacy/Medical", False, None)
    if "AMC" in desc_upper:
        return ("Entertainment", False, None)
    if "DISCOVERY MUSEUM" in desc_upper:
        return ("Family Activities", False, None)
    if any(hint in desc_upper for hint in GROCERY_HINTS):
        return ("Groceries", False, None)
    if any(hint in desc_upper for hint in DINING_HINTS):
        return ("Dining", False, None)

    if category == "CREDIT" and amount > 0:
        return ("Credits/Refunds", False, None)
    if category == "DEBIT":
        return ("Shopping", False, None)
    return ("Uncategorized Review", False, None)


def classify_citizens(row: dict) -> tuple[str, bool, str | None]:
    desc = normalize_space(row.get("Description", ""))
    desc_upper = desc.upper()
    txn_type = normalize_space(row.get("Transaction Type", "")).upper()
    amount = parse_money_to_float(row.get("Amount"))

    if "EVERBK CK WEBXFR" in desc_upper:
        return ("Internal Transfers", True, "everbank_checking")
    if "CITIZENS MTG PMT" in desc_upper:
        return ("Mortgage", False, None)
    if "FID BKG SVC LLC MONEYLINE" in desc_upper:
        return ("External Transfers", False, None)
    if "CAPITAL ONE TRANSFER" in desc_upper or "WEALTHFRONT EDI PYMNTS" in desc_upper or "EVERBANK TRANSFER" in desc_upper:
        return ("External Transfers", False, None)
    if "ZELLE" in desc_upper or "VENMO" in desc_upper or "SPLITWISE" in desc_upper:
        return ("External Transfers", False, None)
    if txn_type == "ATM DEBIT":
        return ("ATM/Cash", False, None)
    if "NORTHSIDE CONV" in desc_upper:
        return ("Gas", False, None)
    if txn_type == "OTHER" and amount > 0 and abs(amount) <= 100:
        return ("Interest", False, None)
    if txn_type in {"CREDIT", "DEPOSIT"} and amount > 0:
        return ("Credits/Refunds", False, None)
    if txn_type == "DIRECT DEPOSIT" and amount > 0:
        return ("Payroll", False, None)
    if txn_type in {"DEBIT", "DIRECT DEBIT", "POS DEBIT"}:
        return ("External Transfers", False, None)
    return ("Uncategorized Review", False, None)


def classify_everbank(row: dict) -> tuple[str, bool, str | None]:
    desc = normalize_space(row.get("Description", ""))
    desc_upper = desc.upper()
    txn_type = normalize_space(row.get("Transaction Type", "")).upper()
    debit = parse_money_to_float(row.get("Debits(-)"))
    credit = parse_money_to_float(row.get("Credits(+)"))
    amount = debit if debit != 0 else credit

    if "CIRCLE H2O LLC PAYROLL" in desc_upper and amount > 0:
        return ("Payroll", False, None)
    if "INTEREST CREDIT" in desc_upper:
        return ("Interest", False, None)
    if "CHASE CREDIT CRD AUTOPAY" in desc_upper:
        return ("Internal Transfers", True, "chase_cc")
    if "BARCLAYCARD US CREDITCARD" in desc_upper:
        return ("Internal Transfers", True, "barclays_cc")
    if "CITIZE CK WEBXFR" in desc_upper:
        return ("Internal Transfers", True, "citizens_checking")
    if "EXTERNAL TRANSFER" in desc_upper or "WIRE TRANSFER" in desc_upper:
        return ("External Transfers", False, None)
    if "ZELLE" in desc_upper or "PAYPAL INST XFER" in desc_upper:
        return ("External Transfers", False, None)
    if "EVERSOURCE" in desc_upper or "NGRID" in desc_upper or "NATIONAL GRID" in desc_upper:
        return ("Utilities", False, None)
    if "VERIZON" in desc_upper or re.search(r"\bATT\b", desc_upper):
        return ("Telecom", False, None)
    if "TOWN OF BEDFORD" in desc_upper:
        return ("Taxes", False, None)
    if "UNIPAYFEE" in desc_upper:
        return ("Bank & Card Fees", False, None)
    if txn_type == "CREDIT" and amount > 0:
        return ("Credits/Refunds", False, None)
    return ("Uncategorized Review", False, None)


def build_txn(
    *,
    source_file: str,
    source_row: int,
    account_key: str,
    date_yyyy_mm_dd: str,
    amount_cents: int,
    description: str,
    category_name: str,
    is_internal_transfer: bool,
    transfer_counterparty_account: str | None,
) -> NormalizedTxn:
    imported_payee = normalize_space(description)
    payee_name = pick_payee(imported_payee) or "Unknown"
    imported_id = stable_imported_id(
        source_file=source_file,
        source_row=source_row,
        account_key=account_key,
        date_yyyy_mm_dd=date_yyyy_mm_dd,
        amount_cents=amount_cents,
        imported_payee=imported_payee,
    )
    notes = f"src={source_file}#{source_row}"
    if transfer_counterparty_account:
        notes += f";counterparty={transfer_counterparty_account}"
    return NormalizedTxn(
        source_file=source_file,
        source_row=source_row,
        account_key=account_key,
        date_yyyy_mm_dd=date_yyyy_mm_dd,
        amount_cents=amount_cents,
        payee_name=payee_name,
        imported_payee=imported_payee,
        category_name=category_name,
        imported_id=imported_id,
        is_internal_transfer=is_internal_transfer,
        transfer_counterparty_account=transfer_counterparty_account,
        notes=notes,
    )


def load_chase() -> list[NormalizedTxn]:
    path = BANK_DIR / "chase_cc_transactions.CSV"
    output: list[NormalizedTxn] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=2):
            raw_date = normalize_space(row.get("Transaction Date", ""))
            if not raw_date:
                continue
            date_yyyy_mm_dd = parse_date(raw_date, "%m/%d/%Y")
            amount_cents = cents(parse_money_to_float(row.get("Amount")))
            category_name, is_transfer, counterparty = classify_chase(row)
            output.append(
                build_txn(
                    source_file=path.name,
                    source_row=idx,
                    account_key="chase_cc",
                    date_yyyy_mm_dd=date_yyyy_mm_dd,
                    amount_cents=amount_cents,
                    description=row.get("Description", ""),
                    category_name=category_name,
                    is_internal_transfer=is_transfer,
                    transfer_counterparty_account=counterparty,
                )
            )
    return output


def load_barclays() -> list[NormalizedTxn]:
    path = BANK_DIR / "barclays_cc_transactions.csv"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header_idx = next(i for i, line in enumerate(lines) if line.startswith("Transaction Date,"))
    reader = csv.DictReader(lines[header_idx:])
    output: list[NormalizedTxn] = []
    for offset, row in enumerate(reader, start=header_idx + 2):
        raw_date = normalize_space(row.get("Transaction Date", ""))
        if not raw_date:
            continue
        date_yyyy_mm_dd = parse_date(raw_date, "%m/%d/%Y")
        amount_cents = cents(parse_money_to_float(row.get("Amount")))
        category_name, is_transfer, counterparty = classify_barclays(row)
        output.append(
            build_txn(
                source_file=path.name,
                source_row=offset,
                account_key="barclays_cc",
                date_yyyy_mm_dd=date_yyyy_mm_dd,
                amount_cents=amount_cents,
                description=row.get("Description", ""),
                category_name=category_name,
                is_internal_transfer=is_transfer,
                transfer_counterparty_account=counterparty,
            )
        )
    return output


def load_citizens() -> list[NormalizedTxn]:
    path = BANK_DIR / "citizens_transactions.csv"
    output: list[NormalizedTxn] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=2):
            raw_date = normalize_space(row.get("Date", ""))
            if not raw_date:
                continue
            date_yyyy_mm_dd = parse_date(raw_date, "%m/%d/%y")
            amount_cents = cents(parse_money_to_float(row.get("Amount")))
            category_name, is_transfer, counterparty = classify_citizens(row)
            output.append(
                build_txn(
                    source_file=path.name,
                    source_row=idx,
                    account_key="citizens_checking",
                    date_yyyy_mm_dd=date_yyyy_mm_dd,
                    amount_cents=amount_cents,
                    description=row.get("Description", ""),
                    category_name=category_name,
                    is_internal_transfer=is_transfer,
                    transfer_counterparty_account=counterparty,
                )
            )
    return output


def load_everbank() -> list[NormalizedTxn]:
    path = BANK_DIR / "everbank_transactions.csv"
    output: list[NormalizedTxn] = []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for idx, row in enumerate(reader, start=2):
            raw_date = normalize_space(row.get("Date", ""))
            if not raw_date:
                continue
            date_yyyy_mm_dd = parse_date(raw_date, "%m/%d/%Y")
            debit = parse_money_to_float(row.get("Debits(-)"))
            credit = parse_money_to_float(row.get("Credits(+)"))
            amount_cents = cents(debit if debit != 0 else credit)
            category_name, is_transfer, counterparty = classify_everbank(row)
            output.append(
                build_txn(
                    source_file=path.name,
                    source_row=idx,
                    account_key="everbank_checking",
                    date_yyyy_mm_dd=date_yyyy_mm_dd,
                    amount_cents=amount_cents,
                    description=row.get("Description", ""),
                    category_name=category_name,
                    is_internal_transfer=is_transfer,
                    transfer_counterparty_account=counterparty,
                )
            )
    return output


def extract_pdf_text(path: Path) -> str:
    return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True)


def extract_roth_value() -> float:
    text = extract_pdf_text(INVEST_DIR / "roth_ira_wealthfront.pdf")
    match = re.search(r"January 31, 2026\s+Ending Balance\s+\$([0-9,]+\.[0-9]{2})", text)
    if not match:
        raise RuntimeError("Could not parse Wealthfront Roth ending balance from PDF.")
    return parse_money_to_float(match.group(1))


def extract_solo_401k_value() -> float:
    text = extract_pdf_text(INVEST_DIR / "solo_401k.pdf")
    match = re.search(r"Ending Value \(as of 02/26/2026\)\s+\$([0-9,]+\.[0-9]{2})", text)
    if not match:
        raise RuntimeError("Could not parse solo 401k ending value from PDF.")
    return parse_money_to_float(match.group(1))


def extract_529_value() -> float:
    path = INVEST_DIR / "529_fidelity.csv"
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        first = next(reader)
        return parse_money_to_float(first.get("Ending mkt Value"))


def extract_ubs_value() -> float:
    path = INVEST_DIR / "irrevocable_trust_ubs.csv"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header_idx = next(i for i, line in enumerate(lines) if line.startswith("ACCOUNT NUMBER,"))
    reader = csv.DictReader(lines[header_idx:])
    total = 0.0
    for row in reader:
        total += parse_money_to_float(row.get("VALUE"))
    return total


def extract_vanguard_trust_value() -> float:
    path = INVEST_DIR / "irrevocable_trust_vanguard.csv"
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    header_idx = next(i for i, line in enumerate(lines) if line.startswith('"Account","Symbol/CUSIP"'))
    reader = csv.DictReader(lines[header_idx:])
    total = 0.0
    value_col = "Market value as of 02/27/2026 11:29 AM, ET"
    for row in reader:
        total += parse_money_to_float(row.get(value_col))
    return total


def build_ghostfolio_specs() -> list[dict]:
    roth = extract_roth_value()
    solo = extract_solo_401k_value()
    ed529 = extract_529_value()
    ubs = extract_ubs_value()
    vanguard = extract_vanguard_trust_value()

    return [
        {
            "name": "Trust - UBS",
            "balance": round(ubs, 2),
            "currency": "USD",
            "entity": "trust",
            "tax_wrapper": "taxable",
            "account_type": "trust_irrevocable",
            "comment": "source:irrevocable_trust_ubs.csv as_of:2026-02-27 ingestion_state:orders_deferred",
        },
        {
            "name": "Trust - Vanguard",
            "balance": round(vanguard, 2),
            "currency": "USD",
            "entity": "trust",
            "tax_wrapper": "taxable",
            "account_type": "trust_irrevocable",
            "comment": "source:irrevocable_trust_vanguard.csv as_of:2026-02-27 ingestion_state:orders_deferred",
        },
        {
            "name": "Personal - Wealthfront Roth IRA",
            "balance": round(roth, 2),
            "currency": "USD",
            "entity": "personal",
            "tax_wrapper": "tax_exempt",
            "account_type": "roth_ira",
            "comment": "source:roth_ira_wealthfront.pdf as_of:2026-01-31 ingestion_state:orders_deferred",
        },
        {
            "name": "Personal - Solo 401k",
            "balance": round(solo, 2),
            "currency": "USD",
            "entity": "personal",
            "tax_wrapper": "tax_deferred",
            "account_type": "solo_401k",
            "comment": "source:solo_401k.pdf as_of:2026-02-26 ingestion_state:orders_deferred",
        },
        {
            "name": "Personal - Fidelity 529",
            "balance": round(ed529, 2),
            "currency": "USD",
            "entity": "personal",
            "tax_wrapper": "tax_exempt",
            "account_type": "529",
            "comment": "source:529_fidelity.csv as_of:2026-02-27 ingestion_state:orders_deferred",
        },
    ]


def summarize(transactions: Iterable[NormalizedTxn]) -> dict:
    txns = list(transactions)
    by_account = Counter(tx.account_key for tx in txns)
    by_category = Counter(tx.category_name for tx in txns)
    by_file = Counter(tx.source_file for tx in txns)

    date_min = min(tx.date_yyyy_mm_dd for tx in txns) if txns else None
    date_max = max(tx.date_yyyy_mm_dd for tx in txns) if txns else None
    total_cents = sum(tx.amount_cents for tx in txns)

    return {
        "rows_total": len(txns),
        "date_min": date_min,
        "date_max": date_max,
        "net_total": round(total_cents / 100.0, 2),
        "rows_by_account_key": dict(by_account),
        "rows_by_category": dict(by_category.most_common()),
        "rows_by_source_file": dict(by_file),
    }


def main() -> None:
    all_txns: list[NormalizedTxn] = []
    all_txns.extend(load_barclays())
    all_txns.extend(load_chase())
    all_txns.extend(load_citizens())
    all_txns.extend(load_everbank())

    all_txns.sort(key=lambda tx: (tx.account_key, tx.date_yyyy_mm_dd, tx.source_file, tx.source_row))

    tx_by_account: dict[str, list[dict]] = defaultdict(list)
    for tx in all_txns:
        tx_by_account[tx.account_key].append(tx.as_actual_payload())

    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "actual": {
            "accounts": ACTUAL_ACCOUNTS,
            "account_ids_by_key": ACTUAL_ACCOUNT_IDS_BY_KEY,
            "category_groups": CATEGORY_GROUPS,
            "transactions_by_account_key": tx_by_account,
        },
        "ghostfolio": {
            "accounts": build_ghostfolio_specs(),
            "delete_default_account_name": "My Account",
        },
    }

    summary = {
        "generated_at": payload["generated_at"],
        "actual_summary": summarize(all_txns),
        "ghostfolio_accounts": payload["ghostfolio"]["accounts"],
    }

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote payload: {OUTPUT_PATH}")
    print(f"Wrote summary: {SUMMARY_PATH}")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
