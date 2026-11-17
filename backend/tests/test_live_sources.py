"""Optional live API tests — gated by RLE_LIVE_TESTS=1.

These tests make real HTTP requests to OpenAlex, Crossref, and arXiv.
They are skipped by default to avoid rate limiting and network dependencies.
Every call passes refresh=True: a cache-served "live" test would verify nothing.

Run with: RLE_LIVE_TESTS=1 pytest tests/test_live_sources.py
"""

import os
import pytest
import pytest_asyncio

from app.models.schemas import TopicInput
from app.services.http import close_client
from app.services.sources import openalex, crossref, arxiv


LIVE_TESTS_ENABLED = os.getenv("RLE_LIVE_TESTS", "0") == "1"

pytestmark = pytest.mark.skipif(not LIVE_TESTS_ENABLED, reason="set RLE_LIVE_TESTS=1 to run")


@pytest_asyncio.fixture(autouse=True)
async def release_client():
    """Close the shared client on the loop that opened it, as the app lifespan does.

    pytest-asyncio gives each test its own event loop. Without this, connections
    opened by an earlier test are torn down after their loop is closed, and the
    Windows proactor transport raises "Event loop is closed" from a later test.
    """
    yield
    await close_client()


@pytest.mark.asyncio
async def test_live_openalex():
    topic = TopicInput(
        topic="smart contract vulnerability detection",
        keywords=["smart contract"],
        sources=["openalex"],
        top_k=5,
    )
    records = await openalex.search_openalex(topic, "smart contract vulnerability", refresh=True)
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
    records = await crossref.search_crossref(topic, "smart contract vulnerability", refresh=True)
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
    records = await arxiv.search_arxiv(topic, "smart contract", refresh=True)
    # arXiv may return 429, so we allow empty
    assert all(r.source == "arxiv" for r in records)
