"""DI-based tests for estate-planning compliance module."""

import pytest

from test_support.db import FakeRecord
from test_support.mcp import FakeMCP


@pytest.fixture
def compliance_mcp(fake_mcp, get_pool):
    from compliance import register_compliance_tools
    register_compliance_tools(fake_mcp, get_pool)
    return fake_mcp


class TestUpdateComplianceInstanceStatus:
    async def test_invalid_status_rejected(self, compliance_mcp, pool):
        result = await compliance_mcp.call(
            "update_compliance_instance_status",
            compliance_instance_id=1,
            status="invalid_status",
        )
        assert result["status"] == "error"
        assert result["data"]["valid_statuses"]

    async def test_not_found(self, compliance_mcp, pool):
        pool.fetchrow.return_value = None
        result = await compliance_mcp.call(
            "update_compliance_instance_status",
            compliance_instance_id=999,
            status="submitted",
        )
        assert result["status"] == "error"
        assert "not found" in result["errors"][0]["message"]

    async def test_submitted(self, compliance_mcp, pool):
        pool.fetchrow.return_value = FakeRecord(
            id=1, status="submitted", submitted_at="2024-01-01T00:00:00",
            accepted_at=None, rejected_at=None,
        )
        result = await compliance_mcp.call(
            "update_compliance_instance_status",
            compliance_instance_id=1,
            status="submitted",
        )
        assert result["data"]["status"] == "submitted"

    async def test_accepted(self, compliance_mcp, pool):
        pool.fetchrow.return_value = FakeRecord(
            id=2, status="accepted", accepted_at="2024-06-01T00:00:00",
        )
        result = await compliance_mcp.call(
            "update_compliance_instance_status",
            compliance_instance_id=2,
            status="accepted",
        )
        assert result["data"]["status"] == "accepted"


class TestUpsertComplianceObligation:
    async def test_unknown_jurisdiction(self, compliance_mcp, pool):
        pool.fetchval.return_value = None
        result = await compliance_mcp.call(
            "upsert_compliance_obligation",
            title="Annual Report",
            obligation_type="filing",
            jurisdiction_code="XX-ZZ",
        )
        assert result["status"] == "error"
        assert "Unknown jurisdiction_code" in result["errors"][0]["message"]

    async def test_creates_obligation(self, compliance_mcp, pool):
        pool.fetchval.return_value = None  # no jurisdiction lookup needed
        pool.fetchrow.return_value = FakeRecord(
            id=1, title="Annual Report", obligation_type="filing",
        )
        result = await compliance_mcp.call(
            "upsert_compliance_obligation",
            title="Annual Report",
            obligation_type="filing",
        )
        assert result["data"]["title"] == "Annual Report"


class TestLinkComplianceEvidence:
    async def test_creates_evidence(self, compliance_mcp, pool):
        pool.fetchrow.return_value = FakeRecord(
            id=1, compliance_instance_id=5, evidence_type="receipt",
            paperless_doc_id=100, status="submitted",
        )
        result = await compliance_mcp.call(
            "link_compliance_evidence",
            compliance_instance_id=5,
            evidence_type="receipt",
            paperless_doc_id=100,
        )
        assert result["data"]["compliance_instance_id"] == 5
        assert result["data"]["evidence_type"] == "receipt"
