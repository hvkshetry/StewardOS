# Fixed-Workspace Plane Control Plane — Vetting & Implementation Plan

## Context

This plan introduces Plane as the PM substrate for StewardOS's agent-human task management, keeping email as ingress/egress and the lead agent as orchestration authority. The review below vets the original proposal against the actual codebase state, Plane's current capabilities, home-server resource constraints, and persona domain boundaries — then recommends a revised approach.

### Key Decisions (confirmed with user)
- **Workspaces are domain-scoped** — named by domain, not persona. Future persona splits stay within existing workspaces.
- **Insurance Advisor** included in Phase 1 — all required MCPs exist, high-value gap.
- **Research Analyst** split from Investment Officer — shares `investment-office` workspace.
- **Scheduled briefs** stay with Portfolio Manager (keeps `io` alias). Research Analyst is on-demand only.
- **Tax Advisor** deferred — Comptroller handles it well; `household-tax-mcp` only supports 2026 US+MA. Revisit when multi-state or international tax enters scope.

---

## Part 1: Plane Platform Vetting

### 1A. Webhook Status (Revised Assessment)

**Original concern:** GitHub issue [#6746](https://github.com/makeplane/plane/issues/6746) — API-created work items don't trigger webhooks.

**Research finding:** The bug was **effectively fixed in v0.26.0** (April 2025, commit `bfc6ed83`). The reporter was on v0.25.2. Current Plane v1.2.x **does emit webhooks for API `POST` (create) operations**. Remaining gaps:
- `PUT` (update) on external API — still missing `model_activity.delay()` call
- `DELETE` on external API — PR [#8055](https://github.com/makeplane/plane/pull/8055) pending

**Webhook emission architecture:** Explicit `model_activity.delay()` calls in view code → Celery chain: `model_activity` → `webhook_activity` → `webhook_send_task`. No Django signals involved. Patching missing endpoints is surgical (~10-20 lines per endpoint).

**Recommended event strategy (hybrid webhook + polling):**
1. **Webhooks for CREATE events** — works on v1.2.x out of the box. Lead agent creates a task → webhook fires → ingress receives → routes to specialist.
2. **`updated_at__gt` polling for UPDATE/DELETE events** — Plane's `/work-items/` API supports `updated_at__gt` filtering. Poll every 5 minutes per workspace. Cost: 7 workspaces × 12 polls/hour = 84 req/hour (~1.4 req/min), well within rate limits.
3. **Optional future patch** — When Plane merges #8055 (DELETE fix) and we submit a similar PR for PUT, webhooks cover all mutation types and polling becomes a reliability fallback only.

**This unblocks agent-to-agent collaboration in Phase 1:**
- Lead agent creates specialist task → CREATE webhook fires → ingress notifies specialist
- Specialist completes task (state update) → caught by 5-min poll → lead agent resumes
- Acceptable latency: ≤5 minutes for task completion notification (fine for family office cadence)

### 1B. Rate Limits (REVISED per Codex vetting + follow-up research)

- **60 req/min per API key** (default). Rate limit is keyed by the literal API key string, not by user or instance.
- **Workspace-scoped bot tokens are Commercial-only** (Pro tier, $6/seat/month). Not available on self-hosted Community Edition.
- **Mitigation (confirmed viable):**
  1. **Self-hosted rate limit override:** Set `API_KEY_RATE_LIMIT` env var on plane-api to raise the default (e.g., `300/minute`). This is the simplest fix for a single-user family office.
  2. **Multiple service-account PATs:** Create 2-3 Plane user accounts for agent use, each generating a PAT with an independent 60/min bucket. plane-mcp rotates across PATs.
  3. Polling budget: ~1.4 req/min (negligible)
  4. Cache workspace/project/state lookups to reduce discovery reads
- **Recommendation:** Use option 1 (raise `API_KEY_RATE_LIMIT` to 300/min). It's a single env var on a self-hosted instance you control. No need for multiple accounts or commercial licensing.

### 1C. home-server RAM Strategy: Drop Subsumed Services, Keep Full Plane

Current Docker allocation: **7.53 GB** of 16 GB (47%). OS + systemd: ~2-3 GB. Free: ~5.5-6.5 GB.

The Plane web UI is essential for human-agent collaboration (epic/task assignment, progress visibility). Rather than stripping Plane, **drop services that a fully functional Plane instance subsumes:**

**Services to drop (Plane subsumes their function):**

| Service | Memory | Plane Replacement | Migration |
|---------|--------|-------------------|-----------|
| **n8n** | 256 MB | Lead-agent orchestration + Plane task automation | No active workflows to migrate. Already "out of critical path." |
| **directus** | 512 MB | Plane provides human work visibility; estate-planning-mcp provides data access | Human estate graph browsing moves to Plane views or ad-hoc MCP queries. Revisit if raw graph browsing is missed. |
| **changedetection** | 512 MB | Not subsumed, but zero agent integration | No migration needed. Pure human dashboard — re-add later if missed. |

**Total freed: 1,280 MB (1.25 GB)** (memos kept; see note below)

**Full Plane deployment (reusing shared DB + Redis):**

| Container | Purpose | mem_limit |
|-----------|---------|-----------|
| plane-web | React frontend (workspace UI) | 256m |
| plane-admin | Instance administration UI | 128m |
| plane-space | Public project pages | 128m |
| plane-api | Django REST API | 512m |
| plane-worker | Celery worker (webhooks, activities) | 256m |
| plane-beat | Celery beat (periodic tasks) | 64m |
| plane-migrator | One-shot DB migration | 128m |
| plane-live | Real-time collaboration (WebSocket) | 256m |
| plane-mq | RabbitMQ | 256m |
| plane-minio | S3-compatible object storage | 256m |
| plane-proxy | Nginx reverse proxy | 32m |

**Additional: dedicated Plane Valkey instance (not shared Redis):**

| Container | Purpose | mem_limit |
|-----------|---------|-----------|
| plane-valkey | Dedicated Valkey 7.2 for Plane (cache + Celery + live pubsub) | 256m |

Codex vetting found that sharing the existing `personal-redis` (200mb, `allkeys-lru`) is unsafe — Plane needs a non-evicting Redis for Celery task queues and live pubsub. A dedicated Plane Valkey instance avoids interference with existing services.

**Shared PostgreSQL: viable with tuning.** No PG extensions required. Add `max_connections=1000` to `personal-db` command (Plane's default). No PG16→PG15 incompatibility found, but test migrations before enabling agent traffic.

**Total Plane: ~2.6 GB** (dedicated Valkey, shared PostgreSQL with tuning)

**Revised RAM budget:**

| Layer | Allocation |
|-------|-----------|
| Existing Docker (after dropping 4 services) | ~6.0 GB |
| Full Plane (12 containers: 11 app + dedicated Valkey) | ~2.6 GB |
| OS + systemd (ingress, cloudflared, SSH) | ~2.5 GB |
| **Total** | **~11.1 GB** |
| **Buffer** | **~4.9 GB** |

Workable headroom. If `docker stats` shows pressure, first action: raise `plane-api` and `plane-worker` mem_limits to K8s defaults (1000Mi each) and drop `plane-admin` + `plane-space` (admin on-demand, no public pages). Verify under load before enabling agent traffic.

> **Codex caveat:** K8s defaults for Plane services are 1000Mi each. The 512m/256m caps above are aggressive. Start there but be ready to increase if OOM kills appear.

**Memos: KEEP for now (REVISED per Codex vetting).**
- `plane-sdk` only exposes `pages.list` / `pages.retrieve` — no create/update/delete
- Plane Pages are project-scoped (not workspace-scoped), which is a poor fit for cross-project notes
- Keep Memos running (256 MB) until Pages write path is proven via raw HTTP or SDK patch
- Remove Memos from the "services to drop" list; total freed becomes **1,280 MB (1.25 GB)** instead of 1.5 GB
- Revisit Memos→Pages migration in Phase 2 once Pages CRUD is validated

### 1D. Ontology Mapping (REVISED per Codex vetting)

**Epic CREATE is not available in the public API** — only list/retrieve. `plane-sdk` also lacks epic create/update/delete. The original Case=Epic mapping is not viable for agent-driven creation.

**Revised mapping: Case = top-level Work Item with `case` label; Task = child Work Item.**

| Plan Term | Plane Entity | API Endpoint |
|-----------|-------------|-------------|
| Workspace | Workspace | `/api/v1/workspaces/` |
| Project | Project | `/api/v1/workspaces/{slug}/projects/` |
| Case | **Work Item** (top-level, labeled `case`) | `/api/v1/workspaces/{slug}/projects/{id}/work-items/` |
| Task | **Child Work Item** (via `parent` field) | `/api/v1/workspaces/{slug}/projects/{id}/work-items/` with `parent={case_id}` |
| Sub-task | Grandchild Work Item | Nested via `parent` field (unlimited depth) |

Hierarchy: `Workspace > Project > Work Item [label=case] > Child Work Item [label=agent-task|human-task]`

This uses fully supported CRUD endpoints. A `case` label distinguishes root cases from leaf tasks. Revisit Epics if Plane exposes public create/update in a future release.

### 1E. API Terminology

All `/issues/` endpoints deprecated. **Cutoff: March 31, 2026** (3 weeks). Implementation uses `work-items` exclusively via `plane-sdk` v0.2.x (already migrated).

### 1F. MCP Server Assessment

Official Plane MCP (v0.2.5, 55+ tools) is too broad for governance — exposes workspace CRUD, project deletion, bulk ops. **Build narrow first-party wrapper** using `plane-sdk` for HTTP, exposing only governance-safe tools.

---

## Part 2: Workspace Taxonomy

### 2A. Domain-Scoped Workspaces (7 total)

All workspaces named by **domain**, not persona. Future persona splits stay within existing workspaces without structural changes.

| Workspace Slug | Domain | Current Persona(s) | Future Split Candidates |
|----------------|--------|--------------------|-----------------------|
| `chief-of-staff` | Operations & administration | Chief of Staff | Facilities Manager (if property portfolio grows) |
| `estate-counsel` | Legal, entities, succession | Estate Counsel | — |
| `household-finance` | Cash, budget, tax, statements | Household Comptroller | Tax Counsel (when international tax enters scope) |
| `household-ops` | Meals, grocery, child dev | Household Director | — |
| `investment-office` | Portfolio, markets, research | Portfolio Manager, Research Analyst | Private Markets Lead (if cadence warrants) |
| `wellness` | Health, fitness, nutrition, medical | Wellness Advisor | Fitness Coach / Medical Advisor (if complexity grows) |
| `insurance` | Policies, claims, coverage | Insurance Advisor (new) | — |

### 2B. Cross-Domain Collaboration Rules

- Lead agent always owns the root case and all child tasks in its **home workspace/project** (Plane requires parent/child to be in the same project)
- Cross-domain work: lead agent creates child **tasks** in its own project and routes them through Plane coordination state (`route_to`, `coordination_status`, `reply_identity`) rather than `target_alias:*` labels
- Specialist executes using its own workspace's tools and skills, but the Plane work item tracking stays in the lead's project
- Specialist results are posted as Plane comments on the child work item; the polling loop fetches comments for the lead's resume prompt
- No agent creates cases outside its home workspace without human approval

### 2C. Persona Changes

**New: Insurance Advisor (`insurance` alias)**
- MCP wiring: paperless, finance-graph (read), estate-planning (read), actual-budget (read), google-workspace
- Skills: policy-inventory, coverage-review, claims-tracker, renewal-calendar, family-email-formatting
- Home workspace: `insurance`

**New: Research Analyst (`ra` alias)**
- MCP wiring: market-intel-direct, sec-edgar, policy-events, finance-graph (read), google-workspace
- Skills: market-briefing, comps-analysis, dcf-model, unit-economics, returns-analysis, family-email-formatting
- Home workspace: `investment-office`
- No scheduled briefs (on-demand only, triggered by PM delegation or direct email)

**Modified: Investment Officer → Portfolio Manager (keeps `io` alias)**
- Remove 5 research skills (market-briefing, comps-analysis, dcf-model, unit-economics, returns-analysis)
- Retains: risk-model-config, practitioner-heuristics, portfolio-review, rebalance, tax-loss-harvesting, client-report, investment-proposal, illiquid-valuation, portfolio-monitoring, dd-checklist, value-creation-plan
- Keeps both scheduled briefs (Monday pre-market, Friday post-close)
- Home workspace: `investment-office`

**Unchanged:** Chief of Staff, Estate Counsel, Household Comptroller, Household Director, Wellness Advisor

**Tax Advisor: DEFERRED.** `household-tax-mcp` only supports 2026 US+MA. Comptroller handles tax compliance well with 7 skills at moderate load. Splitting would fragment the tightly coupled monthly-close + tax-planning workflow. Revisit when international tax (FBAR/FATCA for India assets) or multi-state support is added.

---

## Part 3: Implementation Status

### Phase 0 — Infrastructure ✅ COMPLETE

Deployed March 2026. Dropped n8n, directus, changedetection (saved 1.25 GB). Added 12 Plane containers (plane-api, plane-worker, plane-beat, plane-web, plane-admin, plane-space, plane-live, plane-proxy, plane-migrator, plane-mq, plane-minio, plane-valkey) to `services/docker-compose.yml`. Total stack: 26 Docker services.

Key deployment details:
- Plane v1.2.3 Community Edition, Caddy-based proxy (not nginx) with Docker network aliases for hostname resolution
- Dedicated `plane-valkey` (non-evicting) — not shared with `personal-redis`
- Shared `personal-db` with `max_connections=1000` and `plane` database
- RabbitMQ with `RABBITMQ_DEFAULT_VHOST=plane`, user/password via env vars (`RABBITMQ_USER`/`RABBITMQ_PASSWORD` for Plane Django, `RABBITMQ_DEFAULT_USER`/`RABBITMQ_DEFAULT_PASS` for RabbitMQ container)
- `WEB_URL=https://pm.stewardos.example.com`, `CORS_ALLOWED_ORIGINS`, `GUNICORN_WORKERS=1`, `API_KEY_RATE_LIMIT=300/minute`
- Memory limits tuned from plan: plane-worker 512m, plane-beat 128m, plane-space 192m (bumped from initial aggressive caps)
- Measured: Docker total ~3.1 GB, system 7.1/15 GB used, 8.4 GB available
- 7 workspaces created in Plane UI, single admin PAT verified across all workspaces
- Labels are project-scoped (not workspace-scoped as originally planned) — `plane-pm`'s `create_project` will auto-create labels
- All provisioning scripts updated: `deploy.sh`, `deploy-local.sh`, `setup-tunnel.sh`, `CLAUDE.md`, `backup-personal.sh`, `.env.example`, `cloudflared/config.yml.template`, `AI_AGENT_ARCHITECTURE_PRIMER.md`

### Phase 0.5 — Plane MCP Server (`plane-pm`) ✅ COMPLETE

Built `servers/plane-mcp/` with `FastMCP("plane-pm")` and `get_client()` DI pattern. 14 tools across 4 modules:

- **Discovery** (5): `list_workspaces`, `list_projects`, `get_project_bundle`, `get_case_bundle`, `get_task_bundle`
- **Creation** (3): `create_case`, `create_agent_task`, `create_human_task`
- **Execution** (4): `update_task_state`, `add_task_comment`, `complete_task`, `attach_external_link`
- **Projects** (2): `create_project`, `get_project`

Governance: no workspace CRUD exposed, home-workspace validation on writes, cross-workspace delegation logged. SDK-based calls use `plane-sdk` v0.2.x; direct HTTP calls (comments, links) use upstream `/issues/` paths. Tests in `tests/` with FakeMCP + mock client.

**Accepted deviation from plan:** Credentials distributed to each persona config (not centralized behind one worker service account). This follows from the persona-owns-writes architecture — each persona's `plane-pm` server instance reads `PLANE_API_TOKEN` from its own env. The single admin PAT is the same token, just injected per-persona.

### Phase 1 — Worker Integration + New Personas ✅ COMPLETE

**ActionAck unification:** Unified `SendAck`/`MaintenanceAck` into `ActionAck(action: Literal["reply", "delegate", "maintenance"])` with `human_update_html` field. Old models cleanly removed; extraction uses `ACTION_ACK_JSON:` marker exclusively.

**PM session tables:** Added to `session_store.py`: `pm_sessions`, `processed_plane_deliveries`, `email_thread_cases`, `case_snapshots` (for session resume durability).

**Plane polling loop:** `plane_poller.py` polls project-scoped `/work-items/?updated_at__gt={ts}` per workspace on 5-min interval. Reads Plane parent/child work item hierarchy to detect case completion, fetches specialist results from comments, resumes lead-agent sessions. Unified dedupe key prevents double-processing with webhooks.

**Webhook ingress:** `POST /webhooks/plane` on ingress with HMAC-SHA256 verification, stateless forwarding to worker. Worker handler at `/internal/family-office/plane-webhook` with delivery-ID idempotency. Webhook payload reads workspace `slug` from top level.

**Delegation flow:** Worker is a thin event router. Personas create Plane items and send progress emails directly via `plane-pm` tools; worker records PM session metadata (case, thread link, snapshot) for polling/resume. Delegation governance enforced via system prompts and `plane-pm` tool-level `PLANE_HOME_WORKSPACE` validation.

**Accepted deviation from plan:** Personas own Plane writes (not worker). The plan originally called for worker-owns-writes to keep Plane credentials out of persona configs. The implemented design has personas call `plane-pm` tools directly, which is simpler and avoids the worker becoming a bottleneck. Trade-off: each persona needs the API token in its config.

**New personas:**
- Insurance Advisor (`insurance`): config, AGENTS.md, 4 skills (policy-inventory, coverage-review, claims-tracker, renewal-calendar). Paperless taxonomy is documentation-only (tags created on first use via MCP).
- Research Analyst (`ra`): config, AGENTS.md, 5 skills (market-briefing, comps-analysis, dcf-model, unit-economics, returns-analysis) — moved from Investment Officer.
- Investment Officer → Portfolio Manager: 5 research skills removed, skill docs updated to delegate to RA via Plane.

**Plane wired to all 8 personas** via `[mcp_servers.plane-pm]` with correct `PLANE_HOME_WORKSPACE` per config.

### Phase 2 — Maturation

#### Wave 1: ✅ COMPLETE (March 2026)

55 tools across 11 modules, 117 tests. Codex-verified (two review passes, all PASS).

| Task | Tools Added | Notes |
|------|------------|-------|
| **2.0** SDK cleanup | — | Comments migrated to SDK in execution.py + discovery.py. `attach_external_link` stays HTTP (SDK drops title). |
| **2B** Cycles/Modules | 9 | `cycles.py` (5): list, create, add/remove membership, progress. `modules.py` (4): list, create, add/remove membership. All use plane-sdk. |
| **2C** Due dates + overdue | 2 | `create_human_task` gained `due_date`/`start_date`. `list_overdue_tasks` added to discovery.py. Milestones deferred (no server routes). |
| **2E** Attachments | 2 | `attach_paperless_document` (metadata-rich link) + `attach_work_item_file` (SDK `WorkItemAttachmentUploadRequest`) in execution.py. |
| **2F** Pages | 6 | `pages.py`: list, create (SDK), get (SDK), update, archive, delete. Per-project strategy. SDK for create/get, HTTP for list/update/archive/delete. |
| **2H** Coordination | 7 | `coordination.py`: list_project_members, list_workspace_members, search_work_items, list/create/update intake, get_work_item_history (SDK activities — documented deviation from plan's `/issues/history/`). |
| **2I** Management/Views/Estimates | 17 | `management.py` (7): states CRUD + labels CRUD. `views.py` (5): list/create/get/update/delete via HTTP. `estimates.py` (5): list/create/get/update/delete via HTTP. |

**Governance model:** All structural write tools (create/update/delete on cycles, modules, pages, intake, states, labels, views, estimates) validate `PLANE_HOME_WORKSPACE` and reject cross-workspace writes. Execution tools (state transitions, comments, attachments, links) intentionally allow cross-workspace writes for delegation flows.

**Accepted deviations:**
- `attach_external_link` uses direct HTTP (SDK `CreateWorkItemLink` drops `title` field via `extra="ignore"`)
- `get_work_item_history` uses SDK `work_items.activities.list()` instead of `/issues/{id}/history/` (activities is the correct public API for audit trail data)
- `create_cycle` sends `owned_by=""` (server fills authenticated user)

**Not implemented (deferred per plan):**
- 2A (webhook emission patch) — upstream PR #8055 still open; polling covers gap
- Tier 2 cycle/module tools (update, delete, archive, transfer)
- Due-date reminder email templates
- Memos→Pages skill migration for Chief of Staff
- `manage_relations`, `milestones`, `custom_properties`, `notifications_inbox` — API routes missing in v1.2.3

---

#### Wave 2: Depends on Wave 1 or upstream changes

##### 2D. Delegation scope control ✅ COMPLETE (March 2026)

**Architecture: Prompt-based governance with Plane as single source of truth.**

After implementing and reviewing a code-level A2A pre-hoc approval model (DelegationEdge, DelegationApproval, reserve_approval endpoint, plan-hash verification), the entire policy machinery was deliberately stripped in favor of system prompt instruction following. Guiding philosophy: *assume SOTA LLMs will continue improving in instruction following — use system prompts/skills in place of code where possible.*

**What was deleted (intentionally superseded):**
- `delegation.py` module, `DelegationEdge`/`DelegationApproval` models, `DelegationTaskItem` model
- `reserve_approval_endpoint`, `compute_plan_hash`, `count_case_tasks`, `reserve_approval`, `verify_and_consume_approval`
- `create_delegation_edge`, `create_delegation_edges_batch`, `get_delegation_edges`, `store_delegation_result`, `resolve_delegation_edge`
- `MAX_DELEGATION_DEPTH`, `MAX_TASKS_PER_CASE`, A2A protocol prompt injection, sub-delegation branch, `approval_id`/`task_plan` on ActionAck

**What remains (transport bridges):**
- `PmSession`, `EmailThreadCase`, `CaseSnapshot`, `ProcessedPlaneDelivery` — session persistence + idempotency
- Plane polling loop reads parent/child work item hierarchy directly from Plane API
- Specialist results posted as Plane comments; poller fetches comments for lead resume prompt
- Duplicate resume guard: poller skips closed PM sessions

**Scope controls (prompt-enforced):**
- Delegation norms in persona system prompts (AGENTS.md)
- `plane-pm` tool-level `PLANE_HOME_WORKSPACE` validation rejects cross-workspace structural writes
- Execution tools intentionally allow cross-workspace writes for delegation flows

##### 2G. API endpoint migration (`/issues/` → `/work-items/`)
- Documented March 31, 2026 deprecation cutoff — **no evidence of extension**.
- v1.2.3 source still ships both `old_url_patterns` and `new_url_patterns`.
- Open SDK PR [#18](https://github.com/makeplane/plane-python-sdk/pull/18) proposes reverting SDK from `/work-items/` to `/issues/`.
- **Split approach (per Codex, independently validated):**
  - Use SDK / `/work-items/` for: work items, comments, links, attachments, activities (all have public API routes)
  - Keep `/issues/` for: relations, history, subscribers, intake (app-level only or route gaps)
- **Action:** After Wave 1 SDK cleanup (2.0), remaining `/issues/` calls will be only for features without `/work-items/` equivalents. Pin SDK `>=0.2.0,<0.3.0`. Monitor next Plane release.

##### 2J. Relations and dependency graphs
- Blocked: SDK wraps `work_items.relations` but v1.2.3 routes don't exist on `/work-items/`. App-level routes at `/issues/{id}/issue-relation/` do work.
- **Action:** Build relation tools using app-level `/issues/` paths. Supports: `relates_to`, `is_blocked_by`, `blocks`, `is_duplicate_of`. Enables dependency graphs for complex projects.
- Migrate to SDK calls when `/work-items/` relation routes appear in a future Plane release.

---

## Part 4: Risk Register

| Risk | Severity | Mitigation | Status |
|------|----------|------------|--------|
| Webhooks missing for PATCH/DELETE | **MEDIUM** | `updated_at__gt` polling covers gaps; unified dedupe key; upstream PR #8055 still open | Mitigated |
| 60 req/min rate limit | **LOW** | Raised to 300/min via `API_KEY_RATE_LIMIT` env var | Resolved |
| home-server RAM pressure | **LOW** | Measured 7.1/15 GB used, 8.4 GB available | Verified |
| Shared PostgreSQL compatibility | **LOW** | Migrations succeeded on PG16 with `max_connections=1000` | Verified |
| API endpoint namespace instability | **HIGH** | SDK PR #18 shows `/work-items/` causes 404s; `/issues/` cutoff March 31 but both routes still ship in v1.2.3. Split approach: SDK for canonical, `/issues/` for legacy-only. Pin SDK version. | Active |
| SDK ahead of server | **MEDIUM** | SDK v0.2.6 wraps relations, milestones, custom properties, work-item types — but routes don't exist in v1.2.3. Must verify route existence before using SDK wrappers. | Active |
| Credential distribution | **LOW** | Single PAT injected per-persona; accepted deviation from centralized model | Accepted |
| Session resume durability | **LOW** | `case_snapshots` table implemented | Resolved |
| Memos→Pages migration | **LOW** | API has full CRUD; per-project strategy; only CoS needs skill updates | Unblocked |
| Webhook SSRF protection (v1.2.3) | **LOW** | New validation on webhook URLs with reserved IPs; PR #8732 proposes making this configurable for self-hosted | Monitor |
| Docker service count drift | **LOW** | CLAUDE.md says 26 but watchtower makes it 27; update docs | Minor fix needed |
| No workspace-level bulk list | **MEDIUM** | Only project-scoped `work_items.list()` + workspace-scoped `search()`. Cross-project queries require iterating projects. | Accepted |
