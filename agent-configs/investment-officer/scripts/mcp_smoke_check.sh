#!/usr/bin/env bash
set -euo pipefail

PASS=0
FAIL=0

log_ok() {
  echo "OK   $1"
  PASS=$((PASS + 1))
}

log_fail() {
  echo "FAIL $1"
  FAIL=$((FAIL + 1))
}

check_http() {
  local name="$1"
  local url="$2"
  local status
  status="$(curl -sS -o /dev/null -w '%{http_code}' "$url" || echo 000)"
  if [[ "$status" =~ ^2|3 ]]; then
    log_ok "$name ($status)"
  else
    log_fail "$name ($status) -> $url"
  fi
}

echo "Running HTTP service checks..."
check_http "ghostfolio" "http://localhost:8224/api/v1/health"
check_http "actual-budget" "http://localhost:5006/"

echo
echo "Running market-intel-direct tool check..."
if /path/to/stewardos/servers/investing-workspace/.venv/bin/python - <<'PY'
import importlib.util
import inspect
import pathlib
import asyncio

path = pathlib.Path("/path/to/stewardos/servers/investing-workspace/market-intel-direct/server.py")
spec = importlib.util.spec_from_file_location("market_intel_direct_server", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[union-attr]

result = mod.get_market_snapshot.fn()
if inspect.isawaitable(result):
    result = asyncio.run(result)
assert isinstance(result, dict)
assert result.get("ok") is True
assert "quotes" in result

news = mod.search_market_news.fn(query="Federal Reserve policy", days_back=2, limit=5, source_country="US")
if inspect.isawaitable(news):
    news = asyncio.run(news)
assert isinstance(news, dict)
assert "ok" in news
if news.get("ok") is False:
    assert news.get("error_code")
    assert news.get("retryable") is not None
PY
then
  log_ok "market-intel-direct.get_market_snapshot/search_market_news"
else
  log_fail "market-intel-direct.get_market_snapshot/search_market_news"
fi

echo
echo "Running sec-edgar tool checks..."
if EDGAR_LOCAL_DATA_DIR=/tmp/sec-edgar-data EDGAR_CACHE_DIR=/tmp/sec-edgar-cache \
   /path/to/stewardos/servers/investing-workspace/sec-edgar/.venv/bin/python - <<'PY'
import importlib.util
import pathlib

path = pathlib.Path("/path/to/stewardos/servers/investing-workspace/sec-edgar/consolidated_server.py")
spec = importlib.util.spec_from_file_location("sec_edgar_consolidated_server", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[union-attr]

r1 = mod.sec_edgar_company(operation="cik_by_ticker", ticker="AAPL")
assert r1.get("ok") is True
assert r1.get("data", {}).get("cik")

r2 = mod.sec_edgar_company(operation="search", query="AAPL", limit=3)
assert r2.get("ok") is True
assert r2.get("data", {}).get("count", 0) >= 1
PY
then
  log_ok "sec-edgar company ops (cik_by_ticker/search)"
else
  log_fail "sec-edgar company ops (cik_by_ticker/search)"
fi

echo
echo "Running portfolio-analytics tool check..."
FALLBACK_GHOSTFOLIO_TOKEN="$(python3 - <<'PY'
from pathlib import Path
import re

text = Path('/path/to/stewardos/agent-configs/investment-officer/.codex/config.toml').read_text()
match = re.search(r'GHOSTFOLIO_TOKEN\s*=\s*"([^"]+)"', text)
print(match.group(1) if match else "")
PY
)"
EFFECTIVE_GHOSTFOLIO_TOKEN="${GHOSTFOLIO_TOKEN:-$FALLBACK_GHOSTFOLIO_TOKEN}"

if GHOSTFOLIO_URL="http://localhost:8224" \
   GHOSTFOLIO_TOKEN="$EFFECTIVE_GHOSTFOLIO_TOKEN" \
   /path/to/stewardos/servers/investing-workspace/.venv/bin/python - <<'PY'
import asyncio
import importlib.util
import pathlib

path = pathlib.Path("/path/to/stewardos/servers/investing-workspace/portfolio-analytics/server.py")
spec = importlib.util.spec_from_file_location("portfolio_analytics_server", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[union-attr]

async def main():
    result = await mod.validate_account_taxonomy.fn(strict=False)
    assert isinstance(result, dict)
    assert "ok" in result
    state = await mod.get_condensed_portfolio_state.fn(strict=False)
    assert state.get("ok") is True
    portfolio = state.get("portfolio", {})
    assert "investments_value_ex_cash" in portfolio
    assert "cash_balance" in portfolio
    assert "net_worth_total" in portfolio

    scoped_types = ["brokerage", "401k", "hsa", "equity_comp"]
    coverage = await mod.validate_account_scope_coverage.fn(
        scope_account_types=scoped_types,
        strict=False,
    )
    assert "ok" in coverage

    risk = await mod.analyze_portfolio_risk.fn(
        scope_account_types=scoped_types,
        strict=False,
        lookback_days=120,
    )
    assert "ok" in risk

    returns = await mod.get_portfolio_return_series.fn(
        scope_account_types=scoped_types,
        strict=False,
        lookback_days=120,
    )
    assert "ok" in returns

    tlh = await mod.find_tax_loss_harvesting_candidates.fn(
        scope_account_types=["brokerage"],
        strict=False,
        min_loss_amount=100.0,
    )
    assert "ok" in tlh

asyncio.run(main())
PY
then
  log_ok "portfolio-analytics scoped analytics (list-form scope_account_types)"
else
  log_fail "portfolio-analytics scoped analytics (list-form scope_account_types)"
fi

echo
echo "Running finance-graph tool checks..."
if /path/to/stewardos/servers/finance-graph-mcp/.venv/bin/python - <<'PY'
import asyncio
import importlib.util
import json
import pathlib

path = pathlib.Path("/path/to/stewardos/servers/finance-graph-mcp/server.py")
spec = importlib.util.spec_from_file_location("finance_graph_server", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[union-attr]

async def main():
    methods_raw = await mod.list_valuation_methods()
    methods = json.loads(methods_raw)
    assert isinstance(methods, list)
    codes = {m.get("code") for m in methods if isinstance(m, dict)}
    for required in ("rentcast_avm", "manual_comp", "manual_mark", "income_approach", "dcf"):
        assert required in codes
    liability_types_raw = await mod.list_liability_types()
    liability_types = json.loads(liability_types_raw)
    assert isinstance(liability_types, list)
    liability_codes = {m.get("code") for m in liability_types if isinstance(m, dict)}
    for required in ("mortgage_fixed", "mortgage_arm", "heloc", "home_equity_loan", "other_secured"):
        assert required in liability_codes

asyncio.run(main())
PY
then
  log_ok "finance-graph.list_valuation_methods/list_liability_types"
else
  log_fail "finance-graph.list_valuation_methods/list_liability_types"
fi

echo
echo "Summary: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
