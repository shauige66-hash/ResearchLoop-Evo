"""Tests for API endpoints using FastAPI TestClient."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
import os
import tempfile

from app.main import app
from app.models.paper import Paper, SearchMeta
from app.models.schemas import SearchResponse


# Use a temporary database for tests
@pytest.fixture(autouse=True)
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        os.environ["RLE_DB_PATH"] = db_path
        # Clear the cached store and settings
        import app.storage.store as store_module
        import app.config as config_module
        if store_module._store is not None:
            store_module._store.close()
        store_module._store = None
        config_module.get_settings.cache_clear()
        yield
        # Cleanup
        if store_module._store is not None:
            store_module._store.close()
            store_module._store = None
        if "RLE_DB_PATH" in os.environ:
            del os.environ["RLE_DB_PATH"]
        config_module.get_settings.cache_clear()


client = TestClient(app)


def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "ResearchLoop Evo API" in data["name"]


def test_future_endpoints_return_501():
    endpoints = [
        "/api/gaps/discover",
        "/api/experiments/design",
        "/api/experiments/run",
        "/api/experiments/verify",
        "/api/evolve/skills",
        "/api/skills/evaluate",
        "/api/skills/promote",
    ]
    for endpoint in endpoints:
        response = client.post(endpoint)
        assert response.status_code == 501
        data = response.json()
        assert data["detail"]["status"] == "not_implemented"


@pytest.fixture
def mock_search_response():
    import time
    run_id = f"run_{int(time.time() * 1000000)}"
    project_id = f"proj_{int(time.time() * 1000000)}"
    papers = [
        Paper(
            paper_id="test:1",
            title="Test Paper",
            source="openalex",
            source_url="https://example.com",
            abstract="Test abstract",
            run_id=run_id,
        )
    ]
    return SearchResponse(
        run_id=run_id,
        project_id=project_id,
        topic="test topic",
        meta=SearchMeta(
            retrieved_at="2024-01-01T00:00:00Z",
            duration_ms=100,
            cache_hits=0,
            requests_made=1,
            sources_requested=["openalex"],
            sources_failed=[],
        ).model_dump(),
        papers=papers,
        source_errors=[],
        stats={"cache_hits": 0, "requests_made": 1},
    )


def test_search_endpoint(mock_search_response):
    with patch("app.api.routes_literature.search_pipeline", new_callable=AsyncMock) as mock_pipeline:
        mock_pipeline.return_value = mock_search_response

        response = client.post(
            "/api/literature/search",
            json={"topic": "test topic", "sources": ["openalex"], "top_k": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["run_id"].startswith("run_")
        assert len(data["papers"]) == 1


def test_list_papers_empty():
    response = client.get("/api/literature/papers")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["papers"] == []


def test_get_paper_not_found():
    response = client.get("/api/literature/papers/nonexistent")
    assert response.status_code == 404


def test_matrix_requires_paper_ids():
    response = client.post("/api/literature/matrix", json={"paper_ids": []})
    assert response.status_code == 422  # validation error


def test_export_requires_paper_ids():
    response = client.get("/api/literature/matrix/export?format=csv")
    assert response.status_code == 400


def test_report_requires_papers():
    response = client.post("/api/literature/report", json={"paper_ids": []})
    assert response.status_code == 404
