"""Optional live API tests — gated by RLE_LIVE_TESTS=1.

These tests make real HTTP requests to OpenAlex, Crossref, and arXiv.
They are skipped by default to avoid rate limiting and network dependencies.

Run with: RLE_LIVE_TESTS=1 pytest tests/test_live_sources.py
"""

import os
import pytest

from app.models.schemas import TopicInput
from app.services.sources import openalex, crossref, arxiv


LIVE_TESTS_ENABLED = os.getenv("RLE_LIVE_TESTS", "0") == "1"

pytestmark = pytest.mark.skipif(not LIVE_TESTS_ENABLED, reason="set RLE_LIVE_TESTS=1 to run")


@pytest.mark.asyncio
async def test_live_openalex():
    topic = TopicInput(
        topic="smart contract vulnerability detection",
        keywords=["smart contract"],
        sources=["openalex"],
        top_k=5,
    )
    records = await openalex.search_openalex(topic, "smart contract vulnerability")
    assert len(records) > 0
    assert all(r.source == "openalex" for r in records)
    assert all(r.title for r in records)


@pytest.mark.asyncio
async def test_live_crossref():
    topic = TopicInput(
        topic="smart contract vulnerability detection",
        keywords=["smart contract"],
        sources=["crossref"],
        top_k=5,
    )
    records = await crossref.search_crossref(topic, "smart contract vulnerability")
    assert len(records) > 0
    assert all(r.source == "crossref" for r in records)


@pytest.mark.asyncio
async def test_live_arxiv():
    topic = TopicInput(
        topic="smart contract vulnerability detection",
        keywords=["smart contract"],
        sources=["arxiv"],
        top_k=3,
    )
    records = await arxiv.search_arxiv(topic, "smart contract")
    # arXiv may return 429, so we allow empty
    assert all(r.source == "arxiv" for r in records)
