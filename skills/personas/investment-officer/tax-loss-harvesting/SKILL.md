---
name: tax-loss-harvesting
description: Identify tax-loss harvesting opportunities across taxable accounts. Finds positions with unrealized losses, suggests replacement securities, and tracks wash sale windows.
user-invocable: false
---

# Tax-Loss Harvesting

## MCP Tool Map

- Taxable-scope validation and candidate scan: `portfolio-analytics.validate_account_taxonomy`, `portfolio-analytics.find_tax_loss_harvesting_candidates`
- Realized activity context: `ghostfolio.portfolio(operation="performance", range="1y")`
- Tax impact context: use `household-tax.assess_exact_support` only if the requested household-tax effect is inside the supported exact scope

## Workflow

### Step 1: Scope Taxable Accounts

- Validate account tags via `portfolio-analytics.validate_account_taxonomy`
- Use taxable scope only:
  - `scope_entity=personal` (or trust when applicable)
  - `scope_wrapper=taxable`
  - `scope_account_types=["brokerage"]` (must be a list, not a comma-separated string)

### Step 2: Identify Candidates

- Run `portfolio-analytics.find_tax_loss_harvesting_candidates`
- Review:
  - Absolute unrealized loss
  - Loss percentage
  - Estimated tax savings

### Step 3: Gain/Loss Budget

- Pull realized gains/loss context from tax records and budget data
- Prioritize losses where marginal tax benefit is highest
- Do not call deleted household-tax scenario tools. If a household-tax overlay is needed, assess exact support first and stop if unsupported.

### Step 4: Replacement Selection

- Use suggested replacements while avoiding substantially identical securities
- Prefer liquid alternatives with similar exposure and low tracking error

### Step 5: Wash Sale Controls

- Enforce 30-day wash sale window across all household accounts
- Check DRIP/auto-invest settings that may trigger repurchases

### Step 6: Output

- Candidate list with estimated savings
- Replacement mapping and execution order
- Wash sale window calendar
