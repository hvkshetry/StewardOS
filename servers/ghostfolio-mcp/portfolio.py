from __future__ import annotations

from typing import Any

from accounts import (
    _get_accounts_with_classification,
)
from client import (
    ScopeAccountType,
    VALID_ACCOUNT_TYPES,
    VALID_ENTITY,
    VALID_OWNER,
    VALID_RANGES,
    VALID_WRAPPER,
    _clean_operation,
    _failure,
    _from_request,
    _merge_params,
    _now_iso,
    _request,
    _resolve_symbol_context,
    _success,
    _to_float,
)
from stewardos_lib.portfolio_snapshot import (
    cash_position_symbol,
    content_addressed_snapshot_id,
    normalized_position_symbol,
)


def _normalize_scope_list(scope_account_types: list[ScopeAccountType] | None) -> set[str] | None:
    if scope_account_types is None:
        return None
    if not isinstance(scope_account_types, list):
        raise ValueError("scope_account_types must be a list of account type codes.")

    cleaned = [str(s).strip().lower() for s in scope_account_types if str(s).strip()]
    if not cleaned:
        return None

    invalid = sorted({value for value in cleaned if value not in VALID_ACCOUNT_TYPES})
    if invalid:
        allowed = ", ".join(sorted(VALID_ACCOUNT_TYPES))
        raise ValueError(
            f"scope_account_types contains invalid values: {', '.join(invalid)}. "
            f"Allowed values: {allowed}"
        )

    return set(cleaned)


def _matches_scope(
    classification: dict[str, Any],
    scope_entity: str,
    scope_wrapper: str,
    scope_account_types: set[str] | None,
    scope_owner: str = "all",
) -> bool:
    entity = classification.get("entity")
    wrapper = classification.get("tax_wrapper")
    account_type = classification.get("account_type")
    owner_person = classification.get("owner_person")

    if scope_entity != "all" and entity != scope_entity:
        return False
    if scope_wrapper != "all" and wrapper != scope_wrapper:
        return False
    if scope_account_types is not None and account_type not in scope_account_types:
        return False
    if scope_owner != "all" and owner_person != scope_owner:
        return False
    return True


def _extract_holding_account_id(holding: dict[str, Any]) -> str | None:
    for key in ("accountId", "account_id", "account"):
        value = holding.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("id") or value.get("accountId")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _holding_symbol(row: dict[str, Any]) -> str:
    return normalized_position_symbol(row)


def _holding_value(row: dict[str, Any]) -> float:
    for key in ("valueInBaseCurrency", "value", "marketValue", "currentValue"):
        value = _to_float(row.get(key), default=float("nan"))
        if value == value:
            return value
    quantity = _to_float(row.get("quantity", row.get("shares", 0.0)), 0.0)
    market_price = _to_float(row.get("marketPrice", row.get("price", 0.0)), 0.0)
    return quantity * market_price


def _extract_activity_account_id(activity: dict[str, Any]) -> str | None:
    for key in ("accountId", "account_id", "account"):
        value = activity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            nested = value.get("id") or value.get("accountId")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return None


def _extract_activity_symbol(activity: dict[str, Any]) -> str:
    for key in ("symbol", "ticker"):
        value = activity.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    profile = activity.get("SymbolProfile") or activity.get("symbolProfile")
    if isinstance(profile, dict):
        symbol = profile.get("symbol")
        if isinstance(symbol, str) and symbol.strip():
            return symbol.strip().upper()
    return ""


def _extract_activity_data_source(activity: dict[str, Any]) -> str | None:
    profile = activity.get("SymbolProfile") or activity.get("symbolProfile")
    if isinstance(profile, dict):
        source = profile.get("dataSource")
        if isinstance(source, str) and source.strip():
            return source.strip().upper()
    source = activity.get("dataSource")
    if isinstance(source, str) and source.strip():
        return source.strip().upper()
    return None


def _activity_trade_sign(activity_type: str, quantity: float) -> int:
    t = (activity_type or "").strip().upper()
    if t in {"SELL", "WITHDRAWAL", "CASH_OUT", "DELIVERY_OUT"}:
        return -1
    if t in {"BUY", "DEPOSIT", "CASH_IN", "DELIVERY_IN"}:
        return 1
    if quantity < 0:
        return -1
    return 1


def _build_holdings_symbol_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = _holding_symbol(row)
        if not symbol:
            continue
        entry = out.setdefault(
            symbol,
            {
                "value": 0.0,
                "quantity": 0.0,
                "assetClass": row.get("assetClass"),
                "assetSubClass": row.get("assetSubClass"),
                "currency": row.get("currency"),
                "dataSource": row.get("dataSource"),
                "marketPrice": 0.0,
            },
        )
        entry["value"] += max(_holding_value(row), 0.0)
        entry["quantity"] += max(_to_float(row.get("quantity", row.get("shares", 0.0)), 0.0), 0.0)
        market_price = _to_float(row.get("marketPrice"), 0.0)
        if market_price > 0:
            entry["marketPrice"] = market_price
    for payload in out.values():
        if payload.get("marketPrice", 0.0) <= 0:
            qty = _to_float(payload.get("quantity"), 0.0)
            value = _to_float(payload.get("value"), 0.0)
            payload["marketPrice"] = (value / qty) if qty > 0 else 0.0
    return out


def _position_value_by_symbol(positions: list[dict[str, Any]]) -> dict[str, float]:
    values: dict[str, float] = {}
    for row in positions:
        symbol_key = _holding_symbol(row)
        if not symbol_key:
            continue
        values[symbol_key] = values.get(symbol_key, 0.0) + max(_holding_value(row), 0.0)
    return values


def _coverage_metrics(
    holdings_symbol_map: dict[str, dict[str, Any]],
    all_positions: list[dict[str, Any]],
    scoped_positions: list[dict[str, Any]],
) -> dict[str, float]:
    all_position_values = _position_value_by_symbol(all_positions)
    scoped_position_values = _position_value_by_symbol(scoped_positions)

    covered_value = 0.0
    scoped_holdings_total_value = 0.0
    for symbol_key, payload in holdings_symbol_map.items():
        holdings_value = max(_to_float(payload.get("value"), 0.0), 0.0)
        if holdings_value <= 0:
            continue
        scoped_position_value = scoped_position_values.get(symbol_key, 0.0)
        if scoped_position_value <= 0:
            continue
        global_position_value = all_position_values.get(symbol_key, 0.0)
        if global_position_value > 0:
            scoped_share = min(1.0, scoped_position_value / global_position_value)
            scoped_holdings_value = holdings_value * scoped_share
        else:
            scoped_holdings_value = holdings_value

        scoped_holdings_total_value += scoped_holdings_value
        covered_value += min(scoped_holdings_value, scoped_position_value)

    coverage_pct = (covered_value / scoped_holdings_total_value) if scoped_holdings_total_value > 0 else 1.0
    return {
        "account_aware_coverage_pct": coverage_pct,
        "holdings_total_value": scoped_holdings_total_value,
        "reconstructed_total_value": sum(max(_holding_value(row), 0.0) for row in scoped_positions),
    }


async def _handle_portfolio_capabilities(tool, op, valid):
    return _success(
        tool,
        op,
        "N/A",
        "N/A",
        {
            "operations": valid,
            "snapshot_contracts": {
                "snapshot": "legacy scoped holdings snapshot (accountId may be missing)",
                "snapshot_v2": "account-aware snapshot reconstructed from /api/v1/order + /api/v1/portfolio/holdings",
            },
            "strict_scope_min_coverage_pct": 0.99,
        },
    )


async def _handle_portfolio_summary(tool, op, params):
    result = await _request("GET", "/api/v1/portfolio/details", params=params)
    if not result.get("ok"):
        return _from_request(tool, op, "GET", "/api/v1/portfolio/details", result)

    body = result.get("body")
    if isinstance(body, dict) and isinstance(body.get("summary"), dict):
        transformed = {
            "summary": body.get("summary"),
            "createdAt": body.get("createdAt"),
            "accountCount": len(body.get("accounts", {})) if isinstance(body.get("accounts"), dict) else None,
            "holdingCount": len(body.get("holdings", {})) if isinstance(body.get("holdings"), dict) else None,
        }
        return _success(tool, op, "GET", "/api/v1/portfolio/details", transformed)

    return _success(tool, op, "GET", "/api/v1/portfolio/details", body)


async def _handle_portfolio_details(tool, op, params):
    result = await _request("GET", "/api/v1/portfolio/details", params=params)
    return _from_request(tool, op, "GET", "/api/v1/portfolio/details", result)


async def _handle_portfolio_holdings(tool, op, params):
    result = await _request("GET", "/api/v1/portfolio/holdings", params=params)
    return _from_request(tool, op, "GET", "/api/v1/portfolio/holdings", result)


async def _handle_portfolio_holding(tool, op, symbol, data_source):
    if not symbol:
        return _failure(tool, op, "GET", "/api/v1/portfolio/holding/:dataSource/:symbol", "invalid_input", "symbol is required.")
    resolved = await _resolve_symbol_context(symbol, data_source)
    if isinstance(resolved, str):
        return _failure(tool, op, "GET", "/api/v1/portfolio/holding/:dataSource/:symbol", "symbol_resolution_error", resolved)
    resolved_source, resolved_symbol = resolved
    result = await _request("GET", f"/api/v1/portfolio/holding/{resolved_source}/{resolved_symbol}")
    return _from_request(tool, op, "GET", f"/api/v1/portfolio/holding/{resolved_source}/{resolved_symbol}", result)


async def _handle_portfolio_performance(tool, op, range, params):
    if range not in VALID_RANGES:
        return _failure(
            tool,
            op,
            "GET",
            "/api/v2/portfolio/performance",
            "invalid_input",
            f"Invalid range '{range}'. Valid ranges: {', '.join(sorted(VALID_RANGES))}",
        )
    req_params = _merge_params(params, {"range": range})
    result = await _request("GET", "/api/v2/portfolio/performance", params=req_params)
    return _from_request(tool, op, "GET", "/api/v2/portfolio/performance", result)


async def _handle_portfolio_dividends(tool, op, range, params):
    if range not in VALID_RANGES:
        return _failure(
            tool,
            op,
            "GET",
            "/api/v1/portfolio/dividends",
            "invalid_input",
            f"Invalid range '{range}'. Valid ranges: {', '.join(sorted(VALID_RANGES))}",
        )
    req_params = _merge_params(params, {"range": range})
    result = await _request("GET", "/api/v1/portfolio/dividends", params=req_params)
    if (not result.get("ok")) and result.get("status_code") == 500:
        return _success(
            tool,
            op,
            "GET",
            "/api/v1/portfolio/dividends",
            {
                "dividends": [],
                "range": range,
                "note": "Upstream returned HTTP 500; normalized to empty dividends payload.",
            },
        )
    return _from_request(tool, op, "GET", "/api/v1/portfolio/dividends", result)


async def _handle_portfolio_investments(tool, op, range, params):
    if range not in VALID_RANGES:
        return _failure(
            tool,
            op,
            "GET",
            "/api/v1/portfolio/investments",
            "invalid_input",
            f"Invalid range '{range}'. Valid ranges: {', '.join(sorted(VALID_RANGES))}",
        )
    req_params = _merge_params(params, {"range": range})
    result = await _request("GET", "/api/v1/portfolio/investments", params=req_params)
    return _from_request(tool, op, "GET", "/api/v1/portfolio/investments", result)


async def _handle_portfolio_report(tool, op):
    result = await _request("GET", "/api/v1/portfolio/report")
    return _from_request(tool, op, "GET", "/api/v1/portfolio/report", result)


async def _handle_portfolio_set_holding_tags(tool, op, symbol, data_source, data):
    if not symbol:
        return _failure(tool, op, "PUT", "/api/v1/portfolio/holding/:dataSource/:symbol/tags", "invalid_input", "symbol is required.")
    resolved = await _resolve_symbol_context(symbol, data_source)
    if isinstance(resolved, str):
        return _failure(tool, op, "PUT", "/api/v1/portfolio/holding/:dataSource/:symbol/tags", "symbol_resolution_error", resolved)
    resolved_source, resolved_symbol = resolved
    result = await _request(
        "PUT",
        f"/api/v1/portfolio/holding/{resolved_source}/{resolved_symbol}/tags",
        json=data,
    )
    return _from_request(
        tool,
        op,
        "PUT",
        f"/api/v1/portfolio/holding/{resolved_source}/{resolved_symbol}/tags",
        result,
    )


async def _handle_portfolio_snapshot_v2(
    tool, op, range, params, scope_entity, scope_wrapper,
    scope_account_types, scope_owner, strict,
):
    if range not in VALID_RANGES:
        return _failure(
            tool, op, "GET", "MULTI", "invalid_input",
            f"Invalid range '{range}'. Valid ranges: {', '.join(sorted(VALID_RANGES))}",
        )

    scope_entity = scope_entity.strip().lower()
    scope_wrapper = scope_wrapper.strip().lower()
    scope_owner = scope_owner.strip().lower() if isinstance(scope_owner, str) else "all"
    try:
        scope_types = _normalize_scope_list(scope_account_types)
    except ValueError as exc:
        return _failure(tool, op, "GET", "MULTI", "invalid_input", str(exc))

    if scope_entity not in {"all", *VALID_ENTITY}:
        return _failure(tool, op, "GET", "MULTI", "invalid_input", f"Invalid scope_entity '{scope_entity}'.")
    if scope_wrapper not in {"all", *VALID_WRAPPER}:
        return _failure(tool, op, "GET", "MULTI", "invalid_input", f"Invalid scope_wrapper '{scope_wrapper}'.")
    if scope_owner not in {"all", *VALID_OWNER}:
        return _failure(tool, op, "GET", "MULTI", "invalid_input", f"Invalid scope_owner '{scope_owner}'. Valid values: all, {', '.join(sorted(VALID_OWNER))}.")

    account_payload = await _get_accounts_with_classification(strict=False)
    if not account_payload.get("ok") and account_payload.get("error"):
        return _failure(
            tool, op, "GET", "/api/v1/account",
            account_payload.get("error", {}).get("code", "request_failed"),
            account_payload.get("error", {}).get("message", "Failed to load accounts."),
            details={"status_code": account_payload.get("status_code")},
        )
    if strict and account_payload.get("invalid_accounts"):
        return _failure(
            tool, op, "GET", "/api/v1/account",
            "taxonomy_validation_failed",
            "Account taxonomy validation failed in strict mode.",
            details={
                "summary": account_payload.get("summary", {}),
                "invalid_accounts": account_payload.get("invalid_accounts", []),
            },
        )

    accounts = account_payload.get("accounts", [])
    account_by_id = {
        account.get("account_id"): account
        for account in accounts
        if isinstance(account, dict) and isinstance(account.get("account_id"), str)
    }
    in_scope_account_ids = {
        account.get("account_id")
        for account in accounts
        if isinstance(account.get("account_id"), str)
        and _matches_scope(account.get("classification", {}), scope_entity, scope_wrapper, scope_types, scope_owner)
    }

    order_result = await _request("GET", "/api/v1/order", params=params)
    if not order_result.get("ok"):
        return _from_request(tool, op, "GET", "/api/v1/order", order_result)
    order_body = order_result.get("body", {})
    activities = []
    if isinstance(order_body, dict) and isinstance(order_body.get("activities"), list):
        activities = [row for row in order_body.get("activities", []) if isinstance(row, dict)]
    elif isinstance(order_body, dict) and isinstance(order_body.get("items"), list):
        activities = [row for row in order_body.get("items", []) if isinstance(row, dict)]

    holdings_result = await _request("GET", "/api/v1/portfolio/holdings", params=params)
    if not holdings_result.get("ok"):
        return _from_request(tool, op, "GET", "/api/v1/portfolio/holdings", holdings_result)
    holdings_body = holdings_result.get("body", {})
    holdings_rows: list[dict[str, Any]] = []
    if isinstance(holdings_body, dict) and isinstance(holdings_body.get("holdings"), list):
        holdings_rows = [row for row in holdings_body.get("holdings", []) if isinstance(row, dict)]
    elif isinstance(holdings_body, list):
        holdings_rows = [row for row in holdings_body if isinstance(row, dict)]
    holdings_symbol_map = _build_holdings_symbol_map(holdings_rows)

    position_map: dict[tuple[str, str], dict[str, Any]] = {}
    skipped_missing = 0
    skipped_zero_quantity = 0

    for activity in sorted(
        activities,
        key=lambda row: (
            str(row.get("date") or row.get("createdAt") or row.get("updatedAt") or ""),
            str(row.get("id") or ""),
        ),
    ):
        if bool(activity.get("isDraft")):
            continue
        account_id = _extract_activity_account_id(activity)
        symbol_value = _extract_activity_symbol(activity)
        if not account_id or not symbol_value:
            skipped_missing += 1
            continue

        raw_quantity = _to_float(activity.get("quantity"), 0.0)
        if abs(raw_quantity) <= 1e-12:
            skipped_zero_quantity += 1
            continue

        activity_type = str(activity.get("type", "BUY")).strip().upper()
        sign = _activity_trade_sign(activity_type, raw_quantity)
        quantity = abs(raw_quantity)
        quantity_delta = quantity * sign

        trade_value = _to_float(activity.get("valueInBaseCurrency"), float("nan"))
        if trade_value != trade_value:
            trade_value = _to_float(activity.get("value"), float("nan"))
        if trade_value != trade_value:
            unit_price_fallback = _to_float(
                activity.get("unitPriceInAssetProfileCurrency"),
                _to_float(activity.get("unitPrice"), 0.0),
            )
            trade_value = abs(quantity * unit_price_fallback)
        trade_value = max(trade_value, 0.0)

        fee = max(
            0.0,
            _to_float(
                activity.get("feeInBaseCurrency"),
                _to_float(activity.get("fee"), 0.0),
            ),
        )
        unit_price = _to_float(
            activity.get("unitPriceInAssetProfileCurrency"),
            _to_float(activity.get("unitPrice"), 0.0),
        )

        key = (account_id, symbol_value)
        entry = position_map.setdefault(
            key,
            {
                "accountId": account_id,
                "symbol": symbol_value,
                "quantity": 0.0,
                "cost": 0.0,
                "last_trade_price": 0.0,
                "currency": activity.get("currency") or "USD",
                "dataSource": _extract_activity_data_source(activity),
            },
        )

        if quantity_delta > 0:
            entry["quantity"] += quantity_delta
            entry["cost"] += trade_value + fee
        else:
            if entry["quantity"] <= 1e-12:
                continue
            sell_qty = min(entry["quantity"], abs(quantity_delta))
            avg_cost = (entry["cost"] / entry["quantity"]) if entry["quantity"] > 0 else 0.0
            entry["quantity"] -= sell_qty
            if entry["quantity"] <= 1e-12:
                entry["quantity"] = 0.0
                entry["cost"] = 0.0
            else:
                entry["cost"] = max(0.0, entry["cost"] - (avg_cost * sell_qty))

        if unit_price > 0:
            entry["last_trade_price"] = unit_price

    positions: list[dict[str, Any]] = []
    for (account_id, symbol_value), entry in position_map.items():
        quantity = max(_to_float(entry.get("quantity"), 0.0), 0.0)
        if quantity <= 1e-9:
            continue
        holdings_meta = holdings_symbol_map.get(symbol_value, {})
        market_price = _to_float(holdings_meta.get("marketPrice"), 0.0)
        if market_price <= 0:
            market_price = max(_to_float(entry.get("last_trade_price"), 0.0), 0.0)
        value = quantity * market_price
        cost = max(_to_float(entry.get("cost"), 0.0), 0.0)
        account = account_by_id.get(account_id, {})
        classification = account.get("classification", {}) if isinstance(account, dict) else {}
        positions.append(
            {
                "accountId": account_id,
                "symbol": symbol_value,
                "quantity": quantity,
                "investment": cost,
                "costBasisInBaseCurrency": cost,
                "marketPrice": market_price,
                "valueInBaseCurrency": value,
                "currency": holdings_meta.get("currency") or entry.get("currency") or "USD",
                "assetClass": holdings_meta.get("assetClass"),
                "assetSubClass": holdings_meta.get("assetSubClass"),
                "dataSource": holdings_meta.get("dataSource") or entry.get("dataSource"),
                "entity": classification.get("entity"),
                "tax_wrapper": classification.get("tax_wrapper"),
                "account_type": classification.get("account_type"),
            }
        )

    for account in accounts:
        if not isinstance(account, dict):
            continue
        account_id = account.get("account_id")
        if not isinstance(account_id, str) or not account_id:
            continue
        balance = _to_float(account.get("balance"), 0.0)
        if abs(balance) <= 1e-9:
            continue
        classification = account.get("classification", {})
        positions.append(
            {
                "accountId": account_id,
                "symbol": cash_position_symbol(account.get("currency")),
                "quantity": balance,
                "investment": balance,
                "costBasisInBaseCurrency": balance,
                "marketPrice": 1.0,
                "valueInBaseCurrency": balance,
                "currency": account.get("currency") or "USD",
                "assetClass": "LIQUIDITY",
                "assetSubClass": "CASH",
                "dataSource": "MANUAL",
                "entity": classification.get("entity"),
                "tax_wrapper": classification.get("tax_wrapper"),
                "account_type": classification.get("account_type"),
            }
        )

    holdings_total_value = sum(max(_holding_value(row), 0.0) for row in holdings_rows)
    reconstructed_total_value = sum(max(_holding_value(row), 0.0) for row in positions)
    reconciliation_drift_pct = (
        abs(reconstructed_total_value - holdings_total_value) / holdings_total_value
        if holdings_total_value > 0
        else 0.0
    )

    is_scoped = (
        scope_entity != "all"
        or scope_wrapper != "all"
        or scope_owner != "all"
        or (scope_types is not None and len(scope_types) > 0)
    )
    included_positions: list[dict[str, Any]] = []
    excluded_count = 0
    for row in positions:
        if not is_scoped:
            included_positions.append(row)
            continue
        account_id = _extract_holding_account_id(row)
        if account_id in in_scope_account_ids:
            included_positions.append(row)
        else:
            excluded_count += 1

    min_coverage_pct = 0.99
    coverage = _coverage_metrics(holdings_symbol_map, positions, included_positions if is_scoped else positions)
    coverage_pct = coverage["account_aware_coverage_pct"]
    if strict and is_scoped and coverage_pct < min_coverage_pct:
        return _failure(
            tool, op, "GET", "MULTI", "strict_scope_error",
            (
                f"Account-aware coverage is {coverage_pct:.2%}, below strict minimum "
                f"{min_coverage_pct:.2%}."
            ),
            details={"coverage_pct": coverage_pct, "minimum_required_pct": min_coverage_pct},
        )

    warnings: list[str] = []
    if skipped_missing > 0:
        warnings.append(f"{skipped_missing} activities were skipped due to missing accountId or symbol.")
    if skipped_zero_quantity > 0:
        warnings.append(f"{skipped_zero_quantity} zero-quantity activities were skipped.")
    if excluded_count > 0:
        warnings.append(f"{excluded_count} positions were excluded by account scope.")
    if coverage_pct < min_coverage_pct:
        warnings.append(
            f"Account-aware coverage is {coverage_pct:.2%}, below target {min_coverage_pct:.2%}."
        )

    payload = {
        "snapshot_id": content_addressed_snapshot_id(
            positions=positions,
            accounts=[account for account in accounts if isinstance(account, dict)],
            holdings=holdings_rows,
            prefix="snap_v2",
        ),
        "as_of": _now_iso(),
        "scope": {
            "entity": scope_entity,
            "tax_wrapper": scope_wrapper,
            "account_types": sorted(list(scope_types)) if scope_types is not None else "all",
            "strict": strict,
        },
        "classification_summary": account_payload.get("summary", {}),
        "accounts": accounts,
        "positions": {
            "rows": included_positions,
            "count": len(included_positions),
            "excluded_count": excluded_count,
        },
        "coverage": {
            "account_aware_coverage_pct": coverage_pct,
            "reconciliation_drift_pct": reconciliation_drift_pct,
            "holdings_total_value": coverage["holdings_total_value"] if is_scoped else holdings_total_value,
            "reconstructed_total_value": coverage["reconstructed_total_value"] if is_scoped else reconstructed_total_value,
        },
        "warnings": warnings,
        "provenance": {
            "position_sources": ["ghostfolio:/api/v1/order", "ghostfolio:/api/v1/portfolio/holdings"],
            "account_source": "ghostfolio:/api/v1/account",
        },
    }
    return _success(tool, op, "GET", "MULTI", payload)


async def _handle_portfolio_snapshot(
    tool, op, range, params, scope_entity, scope_wrapper,
    scope_account_types, scope_owner, strict,
):
    if range not in VALID_RANGES:
        return _failure(
            tool, op, "GET", "MULTI", "invalid_input",
            f"Invalid range '{range}'. Valid ranges: {', '.join(sorted(VALID_RANGES))}",
        )

    scope_entity = scope_entity.strip().lower()
    scope_wrapper = scope_wrapper.strip().lower()
    scope_owner = scope_owner.strip().lower() if isinstance(scope_owner, str) else "all"
    try:
        scope_types = _normalize_scope_list(scope_account_types)
    except ValueError as exc:
        return _failure(tool, op, "GET", "MULTI", "invalid_input", str(exc))

    if scope_entity not in {"all", *VALID_ENTITY}:
        return _failure(tool, op, "GET", "MULTI", "invalid_input", f"Invalid scope_entity '{scope_entity}'.")
    if scope_wrapper not in {"all", *VALID_WRAPPER}:
        return _failure(tool, op, "GET", "MULTI", "invalid_input", f"Invalid scope_wrapper '{scope_wrapper}'.")
    if scope_owner not in {"all", *VALID_OWNER}:
        return _failure(tool, op, "GET", "MULTI", "invalid_input", f"Invalid scope_owner '{scope_owner}'. Valid values: all, {', '.join(sorted(VALID_OWNER))}.")

    account_payload = await _get_accounts_with_classification(strict=False)
    if not account_payload.get("ok") and account_payload.get("error"):
        return _failure(
            tool, op, "GET", "/api/v1/account",
            account_payload.get("error", {}).get("code", "request_failed"),
            account_payload.get("error", {}).get("message", "Failed to load accounts."),
            details={"status_code": account_payload.get("status_code")},
        )
    if strict and account_payload.get("invalid_accounts"):
        return _failure(
            tool, op, "GET", "/api/v1/account",
            "taxonomy_validation_failed",
            "Account taxonomy validation failed in strict mode.",
            details={
                "summary": account_payload.get("summary", {}),
                "invalid_accounts": account_payload.get("invalid_accounts", []),
            },
        )

    accounts = account_payload.get("accounts", [])
    in_scope_account_ids = {
        account.get("account_id")
        for account in accounts
        if isinstance(account.get("account_id"), str)
        and _matches_scope(account.get("classification", {}), scope_entity, scope_wrapper, scope_types, scope_owner)
    }

    holdings_result = await _request("GET", "/api/v1/portfolio/holdings", params=params)
    if not holdings_result.get("ok"):
        return _from_request(tool, op, "GET", "/api/v1/portfolio/holdings", holdings_result)

    raw_holdings = holdings_result.get("body", {})
    rows: list[dict[str, Any]] = []
    if isinstance(raw_holdings, dict) and isinstance(raw_holdings.get("holdings"), list):
        rows = [r for r in raw_holdings.get("holdings", []) if isinstance(r, dict)]
    elif isinstance(raw_holdings, list):
        rows = [r for r in raw_holdings if isinstance(r, dict)]

    is_scoped = (
        scope_entity != "all"
        or scope_wrapper != "all"
        or scope_owner != "all"
        or (scope_types is not None and len(scope_types) > 0)
    )

    included: list[dict[str, Any]] = []
    excluded_count = 0
    unscoped_count = 0
    inferred_count = 0
    scoped_known_accounts = {
        a.get("account_id")
        for a in accounts
        if isinstance(a.get("account_id"), str)
    }
    can_infer_single_account_scope = (
        is_scoped
        and len(in_scope_account_ids) == 1
        and len(scoped_known_accounts) == 1
    )

    for row in rows:
        if not is_scoped:
            included.append(row)
            continue

        account_id = _extract_holding_account_id(row)
        if account_id is None:
            if can_infer_single_account_scope:
                included.append(row)
                inferred_count += 1
                continue
            unscoped_count += 1
            continue

        if account_id in in_scope_account_ids:
            included.append(row)
        else:
            excluded_count += 1

    if strict and is_scoped and unscoped_count > 0:
        return _failure(
            tool, op, "GET", "/api/v1/portfolio/holdings", "strict_scope_error",
            (
                f"{unscoped_count} holdings had no account identifier and could not "
                "be scoped in strict mode."
            ),
        )

    warnings: list[str] = []
    if inferred_count > 0:
        warnings.append(
            f"{inferred_count} holdings missing account identifier were included by single-account scope inference."
        )
    if is_scoped and unscoped_count > 0:
        warnings.append(
            f"{unscoped_count} holdings had no account identifier and could not be scoped."
        )

    details_result = await _request("GET", "/api/v1/portfolio/details", params=params)
    if not details_result.get("ok"):
        return _from_request(tool, op, "GET", "/api/v1/portfolio/details", details_result)

    perf_params = _merge_params(params, {"range": range})
    perf_result = await _request("GET", "/api/v2/portfolio/performance", params=perf_params)
    if not perf_result.get("ok"):
        return _from_request(tool, op, "GET", "/api/v2/portfolio/performance", perf_result)

    payload = {
        "asof": _now_iso(),
        "scope": {
            "entity": scope_entity,
            "tax_wrapper": scope_wrapper,
            "account_types": sorted(list(scope_types)) if scope_types is not None else "all",
            "strict": strict,
        },
        "classification_summary": account_payload.get("summary", {}),
        "accounts": accounts,
        "positions": {
            "holdings": included,
            "count": len(included),
            "excluded_holdings_count": excluded_count,
            "classification_warnings": warnings,
        },
        "portfolio_details": details_result.get("body"),
        "portfolio_performance": perf_result.get("body"),
    }
    return _success(tool, op, "GET", "MULTI", payload)


def register_portfolio_tools(mcp):
    @mcp.tool()
    async def portfolio(
        operation: str,
        data_source: str | None = None,
        symbol: str | None = None,
        range: str = "1y",
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        scope_entity: str = "all",
        scope_wrapper: str = "all",
        scope_account_types: list[ScopeAccountType] | None = None,
        scope_owner: str = "all",
        strict: bool = False,
    ) -> dict[str, Any]:
        """Consolidated portfolio operations (state, performance, scoped snapshot, tag updates)."""
        tool = "portfolio"
        op = _clean_operation(operation)
        valid = [
            "capabilities",
            "summary",
            "details",
            "holdings",
            "holding",
            "performance",
            "dividends",
            "investments",
            "report",
            "set_holding_tags",
            "snapshot",
            "snapshot_v2",
        ]
        if op not in valid:
            return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

        params = params or {}
        data = data or {}

        if op == "capabilities":
            return await _handle_portfolio_capabilities(tool, op, valid)
        if op == "summary":
            return await _handle_portfolio_summary(tool, op, params)
        if op == "details":
            return await _handle_portfolio_details(tool, op, params)
        if op == "holdings":
            return await _handle_portfolio_holdings(tool, op, params)
        if op == "holding":
            return await _handle_portfolio_holding(tool, op, symbol, data_source)
        if op == "performance":
            return await _handle_portfolio_performance(tool, op, range, params)
        if op == "dividends":
            return await _handle_portfolio_dividends(tool, op, range, params)
        if op == "investments":
            return await _handle_portfolio_investments(tool, op, range, params)
        if op == "report":
            return await _handle_portfolio_report(tool, op)
        if op == "set_holding_tags":
            return await _handle_portfolio_set_holding_tags(tool, op, symbol, data_source, data)
        if op == "snapshot_v2":
            return await _handle_portfolio_snapshot_v2(
                tool, op, range, params, scope_entity, scope_wrapper,
                scope_account_types, scope_owner, strict,
            )
        if op == "snapshot":
            return await _handle_portfolio_snapshot(
                tool, op, range, params, scope_entity, scope_wrapper,
                scope_account_types, scope_owner, strict,
            )

        return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")
