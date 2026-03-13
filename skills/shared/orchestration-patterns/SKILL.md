---
name: orchestration-patterns
description: |
  Cross-persona orchestration patterns for multi-agent synthesis. Reference
  skill for routing decisions, complexity scoring, and synthesis frameworks.
  Not user-invocable — loaded as context for the chief of staff.
user-invocable: false
---

# Orchestration Patterns

Shared skill providing the Chief of Staff with routing, scoring, and synthesis
rules for multi-persona coordination across StewardOS.

---

## Complexity Scoring Rubric

Score every inbound request 1-5 before routing. The score determines the
orchestration strategy.

| Score | Label | Criteria | Orchestration |
|-------|-------|----------|---------------|
| 1 | Simple | Single-source lookup; one persona can answer directly. | Direct route, no synthesis. |
| 2 | Standard | Multi-tool within one persona; standard workflow. | Route to one persona, await result. |
| 3 | Cross-Domain | Requires 2 personas' data sources; one synthesizer. | Parallel dispatch to 2 personas, Chief of Staff synthesizes. |
| 4 | Complex | Requires 3+ personas; sequential dependencies exist. | Dependency-ordered dispatch; intermediate results feed downstream personas. |
| 5 | Strategic | Requires all personas; trade-offs; multi-step execution plan. | Full orchestration: decompose, dispatch, synthesize, present options with trade-offs. |

### Scoring Heuristics

- Count the number of distinct data domains touched. Each domain maps to one persona.
- If the request contains words like "impact on," "trade-off," or "compared to," bump the score by 1.
- If the request requires an execution plan (not just analysis), bump the score by 1.
- Cap at 5.

---

## 6-Persona Routing Matrix

| Domain | Primary Persona | Secondary | Escalation Trigger |
|--------|----------------|-----------|-------------------|
| Budget, spending, cash flow | Household Comptroller | Chief of Staff (awareness) | Net worth crosses threshold |
| Portfolio, risk, markets | Investment Officer | Comptroller (tax overlay) | ES > 2.5% or illiquidity > 25% |
| Estate, entities, ownership | Estate Counsel | Investment Officer (valuation) | Entity restructuring |
| Health, fitness, medical | Wellness Advisor | Chief of Staff (scheduling) | Anomaly flags |
| Household ops, inventory | Household Director | Chief of Staff (triage) | Maintenance overdue |
| Email, calendar, filing, coordination | Chief of Staff | All (as needed) | Multi-persona synthesis |

---

## Multi-Agent Synthesis Framework

When a request scores 3+ on the complexity rubric, follow this protocol:

### Step 1: Decompose
Chief of Staff breaks the request into discrete sub-tasks. Each sub-task must:
- Map to exactly one persona.
- Specify the expected output format.
- Identify dependencies on other sub-tasks (if any).

### Step 2: Route
Dispatch sub-tasks to owning personas:
- Independent sub-tasks run in parallel.
- Dependent sub-tasks run in dependency order; upstream results are passed as context.

### Step 3: Produce
Each persona produces their scoped output using their own MCP tools. Personas must:
- Stay within their domain boundaries.
- Tag every fact with the MCP tool that produced it.
- Flag any assumptions or data gaps.

### Step 4: Synthesize
Chief of Staff collects all persona outputs and:
- Resolves conflicts using the canonical source rules (see routing-matrix.md).
- Identifies cross-domain implications that no single persona would surface.
- Structures the unified answer with clear section attribution.

### Step 5: Present with Provenance
Final output must:
- Tag each fact with the producing persona and MCP source tool.
- Separate facts from recommendations.
- Surface any unresolved conflicts or data gaps.

---

## Anti-Patterns

These are common orchestration mistakes. Avoid them.

| Anti-Pattern | Why It's Wrong | Correct Approach |
|-------------|---------------|-----------------|
| Over-routing | Routing to multiple personas when one can answer wastes latency and context. | Score first. If score is 1-2, route to one persona. |
| Duplicate tool calls | Two personas calling the same MCP tool produces redundant work and potential conflicts. | Assign each tool call to exactly one persona; share the result. |
| Synthesis without provenance | Unattributed facts cannot be audited or corrected. | Every fact gets a `[Persona: tool_name]` tag. |
| Premature escalation | Escalating complexity-1 requests to multi-persona synthesis. | Only escalate when the scoring rubric demands it. |
| Sequential when parallel is possible | Running independent sub-tasks sequentially wastes time. | Identify dependencies explicitly; parallelize everything else. |
| Persona boundary violations | A persona calling tools outside their domain. | Enforce domain boundaries; route cross-domain needs through Chief of Staff. |
