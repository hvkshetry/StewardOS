---
name: net-worth-report
description: Generate consolidated household net worth report combining cash, investments, illiquid assets, and liabilities from all data sources.
user-invocable: true
---

# /net-worth — Consolidated Net Worth Report

Produce a complete household net worth snapshot by aggregating cash accounts (Actual Budget), investment accounts (Ghostfolio), illiquid assets (finance-graph), and all liabilities.

## MCP Tool Map

- Cash and debt accounts: `actual-budget.account`, `actual-budget.analytics(operation="balance_history")`
- Investment portfolio: `ghostfolio.portfolio(operation="summary")`
- Illiquid assets and ownership: `finance-graph.get_net_worth_summary`, `finance-graph.query_assets`
- Liabilities: `finance-graph.get_liabilities`
- Historical net worth: `finance-graph.query_financial_facts`

## Steps

### 1. Gather Cash & Bank Accounts (Actual Budget)

- Pull all account balances via `actual-budget.account`
- Categorize: checking, savings, credit cards, loans
- Separate assets (positive balances) from liabilities (credit card balances, loan balances)

### 2. Gather Investment Accounts (Ghostfolio)

- Pull `ghostfolio.portfolio(operation="summary")` for total portfolio value
- Break down by account type if available (taxable, tax-deferred, tax-exempt)
- Note: use portfolio totals only — the investment officer owns detailed position analysis

### 3. Gather Illiquid Assets (finance-graph)

- Pull `finance-graph.get_net_worth_summary` for illiquid asset values
- Include: real estate, private investments, business interests, personal property
- Note valuation dates and methods — flag any valuations older than 6 months

### 4. Gather All Liabilities (finance-graph + Actual Budget)

- Pull `finance-graph.get_liabilities` for mortgage, loans, and other long-term debt
- Combine with credit card balances from Actual Budget
- Categorize: secured (mortgage, auto), unsecured (credit cards, personal loans), other

### 5. Consolidate Net Worth

```
## Household Net Worth — [Date]

### Assets
| Category | Source | Amount |
|----------|--------|--------|
| Cash & checking | Actual Budget | |
| Savings | Actual Budget | |
| Investment accounts | Ghostfolio | |
| Real estate | finance-graph | |
| Private investments | finance-graph | |
| Other illiquid | finance-graph | |
| **Total Assets** | | |

### Liabilities
| Category | Source | Amount |
|----------|--------|--------|
| Credit cards | Actual Budget | |
| Mortgage | finance-graph | |
| Auto loans | finance-graph | |
| Other debt | finance-graph | |
| **Total Liabilities** | | |

| **Net Worth** | | **$X** |
```

### 6. Composition Analysis

```
### Asset Allocation
| Category | Amount | % of Total |
|----------|--------|-----------|
| Liquid (cash + savings) | | |
| Investments (public markets) | | |
| Illiquid (real estate, private) | | |

### Debt-to-Asset Ratio: X%
### Liquid-to-Total Ratio: X%
```

### 7. Historical Comparison

- Pull prior month's balance sheet from `finance-graph.query_financial_facts`
- Calculate month-over-month change (absolute and percentage)
- Identify primary drivers of change (market performance, debt paydown, savings)

### 8. Output

```
### Summary
- Total Assets: $X
- Total Liabilities: $X
- **Net Worth: $X**
- Change from prior month: +/- $X (X%)

### Key Drivers
- [What drove the change: market gains, debt paydown, savings, property valuation, etc.]

### Data Quality Notes
- [Any stale valuations, missing accounts, or data gaps]
```
