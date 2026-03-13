from __future__ import annotations

import json
import os
import re
from typing import Any

from client import (
    ACCOUNT_TAG_MAP_ENV,
    ACCOUNT_UPDATE_REQUIRED_FIELDS,
    LEGACY_TAXONOMY_TAG_KEYS,
    TAXONOMY_TAG_KEYS,
    VALID_ACCOUNT_TYPES,
    VALID_COMP_PLANS,
    VALID_ENTITY,
    VALID_OWNER,
    VALID_WRAPPER,
    _clean_operation,
    _failure,
    _from_request,
    _request,
    _success,
)


def _load_env_account_tag_map() -> dict[str, list[str]]:
    raw = os.getenv(ACCOUNT_TAG_MAP_ENV, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for key, value in parsed.items():
        if not isinstance(key, str):
            continue
        if isinstance(value, list):
            tags = [str(v).strip().lower() for v in value if str(v).strip()]
            normalized[key] = tags
    return normalized


def _parse_comment_tags(comment: str | None) -> list[str]:
    if not comment:
        return []
    parts = re.split(r"[;,\s]+", comment)
    return [p.strip().lower() for p in parts if ":" in p.strip()]


def _strip_taxonomy_tokens(comment: str | None) -> str:
    if not isinstance(comment, str):
        return ""
    raw_tokens = re.split(r"\s+", comment.strip())
    kept: list[str] = []
    for token in raw_tokens:
        candidate = token.strip().strip(",;").lower()
        if ":" in candidate:
            key = candidate.split(":", 1)[0]
            if key in TAXONOMY_TAG_KEYS or key in LEGACY_TAXONOMY_TAG_KEYS:
                continue
        kept.append(token)
    return " ".join(kept).strip()


def _build_taxonomy_comment(
    entity: str,
    tax_wrapper: str,
    account_type: str,
    comp_plan: str | None,
    owner_person: str | None = None,
    employer_ticker: str | None = None,
    existing_comment: str | None = None,
    preserve_existing_comment: bool = True,
) -> str:
    taxonomy = f"entity:{entity} tax_wrapper:{tax_wrapper} account_type:{account_type}"
    if comp_plan:
        taxonomy = f"{taxonomy} comp_plan:{comp_plan}"
    if owner_person:
        taxonomy = f"{taxonomy} owner_person:{owner_person}"
    if employer_ticker:
        taxonomy = f"{taxonomy} employer_ticker:{employer_ticker}"
    if not preserve_existing_comment:
        return taxonomy
    preserved = _strip_taxonomy_tokens(existing_comment)
    return f"{preserved} {taxonomy}".strip() if preserved else taxonomy


def _extract_account_record(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict) and isinstance(payload.get("id"), str):
        return payload
    if isinstance(payload, dict):
        nested = payload.get("account")
        if isinstance(nested, dict) and isinstance(nested.get("id"), str):
            return nested
        items = payload.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            if isinstance(items[0].get("id"), str):
                return items[0]
    return None


def _build_account_update_payload(account: dict[str, Any], comment: str) -> dict[str, Any] | str:
    missing = [field for field in ACCOUNT_UPDATE_REQUIRED_FIELDS if field not in account]
    if missing:
        return "Account payload missing required update fields: " + ", ".join(sorted(missing))

    account_id = account.get("id")
    name = account.get("name")
    balance = account.get("balance")
    currency = account.get("currency")
    platform_id = account.get("platformId")

    if not isinstance(account_id, str) or not account_id.strip():
        return "Account field 'id' must be a non-empty string."
    if not isinstance(name, str) or not name.strip():
        return "Account field 'name' must be a non-empty string."
    if not isinstance(currency, str) or not currency.strip():
        return "Account field 'currency' must be a non-empty string."
    if not isinstance(balance, (int, float)):
        return "Account field 'balance' must be numeric."
    if platform_id is not None and not isinstance(platform_id, str):
        return "Account field 'platformId' must be null or string."

    payload: dict[str, Any] = {
        "id": account_id,
        "name": name,
        "balance": balance,
        "currency": currency,
        "platformId": platform_id,
        "comment": comment,
    }

    is_excluded = account.get("isExcluded")
    if isinstance(is_excluded, bool):
        payload["isExcluded"] = is_excluded

    return payload


def _extract_account_id(account: dict[str, Any]) -> str:
    for key in ("id", "accountId", "account_id"):
        value = account.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _extract_account_tags(account: dict[str, Any], env_map: dict[str, list[str]]) -> list[str]:
    tag_set: set[str] = set()

    tags = account.get("tags")
    if isinstance(tags, list):
        for item in tags:
            if isinstance(item, str) and ":" in item:
                tag_set.add(item.strip().lower())
            elif isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and ":" in name:
                    tag_set.add(name.strip().lower())

    comment = account.get("comment")
    if isinstance(comment, str):
        for token in _parse_comment_tags(comment):
            tag_set.add(token)

    account_id = _extract_account_id(account)
    if account_id and account_id in env_map:
        for token in env_map[account_id]:
            if ":" in token:
                tag_set.add(token)

    return sorted(tag_set)


def _classify_account_tags(tags: list[str]) -> dict[str, Any]:
    entity = None
    wrapper = None
    account_type = None
    comp_plan = None
    owner_person = None
    employer_ticker = None
    errors: list[str] = []

    for tag in tags:
        if not isinstance(tag, str) or ":" not in tag:
            continue
        key, value = tag.split(":", 1)
        key = key.strip().lower()
        value = value.strip().lower()
        if key == "entity":
            entity = value
        elif key == "tax_wrapper":
            wrapper = value
        elif key == "account_type":
            account_type = value
        elif key == "comp_plan":
            comp_plan = value
        elif key == "owner_person":
            owner_person = value
        elif key == "employer_ticker":
            employer_ticker = value.upper() if value else None

    if entity not in VALID_ENTITY:
        errors.append("missing_or_invalid_entity_tag")
    if wrapper not in VALID_WRAPPER:
        errors.append("missing_or_invalid_tax_wrapper_tag")
    if account_type not in VALID_ACCOUNT_TYPES:
        errors.append("missing_or_invalid_account_type_tag")
    if comp_plan is not None and comp_plan not in VALID_COMP_PLANS:
        errors.append("invalid_comp_plan_tag")
    if account_type == "equity_comp" and comp_plan not in VALID_COMP_PLANS:
        errors.append("missing_or_invalid_comp_plan_tag_for_equity_comp")
    if owner_person not in VALID_OWNER:
        errors.append("missing_or_invalid_owner_person_tag")
    if account_type == "equity_comp" and not employer_ticker:
        errors.append("missing_or_invalid_employer_ticker_tag_for_equity_comp")

    result: dict[str, Any] = {
        "entity": entity,
        "tax_wrapper": wrapper,
        "account_type": account_type,
        "comp_plan": comp_plan,
        "owner_person": owner_person,
        "valid": len(errors) == 0,
        "errors": errors,
    }
    if employer_ticker:
        result["employer_ticker"] = employer_ticker
    return result


def _classification_summary(accounts: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(accounts)
    invalid = sum(1 for a in accounts if not a.get("classification", {}).get("valid", False))

    by_entity: dict[str, int] = {}
    by_wrapper: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_comp_plan: dict[str, int] = {}
    by_owner_person: dict[str, int] = {}

    for account in accounts:
        c = account.get("classification", {})
        entity = c.get("entity")
        wrapper = c.get("tax_wrapper")
        account_type = c.get("account_type")
        comp_plan = c.get("comp_plan")
        owner_person = c.get("owner_person")
        if isinstance(entity, str):
            by_entity[entity] = by_entity.get(entity, 0) + 1
        if isinstance(wrapper, str):
            by_wrapper[wrapper] = by_wrapper.get(wrapper, 0) + 1
        if isinstance(account_type, str):
            by_type[account_type] = by_type.get(account_type, 0) + 1
        if isinstance(comp_plan, str):
            by_comp_plan[comp_plan] = by_comp_plan.get(comp_plan, 0) + 1
        if isinstance(owner_person, str):
            by_owner_person[owner_person] = by_owner_person.get(owner_person, 0) + 1

    return {
        "total_accounts": total,
        "valid_accounts": total - invalid,
        "invalid_accounts": invalid,
        "by_entity": by_entity,
        "by_tax_wrapper": by_wrapper,
        "by_account_type": by_type,
        "by_comp_plan": by_comp_plan,
        "by_owner_person": by_owner_person,
    }


async def _get_accounts_raw() -> dict[str, Any]:
    result = await _request("GET", "/api/v1/account")
    if not result.get("ok"):
        return {
            "ok": False,
            "error": result.get("error", {}),
            "status_code": result.get("status_code"),
            "accounts": [],
        }

    body = result.get("body")
    accounts: list[dict[str, Any]] = []
    if isinstance(body, dict) and isinstance(body.get("accounts"), list):
        accounts = [a for a in body["accounts"] if isinstance(a, dict)]
    elif isinstance(body, dict) and isinstance(body.get("items"), list):
        accounts = [a for a in body["items"] if isinstance(a, dict)]
    elif isinstance(body, list):
        accounts = [a for a in body if isinstance(a, dict)]

    return {
        "ok": True,
        "accounts": accounts,
    }


async def _get_accounts_with_classification(strict: bool = False) -> dict[str, Any]:
    raw = await _get_accounts_raw()
    if not raw.get("ok"):
        return {
            "ok": False,
            "error": raw.get("error", {}),
            "status_code": raw.get("status_code"),
            "accounts": [],
            "summary": {
                "total_accounts": 0,
                "valid_accounts": 0,
                "invalid_accounts": 0,
            },
            "invalid_accounts": [],
        }

    env_map = _load_env_account_tag_map()
    accounts: list[dict[str, Any]] = []
    invalid_accounts: list[dict[str, Any]] = []

    for account in raw.get("accounts", []):
        account_id = _extract_account_id(account)
        tags = _extract_account_tags(account, env_map)
        classification = _classify_account_tags(tags)
        enriched = {
            **account,
            "account_id": account_id,
            "classification_tags": tags,
            "classification": classification,
        }
        accounts.append(enriched)
        if not classification.get("valid", False):
            invalid_accounts.append(
                {
                    "account_id": account_id,
                    "name": account.get("name"),
                    "errors": classification.get("errors", []),
                    "tags": tags,
                }
            )

    summary = _classification_summary(accounts)
    ok = (not strict) or len(invalid_accounts) == 0

    return {
        "ok": ok,
        "accounts": accounts,
        "summary": summary,
        "invalid_accounts": invalid_accounts,
        "taxonomy": {
            "required_tags": [
                "entity:personal|trust",
                "tax_wrapper:taxable|tax_deferred|tax_exempt",
                "account_type:brokerage|roth_ira|trad_ira|401k|403b|457b|solo_401k|sep_ira|simple_ira|hsa|529|esa|custodial_utma|custodial_ugma|equity_comp|trust_taxable|trust_exempt|trust_irrevocable|trust_revocable|trust_qsst|other",
                "comp_plan:rsu|iso|nso|psu|espp|other (required if account_type:equity_comp)",
                "owner_person:Principal|Spouse|joint",
                "employer_ticker:MSFT|GOOG|... (required if account_type:equity_comp)",
            ]
        },
    }


async def _set_account_taxonomy_tags_internal(
    account_id: str,
    entity: str,
    tax_wrapper: str,
    account_type: str,
    comp_plan: str | None,
    preserve_existing_comment: bool,
    owner_person: str | None = None,
    employer_ticker: str | None = None,
) -> dict[str, Any]:
    account_id = account_id.strip()
    entity = entity.strip().lower()
    tax_wrapper = tax_wrapper.strip().lower()
    account_type = account_type.strip().lower()
    comp_plan = comp_plan.strip().lower() if isinstance(comp_plan, str) and comp_plan.strip() else None
    owner_person = owner_person.strip().lower() if isinstance(owner_person, str) and owner_person.strip() else None
    employer_ticker = employer_ticker.strip().upper() if isinstance(employer_ticker, str) and employer_ticker.strip() else None

    if not account_id:
        return {"ok": False, "code": "invalid_input", "message": "account_id is required."}
    if entity not in VALID_ENTITY:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": f"Invalid entity '{entity}'. Valid values: {', '.join(sorted(VALID_ENTITY))}",
        }
    if tax_wrapper not in VALID_WRAPPER:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": f"Invalid tax_wrapper '{tax_wrapper}'. Valid values: {', '.join(sorted(VALID_WRAPPER))}",
        }
    if account_type not in VALID_ACCOUNT_TYPES:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": (
                f"Invalid account_type '{account_type}'. "
                f"Valid values: {', '.join(sorted(VALID_ACCOUNT_TYPES))}"
            ),
        }
    if comp_plan is not None and comp_plan not in VALID_COMP_PLANS:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": (
                f"Invalid comp_plan '{comp_plan}'. "
                f"Valid values: {', '.join(sorted(VALID_COMP_PLANS))}"
            ),
        }
    if account_type == "equity_comp" and comp_plan is None:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": "comp_plan is required when account_type is 'equity_comp'.",
        }
    if owner_person is not None and owner_person not in VALID_OWNER:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": f"Invalid owner_person '{owner_person}'. Valid values: {', '.join(sorted(VALID_OWNER))}",
        }
    if account_type == "equity_comp" and employer_ticker is None:
        return {
            "ok": False,
            "code": "invalid_input",
            "message": "employer_ticker is required when account_type is 'equity_comp'.",
        }
    if employer_ticker is not None and (len(employer_ticker) < 1 or len(employer_ticker) > 5 or not employer_ticker.isalpha()):
        return {
            "ok": False,
            "code": "invalid_input",
            "message": f"Invalid employer_ticker '{employer_ticker}'. Must be 1-5 uppercase letters (e.g. MSFT, GOOG).",
        }

    current_result = await _request("GET", f"/api/v1/account/{account_id}")
    if not current_result.get("ok"):
        return {
            "ok": False,
            "code": current_result.get("error", {}).get("code", "request_failed"),
            "message": current_result.get("error", {}).get("message", "Account fetch failed."),
            "details": {"status_code": current_result.get("status_code")},
        }

    account = _extract_account_record(current_result.get("body"))
    if account is None:
        return {
            "ok": False,
            "code": "response_parse_error",
            "message": f"Could not parse account payload for '{account_id}'.",
        }

    next_comment = _build_taxonomy_comment(
        entity=entity,
        tax_wrapper=tax_wrapper,
        account_type=account_type,
        comp_plan=comp_plan,
        owner_person=owner_person,
        employer_ticker=employer_ticker,
        existing_comment=account.get("comment") if isinstance(account.get("comment"), str) else None,
        preserve_existing_comment=preserve_existing_comment,
    )

    update_payload = _build_account_update_payload(account, next_comment)
    if isinstance(update_payload, str):
        return {
            "ok": False,
            "code": "invalid_update_payload",
            "message": update_payload,
        }

    put_result = await _request(
        "PUT",
        f"/api/v1/account/{account_id}",
        json=update_payload,
    )
    if not put_result.get("ok"):
        return {
            "ok": False,
            "code": put_result.get("error", {}).get("code", "request_failed"),
            "message": put_result.get("error", {}).get("message", "Account update failed."),
            "details": {"status_code": put_result.get("status_code")},
        }

    refreshed = await _request("GET", f"/api/v1/account/{account_id}")
    if not refreshed.get("ok"):
        return {
            "ok": True,
            "account_id": account_id,
            "comment": next_comment,
            "classification_tags": [
                f"entity:{entity}",
                f"tax_wrapper:{tax_wrapper}",
                f"account_type:{account_type}",
                *([f"comp_plan:{comp_plan}"] if comp_plan else []),
            ],
            "classification": {
                "entity": entity,
                "tax_wrapper": tax_wrapper,
                "account_type": account_type,
                "comp_plan": comp_plan,
                "valid": True,
                "errors": [],
            },
            "warning": (
                "Account updated, but refresh failed: "
                + str(refreshed.get("error", {}).get("message", "unknown error"))
            ),
            "update_status_code": put_result.get("status_code"),
        }

    updated = _extract_account_record(refreshed.get("body"))
    if updated is None:
        return {
            "ok": True,
            "account_id": account_id,
            "comment": next_comment,
            "warning": "Account updated, but refreshed payload was not parseable.",
            "update_status_code": put_result.get("status_code"),
        }

    tags = _extract_account_tags(updated, _load_env_account_tag_map())
    classification = _classify_account_tags(tags)
    return {
        "ok": True,
        "account_id": updated.get("id", account_id),
        "name": updated.get("name"),
        "comment": updated.get("comment"),
        "classification_tags": tags,
        "classification": classification,
        "update_status_code": put_result.get("status_code"),
    }


async def _handle_account_list(tool, op, params):
    result = await _request("GET", "/api/v1/account", params=params)
    return _from_request(tool, op, "GET", "/api/v1/account", result)


async def _handle_account_get(tool, op, account_id):
    if not account_id:
        return _failure(tool, op, "GET", "/api/v1/account/:id", "invalid_input", "account_id is required.")
    result = await _request("GET", f"/api/v1/account/{account_id}")
    return _from_request(tool, op, "GET", f"/api/v1/account/{account_id}", result)


async def _handle_account_balances(tool, op, account_id, params):
    if not account_id:
        return _failure(tool, op, "GET", "/api/v1/account/:id/balances", "invalid_input", "account_id is required.")
    result = await _request("GET", f"/api/v1/account/{account_id}/balances", params=params)
    return _from_request(tool, op, "GET", f"/api/v1/account/{account_id}/balances", result)


async def _handle_account_create(tool, op, data):
    payload = dict(data)
    if "value" in payload and "balance" not in payload:
        payload["balance"] = payload.pop("value")
    payload.setdefault("balance", 0)
    payload.setdefault("currency", "USD")
    if payload.get("platformId") is None:
        payload["platformId"] = ""
    payload.setdefault("platformId", "")
    result = await _request("POST", "/api/v1/account", json=payload)
    return _from_request(tool, op, "POST", "/api/v1/account", result)


async def _handle_account_update(tool, op, account_id, data, preserve_existing_comment):
    if not account_id:
        return _failure(tool, op, "PUT", "/api/v1/account/:id", "invalid_input", "account_id is required.")
    payload = dict(data)
    if "value" in payload and "balance" not in payload:
        payload["balance"] = payload.pop("value")
    current_result = await _request("GET", f"/api/v1/account/{account_id}")
    current_account = current_result.get("body") if current_result.get("ok") else None
    if isinstance(current_account, dict):
        payload.setdefault("name", current_account.get("name"))
        payload.setdefault("currency", current_account.get("currency") or "USD")
        payload.setdefault("balance", current_account.get("balance", 0))
        payload.setdefault("platformId", current_account.get("platformId") or "")
        payload.setdefault("isExcluded", current_account.get("isExcluded", False))
        if preserve_existing_comment and "comment" not in payload:
            if current_account.get("comment") is not None:
                payload["comment"] = current_account.get("comment")
    else:
        payload.setdefault("currency", "USD")
        payload.setdefault("balance", 0)
        if payload.get("platformId") is None:
            payload["platformId"] = ""
        payload.setdefault("platformId", "")
    payload.setdefault("id", account_id)
    result = await _request("PUT", f"/api/v1/account/{account_id}", json=payload)
    return _from_request(tool, op, "PUT", f"/api/v1/account/{account_id}", result)


async def _handle_account_delete(tool, op, account_id):
    if not account_id:
        return _failure(tool, op, "DELETE", "/api/v1/account/:id", "invalid_input", "account_id is required.")
    result = await _request("DELETE", f"/api/v1/account/{account_id}")
    return _from_request(tool, op, "DELETE", f"/api/v1/account/{account_id}", result)


async def _handle_account_create_balance(tool, op, data):
    payload = dict(data)
    if "value" in payload and "balance" not in payload:
        payload["balance"] = payload.pop("value")
    result = await _request("POST", "/api/v1/account-balance", json=payload)
    return _from_request(tool, op, "POST", "/api/v1/account-balance", result)


async def _handle_account_delete_balance(tool, op, record_id, account_id):
    target = record_id or account_id
    if not target:
        return _failure(tool, op, "DELETE", "/api/v1/account-balance/:id", "invalid_input", "record_id is required (or use account_id).")
    result = await _request("DELETE", f"/api/v1/account-balance/{target}")
    return _from_request(tool, op, "DELETE", f"/api/v1/account-balance/{target}", result)


async def _handle_account_transfer_balance(tool, op, data):
    payload = dict(data)
    if "fromAccountId" in payload and "accountIdFrom" not in payload:
        payload["accountIdFrom"] = payload.pop("fromAccountId")
    if "toAccountId" in payload and "accountIdTo" not in payload:
        payload["accountIdTo"] = payload.pop("toAccountId")
    if "value" in payload and "balance" not in payload:
        payload["balance"] = payload.pop("value")
    payload.pop("date", None)
    result = await _request("POST", "/api/v1/account/transfer-balance", json=payload)
    return _from_request(tool, op, "POST", "/api/v1/account/transfer-balance", result)


async def _handle_account_classify(tool, op):
    payload = await _get_accounts_with_classification(strict=False)
    if not payload.get("ok") and payload.get("error"):
        return _failure(
            tool,
            op,
            "GET",
            "/api/v1/account",
            payload.get("error", {}).get("code", "request_failed"),
            payload.get("error", {}).get("message", "Failed to load accounts."),
            details={"status_code": payload.get("status_code")},
        )
    return _success(tool, op, "GET", "/api/v1/account", payload)


async def _handle_account_validate_taxonomy(tool, op, strict):
    payload = await _get_accounts_with_classification(strict=False)
    if not payload.get("ok") and payload.get("error"):
        return _failure(
            tool,
            op,
            "GET",
            "/api/v1/account",
            payload.get("error", {}).get("code", "request_failed"),
            payload.get("error", {}).get("message", "Failed to load accounts."),
            details={"status_code": payload.get("status_code")},
        )

    invalid_accounts = payload.get("invalid_accounts", [])
    if strict and invalid_accounts:
        return _failure(
            tool,
            op,
            "GET",
            "/api/v1/account",
            "taxonomy_validation_failed",
            "Account taxonomy validation failed.",
            details={
                "summary": payload.get("summary", {}),
                "invalid_accounts": invalid_accounts,
                "taxonomy": payload.get("taxonomy", {}),
            },
        )

    return _success(
        tool,
        op,
        "GET",
        "/api/v1/account",
        {
            "ok": len(invalid_accounts) == 0,
            "summary": payload.get("summary", {}),
            "invalid_accounts": invalid_accounts,
            "taxonomy": payload.get("taxonomy", {}),
        },
    )


async def _handle_account_set_taxonomy_tags(
    tool, op, account_id, entity, tax_wrapper, account_type,
    comp_plan, preserve_existing_comment, owner_person, employer_ticker,
):
    if not account_id:
        return _failure(tool, op, "PUT", "/api/v1/account/:id", "invalid_input", "account_id is required.")
    if not entity or not tax_wrapper or not account_type:
        return _failure(
            tool,
            op,
            "PUT",
            "/api/v1/account/:id",
            "invalid_input",
            "entity, tax_wrapper, and account_type are required.",
        )

    result = await _set_account_taxonomy_tags_internal(
        account_id=account_id,
        entity=entity,
        tax_wrapper=tax_wrapper,
        account_type=account_type,
        comp_plan=comp_plan,
        preserve_existing_comment=preserve_existing_comment,
        owner_person=owner_person,
        employer_ticker=employer_ticker,
    )
    if not result.get("ok"):
        return _failure(
            tool,
            op,
            "PUT",
            f"/api/v1/account/{account_id}",
            result.get("code", "update_failed"),
            result.get("message", "Failed to set taxonomy tags."),
            details=result.get("details"),
        )
    return _success(tool, op, "PUT", f"/api/v1/account/{account_id}", result)


async def _handle_account_set_taxonomy_tags_by_name(
    tool, op, account_name, entity, tax_wrapper, account_type,
    comp_plan, preserve_existing_comment, owner_person, employer_ticker,
):
    if not account_name:
        return _failure(tool, op, "PUT", "/api/v1/account/:id", "invalid_input", "account_name is required.")
    if not entity or not tax_wrapper or not account_type:
        return _failure(
            tool,
            op,
            "PUT",
            "/api/v1/account/:id",
            "invalid_input",
            "entity, tax_wrapper, and account_type are required.",
        )

    raw = await _get_accounts_raw()
    if not raw.get("ok"):
        return _failure(
            tool,
            op,
            "GET",
            "/api/v1/account",
            raw.get("error", {}).get("code", "request_failed"),
            raw.get("error", {}).get("message", "Failed to load accounts."),
            details={"status_code": raw.get("status_code")},
        )

    target = account_name.strip().lower()
    rows = [a for a in raw.get("accounts", []) if isinstance(a, dict)]
    exact = [
        a for a in rows
        if isinstance(a.get("name"), str) and a.get("name", "").strip().lower() == target
    ]
    partial = [
        a for a in rows
        if isinstance(a.get("name"), str) and target in a.get("name", "").strip().lower()
    ]
    matches = exact if exact else partial

    if not matches:
        return _failure(
            tool,
            op,
            "GET",
            "/api/v1/account",
            "not_found",
            f"No account found for name '{account_name}'.",
            details={
                "available_accounts": [
                    {"account_id": _extract_account_id(a), "name": a.get("name")}
                    for a in rows
                ]
            },
        )
    if len(matches) > 1:
        return _failure(
            tool,
            op,
            "GET",
            "/api/v1/account",
            "ambiguous_match",
            f"Multiple accounts matched '{account_name}'. Use account_id instead.",
            details={
                "matches": [
                    {"account_id": _extract_account_id(a), "name": a.get("name")}
                    for a in matches
                ]
            },
        )

    chosen = matches[0]
    chosen_id = _extract_account_id(chosen)
    if not chosen_id:
        return _failure(tool, op, "GET", "/api/v1/account", "invalid_data", "Matched account is missing an account id.")

    result = await _set_account_taxonomy_tags_internal(
        account_id=chosen_id,
        entity=entity,
        tax_wrapper=tax_wrapper,
        account_type=account_type,
        comp_plan=comp_plan,
        preserve_existing_comment=preserve_existing_comment,
        owner_person=owner_person,
        employer_ticker=employer_ticker,
    )
    if not result.get("ok"):
        return _failure(
            tool,
            op,
            "PUT",
            f"/api/v1/account/{chosen_id}",
            result.get("code", "update_failed"),
            result.get("message", "Failed to set taxonomy tags."),
            details=result.get("details"),
        )

    result["resolved_account_name"] = chosen.get("name")
    return _success(tool, op, "PUT", f"/api/v1/account/{chosen_id}", result)


def register_account_tools(mcp):
    @mcp.tool()
    async def account(
        operation: str,
        account_id: str | None = None,
        account_name: str | None = None,
        record_id: str | None = None,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        entity: str | None = None,
        tax_wrapper: str | None = None,
        account_type: str | None = None,
        comp_plan: str | None = None,
        owner_person: str | None = None,
        employer_ticker: str | None = None,
        preserve_existing_comment: bool = True,
        strict: bool = True,
    ) -> dict[str, Any]:
        """Consolidated account operations (CRUD, balances, transfers, taxonomy)."""
        tool = "account"
        op = _clean_operation(operation)
        valid = [
            "list",
            "get",
            "balances",
            "create",
            "update",
            "delete",
            "create_balance",
            "delete_balance",
            "transfer_balance",
            "classify",
            "validate_taxonomy",
            "set_taxonomy_tags",
            "set_taxonomy_tags_by_name",
        ]
        if op not in valid:
            return _failure(tool, op, "N/A", "N/A", "invalid_operation", f"Unknown operation: {operation}", valid_operations=valid)

        data = data or {}
        params = params or {}

        if op == "list":
            return await _handle_account_list(tool, op, params)
        if op == "get":
            return await _handle_account_get(tool, op, account_id)
        if op == "balances":
            return await _handle_account_balances(tool, op, account_id, params)
        if op == "create":
            return await _handle_account_create(tool, op, data)
        if op == "update":
            return await _handle_account_update(tool, op, account_id, data, preserve_existing_comment)
        if op == "delete":
            return await _handle_account_delete(tool, op, account_id)
        if op == "create_balance":
            return await _handle_account_create_balance(tool, op, data)
        if op == "delete_balance":
            return await _handle_account_delete_balance(tool, op, record_id, account_id)
        if op == "transfer_balance":
            return await _handle_account_transfer_balance(tool, op, data)
        if op == "classify":
            return await _handle_account_classify(tool, op)
        if op == "validate_taxonomy":
            return await _handle_account_validate_taxonomy(tool, op, strict)
        if op == "set_taxonomy_tags":
            return await _handle_account_set_taxonomy_tags(
                tool, op, account_id, entity, tax_wrapper, account_type,
                comp_plan, preserve_existing_comment, owner_person, employer_ticker,
            )
        if op == "set_taxonomy_tags_by_name":
            return await _handle_account_set_taxonomy_tags_by_name(
                tool, op, account_name, entity, tax_wrapper, account_type,
                comp_plan, preserve_existing_comment, owner_person, employer_ticker,
            )

        return _failure(tool, op, "N/A", "N/A", "not_implemented", "Operation is not implemented.")
