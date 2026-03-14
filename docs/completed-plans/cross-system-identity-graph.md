# Cross-System Identity Graph + Lightweight Request Tier

## Context

The llmenron → StewardOS implementation is complete (verified through 6 rounds of Codex review). Comparing the architecture against the exchange's conclusions about AI/human coworker coordination substrates revealed three structural gaps. Gap 3 (actor identity on work items) is already adequately addressed by `Case.lead_alias` + `Case.reply_actor` + `structured_input` injection into all 3 prompt sites. This plan addresses the remaining two gaps:

**Gap 1 — No cross-system identity graph.** When a workstream spans multiple email threads, documents, and Plane items, there's no canonical place to record that topology. Linkage is inline (`Case.thread_id` links Gmail to Plane) but not queryable as a graph.

**Gap 2 — No lightweight request tier.** The architecture is binary: either direct reply (no tracking) or full Case + Plane delegation. Quick requests that merit traceability but not a Plane project get no operational record.

The exchange's core conclusion: *"Treat API/MCP search as the recall mechanism and Postgres linkage fields as the memory mechanism."*

---

## Change 1: Cross-System Identity Graph (3 tables)

### Schema

Add to `session_store.py` after the `Case` model:

**`WorkItemNode`** — registers canonical internal work objects:
```
work_item_nodes:
  node_id       TEXT PK          -- uuid4, synthetic graph identity
  node_type     TEXT NOT NULL     -- 'case', 'request'
  internal_id   TEXT NOT NULL     -- case_id or request_id
  workspace     TEXT              -- workspace_slug for scoping
  project_id    TEXT              -- Plane project for scoping
  title         TEXT              -- human-readable label
  status        TEXT              -- mirrors source record status
  created_at    _TimestampVariant
  updated_at    _TimestampVariant
  UNIQUE(node_type, internal_id)
```

**`ExternalObject`** — references objects in external systems:
```
external_objects:
  ext_id        TEXT PK          -- uuid4
  system        TEXT NOT NULL     -- 'gmail', 'paperless', 'sharepoint', 'gdrive'
  system_id     TEXT NOT NULL     -- conversationId, document_id, driveItem_id
  display_label TEXT              -- human-readable
  metadata      _JsonVariant      -- optional system-specific data
  created_at    _TimestampVariant
  UNIQUE(system, system_id)
```

**`Edge`** — typed relations between nodes and/or external objects:
```
edges:
  edge_id         TEXT PK        -- uuid4
  relation_type   TEXT NOT NULL   -- 'spawned_from', 'branch_of', 'related_to',
                                  -- 'evidence_for', 'attachment_of', 'supersedes',
                                  -- 'duplicate_of', 'promoted_to'
  source_node_id  TEXT FK → work_item_nodes.node_id (nullable)
  source_ext_id   TEXT FK → external_objects.ext_id (nullable)
  target_node_id  TEXT FK → work_item_nodes.node_id (nullable)
  target_ext_id   TEXT FK → external_objects.ext_id (nullable)
  metadata        _JsonVariant
  created_at      _TimestampVariant
  CHECK: exactly one of (source_node_id, source_ext_id) is NOT NULL
  CHECK: exactly one of (target_node_id, target_ext_id) is NOT NULL
```

### ORM Notes

- Use `_JsonVariant` and `_TimestampVariant` for cross-dialect compatibility (existing pattern)
- Edge CHECK constraints via `__table_args__` `CheckConstraint` — works in both Postgres and SQLite
- FK constraints silently ignored in SQLite (no `PRAGMA foreign_keys = ON` set) — acceptable, FKs are a Postgres safety net
- All PKs are `uuid.uuid4()` strings generated in SessionStore methods (not ORM defaults) for SQLite compat

### SessionStore Methods

```python
# ── Graph ──
register_node(node_type, internal_id, workspace=None, project_id=None, title=None, status=None) → str
    # Upsert on (node_type, internal_id). Returns node_id. Idempotent.

register_external_object(system, system_id, display_label=None, metadata=None) → str
    # Upsert on (system, system_id). Returns ext_id. Idempotent.

create_edge(relation_type, *, source_node_id=None, source_ext_id=None,
            target_node_id=None, target_ext_id=None, metadata=None) → str
    # Creates edge. Validates exactly one source and one target. Returns edge_id.

get_edges_for_node(node_id) → list[dict]
    # All edges where node is source or target, with linked object data.

get_node_by_internal_id(node_type, internal_id) → dict | None
    # Lookup by natural key.
```

### Auto-Population

Private helper called from `upsert_case` when `duplicate=False`:

```python
_register_case_graph(case_id, thread_id, message_id, workspace_slug, project_id, title)
```

This:
1. Registers a `WorkItemNode(node_type='case', internal_id=case_id)`
2. If `thread_id` is provided, registers an `ExternalObject(system='gmail', system_id=thread_id)`
3. Creates a `spawned_from` edge: Case node → Gmail external object

**Failure isolation**: Wrapped in try/except — if graph registration fails, the Case is still committed and delegation proceeds. Log the error, do not re-raise.

### Integration Point

**`main.py` ~line 1406** (after `upsert_case` returns `duplicate=False`):
```python
if not upsert_result["duplicate"]:
    await SessionStore._register_case_graph(
        case_id=case_id,
        thread_id=email.thread_id,
        message_id=email.message_id,
        workspace_slug=home_workspace,
        project_id=project_id,
        title=email.subject,
    )
```

---

## Change 2: Lightweight Request Tier

### Schema

**`Request`** — tracked-but-lightweight work that doesn't justify a Plane project:
```
requests:
  request_id         TEXT PK           -- uuid4
  source_system      TEXT NOT NULL      -- 'gmail', 'plane_webhook', 'scheduled'
  source_object_id   TEXT               -- gmail message_id, etc.
  requester          TEXT               -- sender email or system name
  assigned_agent     TEXT NOT NULL      -- persona alias
  status             TEXT NOT NULL DEFAULT 'open'  -- 'open', 'resolved', 'promoted'
  urgency            TEXT DEFAULT 'normal'          -- 'low', 'normal', 'high', 'urgent'
  summary            TEXT               -- brief description (email subject)
  resolution         TEXT               -- how resolved (truncated response_text)
  promoted_to_case_id TEXT FK → cases.case_id (nullable)
  thread_id          TEXT               -- Gmail thread for graph linkage
  created_at         _TimestampVariant
  resolved_at        _TimestampVariant
  updated_at         _TimestampVariant
```

### SessionStore Methods

```python
# ── Requests ──
create_request(*, source_system, assigned_agent, requester=None, source_object_id=None,
               summary=None, urgency='normal', thread_id=None) → dict
    # Creates request + registers graph node + external object edge. Returns {request_id, ...}.

resolve_request(request_id, resolution=None) → None
    # Sets status='resolved', resolved_at=now, updates node status.

promote_request(request_id, case_id) → None
    # Sets status='promoted', promoted_to_case_id=case_id.
    # Creates 'promoted_to' edge: request node → case node.

get_request(request_id) → dict | None

get_open_requests(assigned_agent=None) → list[dict]
    # All open requests, optionally filtered by agent.
```

### Auto-Tracking Integration

**`main.py` ~line 1462** (in the standard reply flow, after `record_message_result` with `status="sent"`):

```python
# Auto-track direct replies as lightweight requests for traceability
try:
    req = await SessionStore.create_request(
        source_system="gmail",
        source_object_id=email.message_id,
        assigned_agent=alias,
        requester=email.sender_email,
        summary=email.subject[:200],
        thread_id=email.thread_id,
    )
    await SessionStore.resolve_request(
        req["request_id"],
        resolution=f"Direct reply by +{alias}",
    )
except Exception:
    logger.debug("Request auto-tracking failed for %s", email.message_id[:24], exc_info=True)
```

This creates and immediately resolves a request record for every direct reply, providing a queryable audit trail without affecting the reply flow. Failures are silently logged at debug level.

---

## Files to Modify

| File | Change |
|------|--------|
| `agents/family-office-mail-worker/src/session_store.py` | Add 4 ORM models (`WorkItemNode`, `ExternalObject`, `Edge`, `Request`); add ~10 new SessionStore classmethods; add `import uuid`; add `_register_case_graph` private helper |
| `agents/family-office-mail-worker/src/main.py` | Call `_register_case_graph` after Case creation (~line 1406); add request auto-tracking in standard reply flow (~line 1462) |
| `agents/family-office-mail-worker/migrations/002_cross_system_graph.sql` | DDL for all 4 new tables with indexes and CHECK constraints |
| `agents/family-office-mail-worker/tests/test_graph_and_requests.py` | New test file: ~12 test cases |

## Existing Code to Reuse

- `_JsonVariant` and `_TimestampVariant` type aliases (`session_store.py:23-24`)
- `_utcnow()` helper (`session_store.py:27-28`)
- `Base = declarative_base()` (`session_store.py:19`)
- `SessionStore.initialize()` with `create_all()` — new tables auto-created (`session_store.py:167-182`)
- `_reset_session_store(tmp_path)` test helper pattern (`test_delegation.py:20-23`)
- `asyncio.run()` sync test pattern (`test_delegation.py`)

## NOT Changing

- **Case model** — no schema changes; graph auto-population is additive
- **Plane MCP** — no new tools; agents interact with graph indirectly via worker
- **Delegation flow** — only additive graph registration after existing `upsert_case`
- **Poller / specialist flow** — no changes in this phase
- **Actor identity (Gap 3)** — already addressed by Case.lead_alias + reply_actor

---

## Deployment Context

**Live Postgres**: home-server `personal-db` (Postgres 16.6) at remote `5433`, tunneled to local `localhost:5434` via `home-server-db-tunnel.service`. The `orchestration` database has 6 deployed tables created by SQLAlchemy `create_all()` (not by the `001_initial.sql` migration DDL).

**Config**: `config.py` default is `localhost:5433` but live worker uses env var override pointing at the correct tunnel port. Migration scripts should be run against `localhost:5434`.

**Worker service**: Local `family-office-mail-worker.service` on `127.0.0.1:8312`. Restart via `systemctl --user restart family-office-mail-worker.service` after code changes.

**Current deployed tables** (verified via `\dt orchestration.*`):
- `cases`, `email_sessions`, `gmail_watch_state`, `processed_gmail_messages`, `processed_plane_deliveries`, `queued_gmail_notifications`

The 4 new tables (`work_item_nodes`, `external_objects`, `edges`, `requests`) will be created by SQLAlchemy `create_all()` on next worker restart, but `002_cross_system_graph.sql` should also be run for indexes and CHECK constraints.

---

## Verification

1. **Tests**: `cd agents/family-office-mail-worker && uv run pytest` — all existing + new tests pass on SQLite
2. **Schema**: Restart worker service, verify 4 new tables created in `orchestration` schema: `psql "postgresql://orchestration:changeme@localhost:5434/orchestration" -c "\dt orchestration.*"` shows 10 tables
3. **Migration**: Run `002_cross_system_graph.sql` against live DB: `psql "postgresql://orchestration:changeme@localhost:5434/orchestration" -f migrations/002_cross_system_graph.sql`
4. **Graph population**: Process a delegation email, verify `work_item_nodes` + `external_objects` + `edges` populated
5. **Request tracking**: Process a direct reply email, verify `requests` table has a resolved record
6. **Idempotency**: Re-delegate on same thread, verify graph node upsert is idempotent (no duplicate nodes)
7. **Failure isolation**: Simulate graph registration failure, verify Case is still created and delegation proceeds
8. **Regression**: `make test-all` passes across the monorepo
