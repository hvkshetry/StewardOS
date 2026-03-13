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
echo "Running market-intel-direct readiness checks..."
FALLBACK_FRED_API_KEY="$(python3 - <<'PY'
from pathlib import Path
import re

text = Path('$STEWARDOS_ROOT/agent-configs/investment-officer/.codex/config.toml').read_text()
match = re.search(r'FRED_API_KEY\s*=\s*"([^"]+)"', text)
print(match.group(1) if match else "")
PY
)"
EFFECTIVE_FRED_API_KEY="${FRED_API_KEY:-$FALLBACK_FRED_API_KEY}"

if FRED_API_KEY="$EFFECTIVE_FRED_API_KEY" \
   $STEWARDOS_ROOT/servers/investing-workspace/.venv/bin/python - <<'PY'
import importlib.util
import inspect
import pathlib
import asyncio
import sys

path = pathlib.Path("$STEWARDOS_ROOT/servers/investing-workspace/market-intel-direct/server.py")
sys.path.insert(0, str(path.parent))
spec = importlib.util.spec_from_file_location("market_intel_direct_server", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[union-attr]

def call(tool, **kwargs):
    fn = getattr(tool, "fn", tool)
    result = fn(**kwargs)
    if inspect.isawaitable(result):
        result = asyncio.run(result)
    return result

result = call(mod.get_market_snapshot)
assert isinstance(result, dict)
assert result.get("ok") is True
assert "quotes" in result

news = call(mod.search_market_news, query="Federal Reserve policy", days_back=2, limit=5, source_country="US")
assert isinstance(news, dict)
assert "ok" in news
if news.get("ok") is False:
    assert news.get("error_code")
    assert news.get("retryable") is not None

cape = call(mod.get_shiller_cape)
assert cape.get("ok") is True
assert cape.get("value")

temperature = call(mod.compute_market_temperature)
assert temperature.get("ok") is True
assert temperature.get("status") == "complete"
assert temperature.get("temperature", {}).get("score") is not None

convex = call(
    mod.rank_convex_candidates,
    target_convex_add_pct=0.05,
    allow_options=False,
)
assert convex.get("ok") is True
assert convex.get("primary_path_shortlist")
PY
then
  log_ok "market-intel-direct readiness (snapshot/news/CAPE/temperature/convex-ranking)"
else
  log_fail "market-intel-direct readiness (snapshot/news/CAPE/temperature/convex-ranking)"
fi

echo
echo "Running sec-edgar tool checks..."
if EDGAR_LOCAL_DATA_DIR=/tmp/sec-edgar-data EDGAR_CACHE_DIR=/tmp/sec-edgar-cache \
   $STEWARDOS_ROOT/servers/investing-workspace/sec-edgar/.venv/bin/python - <<'PY'
import importlib.util
import pathlib

path = pathlib.Path("$STEWARDOS_ROOT/servers/investing-workspace/sec-edgar/consolidated_server.py")
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
echo "Running portfolio-analytics readiness checks..."
FALLBACK_GHOSTFOLIO_TOKEN="$(python3 - <<'PY'
from pathlib import Path
import re

text = Path('$STEWARDOS_ROOT/agent-configs/investment-officer/.codex/config.toml').read_text()
match = re.search(r'GHOSTFOLIO_TOKEN\s*=\s*"([^"]+)"', text)
print(match.group(1) if match else "")
PY
)"
EFFECTIVE_GHOSTFOLIO_TOKEN="${GHOSTFOLIO_TOKEN:-$FALLBACK_GHOSTFOLIO_TOKEN}"

if GHOSTFOLIO_URL="http://localhost:8224" \
   GHOSTFOLIO_TOKEN="$EFFECTIVE_GHOSTFOLIO_TOKEN" \
   $STEWARDOS_ROOT/servers/investing-workspace/portfolio-analytics/.venv/bin/python - <<'PY'
import asyncio
import importlib.util
import pathlib
import sys

path = pathlib.Path("$STEWARDOS_ROOT/servers/investing-workspace/portfolio-analytics/server.py")
sys.path.insert(0, str(path.parent))
spec = importlib.util.spec_from_file_location("portfolio_analytics_server", path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)  # type: ignore[union-attr]
import holdings as holdings_mod
import snapshot as snapshot_mod
import risk as risk_mod
import tlh as tlh_mod

async def main():
    result = await holdings_mod.validate_account_taxonomy(strict=False)
    assert isinstance(result, dict)
    assert "ok" in result
    state = await snapshot_mod.get_condensed_portfolio_state(strict=False)
    assert state.get("ok") is True
    portfolio = state.get("portfolio", {})
    assert "investments_value_ex_cash" in portfolio
    assert "cash_balance" in portfolio
    assert "net_worth_total" in portfolio

    scoped_types = ["brokerage", "401k", "hsa", "equity_comp"]
    coverage = await snapshot_mod.validate_account_scope_coverage(
        scope_account_types=scoped_types,
        strict=False,
    )
    assert "ok" in coverage

    risk = await risk_mod.analyze_portfolio_risk(
        scope_account_types=scoped_types,
        strict=False,
        lookback_days=120,
    )
    assert "ok" in risk
    assert "risk" in risk

    returns = await risk_mod.get_portfolio_return_series(
        scope_account_types=scoped_types,
        strict=False,
        lookback_days=120,
    )
    assert "ok" in returns

    tlh = await tlh_mod.find_tax_loss_harvesting_candidates(
        scope_account_types=["brokerage"],
        strict=False,
        min_loss_amount=100.0,
    )
    assert "ok" in tlh

    barbell = await risk_mod.classify_barbell_buckets(
        scope_account_types=scoped_types,
        strict=False,
    )
    assert barbell.get("ok") is True
    assert "safe_gap_pct" in barbell
    assert "convex_gap_pct" in barbell
    assert "fragile_excess_pct" in barbell

    symbols = state.get("portfolio", {}).get("symbols", [])
    chosen_symbol = next((s for s in symbols if s not in {"USD", "CASH"}), None)
    if chosen_symbol:
        hypothetical = await risk_mod.analyze_hypothetical_portfolio_risk(
            target_allocations={"USD": 0.10, chosen_symbol: 0.90},
            scope_account_types=scoped_types,
            strict=False,
            lookback_days=120,
        )
        assert hypothetical.get("ok") is True
        assert "verification_pass" in hypothetical
        assert "post_plan_barbell" in hypothetical

asyncio.run(main())
PY
then
  log_ok "portfolio-analytics readiness (risk/barbell/hypothetical/TLH)"
else
  log_fail "portfolio-analytics readiness (risk/barbell/hypothetical/TLH)"
fi

echo
echo "Running finance-graph tool checks..."
if $STEWARDOS_ROOT/servers/finance-graph-mcp/.venv/bin/python - <<'PY'
import asyncio
import json
import pathlib
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

async def main():
    server = StdioServerParameters(
        command="$STEWARDOS_ROOT/servers/finance-graph-mcp/.venv/bin/python",
        args=["server.py"],
        cwd="$STEWARDOS_ROOT/servers/finance-graph-mcp",
    )

    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_result = await session.list_tools()
            tool_names = {tool.name for tool in tools_result.tools}
            for required in ("list_valuation_methods", "list_liability_types", "get_net_worth"):
                assert required in tool_names

            methods_call = await session.call_tool("list_valuation_methods")
            assert not methods_call.isError
            methods_payload = methods_call.structuredContent
            assert methods_payload["status"] == "ok"
            methods = methods_payload["data"]
            assert isinstance(methods, list)
            codes = {m.get("code") for m in methods if isinstance(m, dict)}
            for required in ("rentcast_avm", "manual_comp", "manual_mark", "income_approach", "dcf"):
                assert required in codes

            liability_types_call = await session.call_tool("list_liability_types")
            assert not liability_types_call.isError
            liability_types_payload = liability_types_call.structuredContent
            assert liability_types_payload["status"] == "ok"
            liability_types = liability_types_payload["data"]
            assert isinstance(liability_types, list)
            liability_codes = {m.get("code") for m in liability_types if isinstance(m, dict)}
            for required in ("mortgage_fixed", "mortgage_arm", "heloc", "home_equity_loan", "other_secured"):
                assert required in liability_codes

            net_worth_call = await session.call_tool("get_net_worth")
            assert not net_worth_call.isError
            net_worth_payload = net_worth_call.structuredContent
            assert net_worth_payload["status"] == "ok"
            assert isinstance(net_worth_payload["data"], list)

asyncio.run(main())
PY
then
  log_ok "finance-graph readiness (valuation methods/liability types/net worth)"
else
  log_fail "finance-graph readiness (valuation methods/liability types/net worth)"
fi

echo
echo "Summary: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then
  exit 1
fi
