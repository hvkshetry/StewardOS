"""Envelope/shape tests for active health runtime tools."""

import pytest

from test_support.db import FakeRecord


@pytest.fixture
def fhir_mcp(fake_mcp, get_pool, ensure_initialized):
    from fhir import register_fhir_tools

    register_fhir_tools(fake_mcp, get_pool, ensure_initialized)
    return fake_mcp


@pytest.fixture
def genome_mcp(fake_mcp, get_pool, ensure_initialized):
    from genome_knowledge import register_genome_knowledge_tools

    register_genome_knowledge_tools(fake_mcp, get_pool, ensure_initialized)
    return fake_mcp


@pytest.fixture
def paperless_mcp(fake_mcp, get_pool, ensure_initialized):
    import paperless_sync

    paperless_sync.register_paperless_tools(fake_mcp, get_pool, ensure_initialized)
    return fake_mcp


class TestFhirRuntimeEnvelope:
    async def test_invalid_payload_returns_error_envelope(self, fhir_mcp):
        result = await fhir_mcp.call(
            "ingest_fhir_bundle",
            source_name="epic",
            bundle_json=[],
        )
        assert result["status"] == "error"
        assert result["errors"][0]["code"] == "validation_error"
        assert "FHIR payload must be object" in result["errors"][0]["message"]


class TestGenomeKnowledgeRuntimeEnvelope:
    async def test_invalid_subject_returns_error_envelope(self, genome_mcp):
        result = await genome_mcp.call(
            "hydrate_subject_genome_knowledge",
            subject_id=0,
        )
        assert result["status"] == "error"
        assert result["errors"][0]["code"] == "validation_error"
        assert "subject_id must be > 0" in result["errors"][0]["message"]


class TestPaperlessRuntimeEnvelope:
    async def test_missing_token_returns_error_envelope(self, monkeypatch, paperless_mcp):
        import paperless_sync

        monkeypatch.setattr(paperless_sync, "PAPERLESS_API_TOKEN", "")
        result = await paperless_mcp.call("sync_paperless_medical_metadata")
        assert result["status"] == "error"
        assert result["errors"][0]["code"] == "configuration_error"
        assert "PAPERLESS_API_TOKEN not configured" in result["errors"][0]["message"]

    async def test_document_linkage_returns_ok_envelope(self, paperless_mcp, pool):
        pool._conn.fetchrow.return_value = FakeRecord(paperless_doc_id=101, title="Lab Result")
        pool._conn.fetch.return_value = [FakeRecord(id=1, paperless_doc_id=101, subject_id=7)]

        result = await paperless_mcp.call("get_document_linkage", paperless_doc_id=101)

        assert result["status"] == "ok"
        assert result["errors"] == []
        assert result["data"]["document"]["paperless_doc_id"] == 101
        assert result["data"]["links"][0]["subject_id"] == 7

    async def test_sync_paperless_metadata_paginates_and_uses_transaction(
        self,
        monkeypatch,
        paperless_mcp,
        pool,
    ):
        import paperless_sync

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def raise_for_status(self):
                return None

            def json(self):
                return self._payload

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, params=None):
                if url == "/api/tags/":
                    return FakeResponse({"results": [{"id": 7, "name": "medical"}]})
                if url == "/api/documents/":
                    return FakeResponse(
                        {
                            "count": 3,
                            "results": [
                                {"id": 101, "title": "Lab Result", "document_type_name": "Lab", "created": "2026-03-01"},
                                {"id": 102, "title": "Rx", "document_type_name": "Prescription", "created": "2026-03-02"},
                            ],
                            "next": "/api/documents/?page=2",
                        }
                    )
                if url == "/api/documents/?page=2":
                    return FakeResponse(
                        {
                            "count": 3,
                            "results": [
                                {"id": 103, "title": "Referral", "document_type_name": "Referral", "created": "2026-03-03"},
                            ],
                            "next": None,
                        }
                    )
                raise AssertionError(f"unexpected URL: {url}")

        monkeypatch.setattr(paperless_sync, "PAPERLESS_API_TOKEN", "token")
        monkeypatch.setattr(paperless_sync.httpx, "AsyncClient", lambda **kwargs: FakeClient())
        pool._conn.fetchrow.return_value = FakeRecord(id=55)

        result = await paperless_mcp.call("sync_paperless_medical_metadata", limit=3)

        assert result["status"] == "ok"
        assert result["errors"] == []
        assert result["data"]["ingestion_run_id"] == 55
        assert result["data"]["rows_read"] == 3
        assert result["data"]["rows_written"] == 3
        assert result["data"]["rows_available"] == 3
        assert result["data"]["truncated"] is False
        assert result["data"]["used_fallback_heuristics"] is False
        pool._conn.transaction.assert_called_once()
