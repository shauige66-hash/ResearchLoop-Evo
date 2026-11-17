"""Tests for pipeline.py — full search pipeline with mocked sources."""

import pytest
from unittest.mock import AsyncMock, patch

from app.models.schemas import TopicInput
from app.services.sources.base import RawWorkRecord
from app.services.pipeline import search_pipeline


@pytest.fixture
def mock_openalex_records():
    return [
        RawWorkRecord(
            source="openalex",
            raw_id="W1",
            title="Smart Contract Vulnerability Detection",
            authors=["Alice"],
            year=2024,
            doi="10.1/test1",
            abstract="We propose a method to detect vulnerabilities.",
            source_url="https://openalex.org/W1",
            relevance_score=0.9,
        ),
    ]


@pytest.fixture
def mock_crossref_records():
    return [
        RawWorkRecord(
            source="crossref",
            raw_id="10.1/test2",
            title="LLM Agents for Code Analysis",
            authors=["Bob"],
            year=2023,
            doi="10.1/test2",
            abstract="We present an agent-based approach.",
            source_url="https://doi.org/10.1/test2",
        ),
    ]


@pytest.mark.asyncio
async def test_pipeline_basic(mock_openalex_records, mock_crossref_records):
    with (
        patch("app.services.pipeline.openalex.search_openalex", new_callable=AsyncMock) as mock_oa,
        patch("app.services.pipeline.crossref.search_crossref", new_callable=AsyncMock) as mock_cr,
    ):
        mock_oa.return_value = mock_openalex_records
        mock_cr.return_value = mock_crossref_records

        topic = TopicInput(
            topic="smart contract vulnerability detection",
            keywords=["smart contract", "vulnerability"],
            sources=["openalex", "crossref"],
            top_k=10,
        )
        result = await search_pipeline(topic)

        assert result.run_id.startswith("run_")
        assert len(result.papers) == 2
        assert result.meta["sources_requested"] == ["openalex", "crossref"]


@pytest.mark.asyncio
async def test_pipeline_dedupe_same_doi(mock_openalex_records):
    # Create a duplicate with same DOI
    dup = RawWorkRecord(
        source="crossref",
        raw_id="10.1/test1",
        title="Smart Contract Vulnerability Detection",
        authors=["Alice"],
        year=2024,
        doi="10.1/test1",
        source_url="https://doi.org/10.1/test1",
    )
    with (
        patch("app.services.pipeline.openalex.search_openalex", new_callable=AsyncMock) as mock_oa,
        patch("app.services.pipeline.crossref.search_crossref", new_callable=AsyncMock) as mock_cr,
    ):
        mock_oa.return_value = mock_openalex_records
        mock_cr.return_value = [dup]

        topic = TopicInput(topic="test", sources=["openalex", "crossref"], top_k=10)
        result = await search_pipeline(topic)

        # Should dedupe to 1 paper
        assert len(result.papers) == 1


@pytest.mark.asyncio
async def test_pipeline_source_error_handling():
    from app.services.http import HttpFailure

    with (
        patch("app.services.pipeline.openalex.search_openalex", new_callable=AsyncMock) as mock_oa,
        patch("app.services.pipeline.crossref.search_crossref", new_callable=AsyncMock) as mock_cr,
    ):
        mock_oa.side_effect = HttpFailure("openalex", "timeout", 504)
        mock_cr.return_value = []

        topic = TopicInput(topic="test", sources=["openalex", "crossref"], top_k=10)
        result = await search_pipeline(topic)

        assert len(result.source_errors) == 1
        assert result.source_errors[0].source == "openalex"


@pytest.mark.asyncio
async def test_pipeline_keyword_expansion():
    with patch("app.services.pipeline.openalex.search_openalex", new_callable=AsyncMock) as mock_oa:
        mock_oa.return_value = []

        topic = TopicInput(
            topic="deep learning for smart contracts",
            keywords=[],
            sources=["openalex"],
            expand_keywords=True,
            top_k=5,
        )
        result = await search_pipeline(topic)

        # Should have expanded keywords
        assert len(result.meta["keywords_used"]) > 0
