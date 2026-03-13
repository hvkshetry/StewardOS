"""DI-based tests for estate document tools."""

import pytest

from test_support.db import FakeRecord


@pytest.fixture
def documents_mcp(fake_mcp, get_pool):
    from documents import register_documents_tools

    register_documents_tools(fake_mcp, get_pool)
    return fake_mcp


class TestLinkDocument:
    async def test_link_document_uses_shared_paperless_upsert_and_envelope(self, documents_mcp, pool):
        pool.fetchval.return_value = 10
        pool._conn.fetchrow.side_effect = [
            None,
            FakeRecord(id=1, title="Trust Agreement", paperless_doc_id=101),
            FakeRecord(paperless_doc_id=101, doc_purpose_type="trust_agreement", status="active"),
        ]

        result = await documents_mcp.call(
            "link_document",
            title="Trust Agreement",
            doc_type="trust_agreement",
            paperless_doc_id=101,
            entity_id=7,
            jurisdiction_code="US-MA",
        )

        assert result["status"] == "ok"
        assert result["data"]["title"] == "Trust Agreement"
        assert result["data"]["paperless_doc_id"] == 101
        assert result["data"]["doc_metadata"]["status"] == "active"

    async def test_link_document_rejects_unknown_jurisdiction(self, documents_mcp, pool):
        pool.fetchval.return_value = None

        result = await documents_mcp.call(
            "link_document",
            title="Trust Agreement",
            doc_type="trust_agreement",
            paperless_doc_id=101,
            jurisdiction_code="ZZ-UNKNOWN",
        )

        assert result["status"] == "error"
        assert result["errors"][0]["message"] == "Unknown jurisdiction_code: ZZ-UNKNOWN"
