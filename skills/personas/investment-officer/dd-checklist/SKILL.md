---
name: dd-checklist
description: Generate due diligence checklists and red-flag tracking for private and illiquid investment opportunities.
user-invocable: false
---

# Due Diligence Checklist

Create a structured diligence plan for private deals and direct investments.

## MCP Tool Map

- Disclosure and accounting quality checks: `sec-edgar.sec_edgar_filing`, `sec-edgar.sec_edgar_financial` (for public comps and accounting benchmarks)
- Policy and regulatory checks: `policy-events.get_federal_rules`, `policy-events.get_recent_bills`
- Market backdrop: `market-intel-direct.search_market_news`

## Workflow

### Step 1: Deal Scope

- Confirm business model, geography, sector, and transaction type.
- Set materiality thresholds for red flags.

### Step 2: Workstreams

- Financial diligence.
- Commercial diligence.
- Operational diligence.
- Legal/regulatory diligence.
- Technology/cyber diligence.
- Management and governance diligence.

### Step 3: Red Flag Register

- Track open items, owner, due date, status, and severity.
- Escalate unresolved high-severity items.

### Step 4: Output

- Full checklist matrix.
- Priority request list.
- Go/No-Go risk summary.
