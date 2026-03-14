"""Tests for cross-system identity graph and lightweight request tier."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from conftest import get_test_database_url
from src.config import settings
from src.session_store import SessionStore


def _reset(tmp_path: Path) -> None:
    settings.database_url = get_test_database_url(tmp_path)
    asyncio.run(SessionStore.reset_for_tests())
    asyncio.run(SessionStore.initialize())


# ─── WorkItemNode Tests ───────────────────────────────────────────────


def test_register_node_creates_and_returns_id(tmp_path):
    _reset(tmp_path)
    node_id = asyncio.run(SessionStore.register_node(
        "case", "case-1", workspace="chief-of-staff", title="Test case",
    ))
    assert node_id
    node = asyncio.run(SessionStore.get_node_by_internal_id("case", "case-1"))
    assert node is not None
    assert node["node_id"] == node_id
    assert node["workspace"] == "chief-of-staff"
    assert node["title"] == "Test case"


def test_register_node_upsert_idempotent(tmp_path):
    _reset(tmp_path)
    id1 = asyncio.run(SessionStore.register_node("case", "case-1", title="v1"))
    id2 = asyncio.run(SessionStore.register_node("case", "case-1", title="v2"))
    assert id1 == id2
    node = asyncio.run(SessionStore.get_node_by_internal_id("case", "case-1"))
    assert node["title"] == "v2"


def test_register_node_different_types_separate(tmp_path):
    _reset(tmp_path)
    id1 = asyncio.run(SessionStore.register_node("case", "id-1"))
    id2 = asyncio.run(SessionStore.register_node("request", "id-1"))
    assert id1 != id2


# ─── ExternalObject Tests ────────────────────────────────────────────


def test_register_external_object_upsert(tmp_path):
    _reset(tmp_path)
    eid1 = asyncio.run(SessionStore.register_external_object(
        "gmail", "thread-abc", display_label="Thread ABC",
    ))
    eid2 = asyncio.run(SessionStore.register_external_object(
        "gmail", "thread-abc", display_label="Updated label",
    ))
    assert eid1 == eid2


# ─── Edge Tests ──────────────────────────────────────────────────────


def test_create_edge_and_retrieve(tmp_path):
    _reset(tmp_path)
    nid = asyncio.run(SessionStore.register_node("case", "c-1"))
    eid = asyncio.run(SessionStore.register_external_object("gmail", "t-1"))
    edge_id = asyncio.run(SessionStore.create_edge(
        "spawned_from", source_node_id=nid, target_ext_id=eid,
    ))
    assert edge_id
    edges = asyncio.run(SessionStore.get_edges_for_node(nid))
    assert len(edges) == 1
    assert edges[0]["relation_type"] == "spawned_from"
    assert edges[0]["source_node_id"] == nid
    assert edges[0]["target_ext_id"] == eid


def test_get_edges_includes_linked_object_data(tmp_path):
    """get_edges_for_node resolves linked external objects."""
    _reset(tmp_path)
    nid = asyncio.run(SessionStore.register_node("case", "c-linked", title="Linked case"))
    eid = asyncio.run(SessionStore.register_external_object(
        "gmail", "t-linked", display_label="Thread linked",
    ))
    asyncio.run(SessionStore.create_edge(
        "spawned_from", source_node_id=nid, target_ext_id=eid,
    ))
    edges = asyncio.run(SessionStore.get_edges_for_node(nid))
    assert len(edges) == 1
    # Should have resolved target_ext data
    assert "target_ext" in edges[0]
    assert edges[0]["target_ext"]["system"] == "gmail"
    assert edges[0]["target_ext"]["system_id"] == "t-linked"
    assert edges[0]["target_ext"]["display_label"] == "Thread linked"


def test_get_edges_includes_linked_node_data(tmp_path):
    """get_edges_for_node resolves linked nodes on the other end."""
    _reset(tmp_path)
    n1 = asyncio.run(SessionStore.register_node("request", "r-1", title="Request one"))
    n2 = asyncio.run(SessionStore.register_node("case", "c-promo", title="Promoted case"))
    asyncio.run(SessionStore.create_edge(
        "promoted_to", source_node_id=n1, target_node_id=n2,
    ))
    edges = asyncio.run(SessionStore.get_edges_for_node(n1))
    assert len(edges) == 1
    assert "target_node" in edges[0]
    assert edges[0]["target_node"]["internal_id"] == "c-promo"
    assert edges[0]["target_node"]["title"] == "Promoted case"


def test_create_edge_validates_source_xor(tmp_path):
    _reset(tmp_path)
    nid = asyncio.run(SessionStore.register_node("case", "c-1"))
    eid = asyncio.run(SessionStore.register_external_object("gmail", "t-1"))
    with pytest.raises(ValueError, match="source"):
        asyncio.run(SessionStore.create_edge(
            "bad", source_node_id=nid, source_ext_id=eid, target_node_id=nid,
        ))


def test_create_edge_validates_target_xor(tmp_path):
    _reset(tmp_path)
    nid = asyncio.run(SessionStore.register_node("case", "c-1"))
    with pytest.raises(ValueError, match="target"):
        asyncio.run(SessionStore.create_edge(
            "bad", source_node_id=nid,
        ))


# ─── Case Graph Auto-Population Tests ────────────────────────────────


def test_register_case_graph_creates_node_and_edge(tmp_path):
    _reset(tmp_path)
    asyncio.run(SessionStore._register_case_graph(
        case_id="case-g1",
        thread_id="thread-g1",
        message_id="msg-g1",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        title="Graph test case",
    ))
    node = asyncio.run(SessionStore.get_node_by_internal_id("case", "case-g1"))
    assert node is not None
    assert node["workspace"] == "chief-of-staff"
    assert node["status"] == "active"
    edges = asyncio.run(SessionStore.get_edges_for_node(node["node_id"]))
    assert len(edges) == 1
    assert edges[0]["relation_type"] == "spawned_from"


def test_register_case_graph_no_thread_skips_edge(tmp_path):
    _reset(tmp_path)
    asyncio.run(SessionStore._register_case_graph(
        case_id="case-g2",
        thread_id=None,
        message_id=None,
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        title="No thread",
    ))
    node = asyncio.run(SessionStore.get_node_by_internal_id("case", "case-g2"))
    assert node is not None
    edges = asyncio.run(SessionStore.get_edges_for_node(node["node_id"]))
    assert len(edges) == 0


def test_register_case_graph_idempotent(tmp_path):
    """Re-registering the same case doesn't create duplicate nodes or edges."""
    _reset(tmp_path)
    asyncio.run(SessionStore._register_case_graph(
        case_id="case-g3",
        thread_id="thread-g3",
        message_id="msg-g3",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        title="First",
    ))
    asyncio.run(SessionStore._register_case_graph(
        case_id="case-g3",
        thread_id="thread-g3",
        message_id="msg-g3",
        workspace_slug="chief-of-staff",
        project_id="proj-1",
        title="Second",
    ))
    node = asyncio.run(SessionStore.get_node_by_internal_id("case", "case-g3"))
    assert node is not None
    assert node["title"] == "Second"
    # Verify no duplicate edges
    edges = asyncio.run(SessionStore.get_edges_for_node(node["node_id"]))
    assert len(edges) == 1


def test_register_case_graph_failure_isolation(tmp_path):
    """Graph registration failure does not propagate — returns None silently."""
    _reset(tmp_path)
    from unittest.mock import patch, AsyncMock

    with patch.object(SessionStore, "register_node", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        # Should not raise
        asyncio.run(SessionStore._register_case_graph(
            case_id="case-fail",
            thread_id="thread-fail",
            message_id="msg-fail",
            workspace_slug="chief-of-staff",
            project_id="proj-1",
            title="Should not fail caller",
        ))
    # Node was not created (mocked), but call didn't raise
    node = asyncio.run(SessionStore.get_node_by_internal_id("case", "case-fail"))
    assert node is None


# ─── Request Tier Tests ──────────────────────────────────────────────


def test_create_and_resolve_request(tmp_path):
    _reset(tmp_path)
    req = asyncio.run(SessionStore.create_request(
        source_system="gmail",
        source_object_id="msg-r1",
        assigned_agent="cos",
        requester="alice@example.com",
        summary="Quick question",
        thread_id="thread-r1",
    ))
    assert req["status"] == "open"
    assert req["request_id"]

    asyncio.run(SessionStore.resolve_request(
        req["request_id"], resolution="Direct reply by +cos",
    ))
    resolved = asyncio.run(SessionStore.get_request(req["request_id"]))
    assert resolved["status"] == "resolved"
    assert resolved["resolution"] == "Direct reply by +cos"
    assert resolved["resolved_at"] is not None

    # Graph node should also be resolved
    node = asyncio.run(SessionStore.get_node_by_internal_id("request", req["request_id"]))
    assert node is not None
    assert node["status"] == "resolved"


def test_get_open_requests_filters_by_agent(tmp_path):
    _reset(tmp_path)
    asyncio.run(SessionStore.create_request(
        source_system="gmail", assigned_agent="cos", summary="COS task",
    ))
    asyncio.run(SessionStore.create_request(
        source_system="gmail", assigned_agent="estate", summary="Estate task",
    ))
    cos_reqs = asyncio.run(SessionStore.get_open_requests(assigned_agent="cos"))
    assert len(cos_reqs) == 1
    assert cos_reqs[0]["assigned_agent"] == "cos"

    all_reqs = asyncio.run(SessionStore.get_open_requests())
    assert len(all_reqs) == 2


def test_promote_request_creates_edge(tmp_path):
    _reset(tmp_path)
    # Create a case node first (needed for the promotion edge)
    asyncio.run(SessionStore.register_node("case", "case-promo", workspace="chief-of-staff"))

    req = asyncio.run(SessionStore.create_request(
        source_system="gmail", assigned_agent="cos", summary="Promote me",
    ))
    asyncio.run(SessionStore.promote_request(req["request_id"], "case-promo"))

    promoted = asyncio.run(SessionStore.get_request(req["request_id"]))
    assert promoted["status"] == "promoted"
    assert promoted["promoted_to_case_id"] == "case-promo"

    # Verify promoted_to edge exists
    req_node = asyncio.run(SessionStore.get_node_by_internal_id("request", req["request_id"]))
    edges = asyncio.run(SessionStore.get_edges_for_node(req_node["node_id"]))
    relation_types = {e["relation_type"] for e in edges}
    assert "promoted_to" in relation_types


def test_request_graph_linkage(tmp_path):
    """Creating a request with a thread_id registers graph node + Gmail edge."""
    _reset(tmp_path)
    req = asyncio.run(SessionStore.create_request(
        source_system="gmail",
        assigned_agent="cos",
        summary="Graph linked request",
        thread_id="thread-gr1",
    ))
    node = asyncio.run(SessionStore.get_node_by_internal_id("request", req["request_id"]))
    assert node is not None
    edges = asyncio.run(SessionStore.get_edges_for_node(node["node_id"]))
    assert len(edges) == 1
    assert edges[0]["relation_type"] == "spawned_from"


def test_create_request_graph_failure_isolation(tmp_path):
    """Graph failure during create_request still persists the request row."""
    _reset(tmp_path)
    from unittest.mock import patch, AsyncMock

    with patch.object(SessionStore, "register_node", new_callable=AsyncMock, side_effect=RuntimeError("graph boom")):
        req = asyncio.run(SessionStore.create_request(
            source_system="gmail",
            assigned_agent="cos",
            summary="Request survives graph failure",
            thread_id="thread-fail",
        ))
    assert req["request_id"]
    # Request row was committed before graph registration
    row = asyncio.run(SessionStore.get_request(req["request_id"]))
    assert row is not None
    assert row["status"] == "open"
    assert row["summary"] == "Request survives graph failure"


def test_promote_request_idempotent_edges(tmp_path):
    """Repeated promote_request does not create duplicate promoted_to edges."""
    _reset(tmp_path)
    asyncio.run(SessionStore.register_node("case", "case-idem", workspace="chief-of-staff"))

    req = asyncio.run(SessionStore.create_request(
        source_system="gmail", assigned_agent="cos", summary="Promote twice",
    ))
    asyncio.run(SessionStore.promote_request(req["request_id"], "case-idem"))
    asyncio.run(SessionStore.promote_request(req["request_id"], "case-idem"))

    req_node = asyncio.run(SessionStore.get_node_by_internal_id("request", req["request_id"]))
    edges = asyncio.run(SessionStore.get_edges_for_node(req_node["node_id"]))
    promoted_edges = [e for e in edges if e["relation_type"] == "promoted_to"]
    assert len(promoted_edges) == 1


def test_promote_request_creates_missing_nodes(tmp_path):
    """promote_request creates graph nodes on-demand when they are missing."""
    _reset(tmp_path)
    from unittest.mock import patch, AsyncMock

    # Create request with graph registration failure (no request node)
    with patch.object(SessionStore, "register_node", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
        req = asyncio.run(SessionStore.create_request(
            source_system="gmail", assigned_agent="cos", summary="Missing nodes",
        ))

    # Verify no graph node exists yet
    assert asyncio.run(SessionStore.get_node_by_internal_id("request", req["request_id"])) is None

    # Promote — should create both request and case nodes on-demand + edge
    asyncio.run(SessionStore.promote_request(req["request_id"], "case-missing"))

    req_node = asyncio.run(SessionStore.get_node_by_internal_id("request", req["request_id"]))
    assert req_node is not None
    assert req_node["status"] == "promoted"

    case_node = asyncio.run(SessionStore.get_node_by_internal_id("case", "case-missing"))
    assert case_node is not None

    edges = asyncio.run(SessionStore.get_edges_for_node(req_node["node_id"]))
    promoted_edges = [e for e in edges if e["relation_type"] == "promoted_to"]
    assert len(promoted_edges) == 1
