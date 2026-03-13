# Routing Matrix Reference

Detailed request-to-persona routing rules, tool mappings, and conflict resolution
for the Chief of Staff orchestration layer.

---

## Request Pattern to Persona Routing

| Request Pattern | Route To | Tools Used | Example |
|----------------|----------|-----------|---------|
| "What's my net worth?" | Comptroller | actual-budget, ghostfolio, finance-graph | Monthly net worth report |
| "How's my portfolio doing?" | Investment Officer | ghostfolio, portfolio-analytics | Performance + risk snapshot |
| "Review this contract" | Estate Counsel | estate-planning, paperless | Clause-by-clause analysis |
| "Check my health stats" | Wellness Advisor | oura, apple-health, wger | Daily health dashboard |
| "Plan meals for the week" | Household Director | mealie, grocy | Meal plan + grocery list |
| "Triage my inbox" | Chief of Staff | google-workspace | Email summary + actions |
| "Tax impact of selling AAPL" | IO (primary) + HC (tax) | ghostfolio, household-tax | Tax-aware trade analysis |
| "Estate plan review" | EC (primary) + IO (valuation) | estate-planning, finance-graph | Full estate snapshot |
| "Am I on track for retirement?" | HC (primary) + IO (portfolio) | actual-budget, ghostfolio, finance-graph | Financial plan assessment |

---

## Detailed Routing by Domain

### Budget, Spending, Cash Flow

| Request Pattern | Primary | Tools | Notes |
|----------------|---------|-------|-------|
| Monthly budget status | Comptroller | actual-budget | Compare actuals to budget |
| Cash flow forecast | Comptroller | actual-budget, finance-graph | Project forward 30/60/90 days |
| Spending anomaly | Comptroller | actual-budget | Flag outlier transactions |
| Net worth snapshot | Comptroller | actual-budget, ghostfolio, finance-graph | Aggregate all accounts |

### Portfolio, Risk, Markets

| Request Pattern | Primary | Tools | Notes |
|----------------|---------|-------|-------|
| Performance report | Investment Officer | ghostfolio, portfolio-analytics | Returns, attribution, risk metrics |
| Risk assessment | Investment Officer | portfolio-analytics | VaR, ES, concentration, factor exposure |
| Stock research | Investment Officer | sec-edgar, market-intel-direct | Company fundamentals + news |
| Trade analysis | Investment Officer | ghostfolio, portfolio-analytics | Impact on portfolio risk/return |
| Rebalance recommendation | Investment Officer | ghostfolio, portfolio-analytics | Drift analysis + target weights |

### Estate, Entities, Ownership

| Request Pattern | Primary | Tools | Notes |
|----------------|---------|-------|-------|
| Entity structure review | Estate Counsel | estate-planning | Ownership graph, entity details |
| Beneficiary check | Estate Counsel | estate-planning | Designation currency |
| Document review | Estate Counsel | estate-planning, paperless | Contract or trust analysis |
| Compliance status | Estate Counsel | estate-planning | Filing deadlines, required actions |

### Health, Fitness, Medical

| Request Pattern | Primary | Tools | Notes |
|----------------|---------|-------|-------|
| Sleep quality | Wellness Advisor | oura | Sleep stages, HRV, readiness |
| Workout tracking | Wellness Advisor | wger | Exercise log, progression |
| Health dashboard | Wellness Advisor | oura, apple-health, wger | Composite daily/weekly view |
| Anomaly investigation | Wellness Advisor | oura, apple-health | Trend deviation analysis |

### Household Ops, Inventory

| Request Pattern | Primary | Tools | Notes |
|----------------|---------|-------|-------|
| Meal planning | Household Director | mealie | Weekly plan, recipe selection |
| Grocery list | Household Director | mealie, grocy | Consolidated shopping list |
| Inventory check | Household Director | grocy | Stock levels, expiring items |
| Home maintenance | Household Director | grocy | Task scheduling, overdue items |

### Email, Calendar, Filing

| Request Pattern | Primary | Tools | Notes |
|----------------|---------|-------|-------|
| Inbox triage | Chief of Staff | google-workspace | Priority sort, action extraction |
| Calendar review | Chief of Staff | google-workspace | Upcoming events, conflicts |
| Document filing | Chief of Staff | paperless | Classify and file documents |
| Cross-persona coordination | Chief of Staff | All as needed | Multi-persona synthesis |

---

## Multi-Persona Request Patterns

These requests require coordination between two or more personas.

### Two-Persona Patterns

| Pattern | Primary | Secondary | Synthesis Rule |
|---------|---------|-----------|---------------|
| Tax-aware trade analysis | Investment Officer | Household Comptroller | IO provides trade impact; HC overlays tax lots, wash sale, and bracket impact |
| Estate plan with valuations | Estate Counsel | Investment Officer | EC provides structure; IO provides current market valuations for all assets |
| Retirement readiness | Household Comptroller | Investment Officer | HC provides savings rate and spending; IO provides portfolio projection and risk |
| Health-aware scheduling | Wellness Advisor | Chief of Staff | WA provides readiness score; CoS adjusts calendar density accordingly |
| Budget-aware meal planning | Household Director | Household Comptroller | HD provides meal plan; HC checks grocery budget adherence |

### Three+ Persona Patterns

| Pattern | Personas Involved | Synthesis Rule |
|---------|------------------|---------------|
| Annual financial review | HC + IO + EC | HC: budget and cash flow; IO: portfolio performance; EC: estate currency. CoS synthesizes. |
| Major purchase analysis | HC + IO + EC | HC: affordability; IO: opportunity cost; EC: ownership structure. CoS presents trade-offs. |
| Life event planning (baby, move, etc.) | HC + IO + EC + WA + HD | Full cross-domain impact assessment. CoS orchestrates sequentially. |

---

## Conflict Resolution Rules

When multiple personas produce overlapping or conflicting data, use these canonical
source rules to determine which value prevails.

| Data Domain | Canonical Persona | Canonical Source | Rationale |
|------------|------------------|-----------------|-----------|
| Portfolio valuation | Investment Officer | Ghostfolio | Single source of truth for market values and cost basis |
| Tax computation | Household Comptroller | household-tax MCP | Tax engine owns all bracket, lot, and withholding logic |
| Entity ownership | Estate Counsel | estate-planning MCP | Ownership graph is maintained in estate-planning server |
| Health data | Wellness Advisor | health-graph MCP | Aggregates Oura, Apple Health, wger into unified model |
| Document taxonomy | Chief of Staff | Paperless MCP | Filing classification and retrieval |
| Meal and grocery data | Household Director | Mealie / Grocy MCP | Recipe, meal plan, and inventory source of truth |

### Resolution Protocol

1. Identify which data domain the conflict falls under.
2. The canonical persona's value prevails.
3. Note the discrepancy in the synthesis output for investigation.
4. If a conflict spans two domains (e.g., tax lot valuation), each persona's canonical domain wins for their portion: IO for market value, HC for tax basis.

---

## Escalation Triggers

Automatic escalation rules that override normal routing.

| Trigger | Condition | Escalate To | Action |
|---------|-----------|------------|--------|
| Portfolio risk breach | Expected Shortfall > 2.5% daily or illiquidity > 25% | Chief of Staff + Comptroller | Risk alert with de-risk recommendations |
| Net worth threshold | Crosses a user-defined milestone (up or down) | Chief of Staff | Awareness notification |
| Entity restructuring | Any ownership change in estate-planning | Investment Officer | Valuation and tax impact assessment |
| Health anomaly | HRV, resting HR, or sleep score deviates > 2 sigma for 3+ days | Chief of Staff | Schedule adjustment recommendation |
| Maintenance overdue | Home maintenance task past due > 14 days | Chief of Staff | Triage and scheduling |
| Budget breach | Category spend exceeds budget by > 20% | Chief of Staff | Spending alert with context |
