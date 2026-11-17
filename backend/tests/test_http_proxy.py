"""Regression tests for the HTTP layer.

Covers the real production failure where an ambient NO_PROXY entry containing a
bracketed IPv6 literal ("[::1]") made httpx raise InvalidURL during AsyncClient
construction, so every literature source failed before sending a request.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

import app.config as config_module
import app.services.http as http_module
from app.services.http import SourceClient, build_proxy_mounts

# The exact value observed in the failing environment.
REAL_NO_PROXY = "localhost,.localhost,127.0.0.1,127.0.0.0/8,[::1],::1"

PROXY_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)


@pytest.fixture
def clean_proxy_env(monkeypatch):
    for name in PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.fixture
def temp_cache(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        monkeypatch.setenv("RLE_CACHE_DIR", str(Path(tmpdir) / "cache"))
        monkeypatch.setenv("RLE_DATA_DIR", tmpdir)
        config_module.get_settings.cache_clear()
        yield tmpdir
    config_module.get_settings.cache_clear()


@pytest.mark.asyncio
async def test_bracketed_ipv6_no_proxy_does_not_break_client(clean_proxy_env, temp_cache):
    """The original crash: client construction must survive a malformed NO_PROXY."""
    clean_proxy_env.setenv("NO_PROXY", REAL_NO_PROXY)
    clean_proxy_env.setenv("no_proxy", REAL_NO_PROXY)

    client = SourceClient()
    constructed = await client.client()
    try:
        assert isinstance(constructed, httpx.AsyncClient)
        assert not constructed.is_closed
    finally:
        await client.aclose()


def test_every_generated_mount_pattern_is_parseable(clean_proxy_env):
    clean_proxy_env.setenv("NO_PROXY", REAL_NO_PROXY)
    mounts = build_proxy_mounts()
    assert mounts, "valid entries must still produce bypass mounts"
    for pattern in mounts:
        httpx.URL(pattern)  # raises if the pattern is malformed
    assert "all://[::1]" in mounts
    assert "all://localhost" in mounts
    assert http_module.REJECTED_PROXY_ENTRIES == []


def test_unparseable_entry_is_recorded_not_fatal(clean_proxy_env):
    clean_proxy_env.setenv("NO_PROXY", "localhost,foo:bar]")
    mounts = build_proxy_mounts()
    assert "all://localhost" in mounts
    assert http_module.REJECTED_PROXY_ENTRIES == ["NO_PROXY=foo:bar]"]


def test_legitimate_proxy_is_still_honored(clean_proxy_env):
    clean_proxy_env.setenv("HTTP_PROXY", "http://127.0.0.1:8888")
    clean_proxy_env.setenv("HTTPS_PROXY", "http://127.0.0.1:8888")
    mounts = build_proxy_mounts()
    assert isinstance(mounts["http://"], httpx.AsyncHTTPTransport)
    assert isinstance(mounts["https://"], httpx.AsyncHTTPTransport)


def test_no_proxy_star_bypasses_every_proxy(clean_proxy_env):
    clean_proxy_env.setenv("HTTP_PROXY", "http://127.0.0.1:8888")
    clean_proxy_env.setenv("NO_PROXY", "*")
    assert build_proxy_mounts() == {}


def test_cidr_entry_reduces_to_network_address(clean_proxy_env):
    clean_proxy_env.setenv("NO_PROXY", "192.168.0.0/16")
    mounts = build_proxy_mounts()
    assert "all://192.168.0.0" in mounts


@pytest.mark.asyncio
async def test_timeout_then_success_does_not_raise_unbound_local(clean_proxy_env, temp_cache, monkeypatch):
    """retry_after used to be unbound when the first attempt timed out."""
    monkeypatch.setattr(http_module, "BACKOFF_SECONDS", (0.0, 0.0))
    client = SourceClient()
    request = httpx.Request("GET", "https://example.org/api")
    response = httpx.Response(200, json={"ok": True}, request=request)
    fake = Mock(is_closed=False)
    fake.send = AsyncMock(side_effect=[httpx.ConnectTimeout("timed out"), response])
    client._client = fake

    outcome = await client.fetch_json("https://example.org/api", source="openalex", refresh=True)

    assert outcome.payload == {"ok": True}
    assert outcome.from_cache is False
    assert fake.send.await_count == 2


@pytest.mark.asyncio
async def test_per_request_timeout_uses_extensions_not_send_kwarg(clean_proxy_env, temp_cache):
    """httpx 0.28 removed send(timeout=...); the timeout must ride in extensions."""
    client = SourceClient()
    request = httpx.Request("GET", "https://example.org/api")
    response = httpx.Response(200, json={"ok": True}, request=request)
    fake = Mock(is_closed=False)
    fake.send = AsyncMock(return_value=response)
    client._client = fake

    await client.fetch_json(
        "https://example.org/api", source="crossref", timeout=7.0, refresh=True
    )

    sent_request = fake.send.await_args.args[0]
    assert fake.send.await_args.kwargs == {}
    assert sent_request.extensions["timeout"] == {
        "connect": 7.0,
        "read": 7.0,
        "write": 7.0,
        "pool": 7.0,
    }


@pytest.mark.asyncio
async def test_pipeline_attributes_unexpected_error_to_real_source(monkeypatch):
    from app.models.schemas import TopicInput
    from app.services import pipeline

    async def boom(*args, **kwargs):
        raise RuntimeError("adapter exploded")

    monkeypatch.setattr(pipeline.openalex, "search_openalex", boom)
    topic = TopicInput(topic="agent memory", sources=["openalex"], expand_keywords=False)
    papers, error = await pipeline._search_source("openalex", topic, "agent memory", False)

    assert papers == []
    assert error is not None
    assert error.source == "openalex"
    assert "RuntimeError" in error.detail


@pytest.mark.asyncio
async def test_subunit_rate_bucket_does_not_deadlock():
    """arXiv runs at 0.3 req/s; the bucket used to spin forever waiting for 1 token."""
    bucket = http_module.TokenBucket(0.3, min_interval=0.0)
    assert bucket.capacity >= 1.0
    await asyncio.wait_for(bucket.acquire(), timeout=1.0)


@pytest.mark.asyncio
async def test_subunit_rate_bucket_still_spaces_requests():
    bucket = http_module.TokenBucket(0.3, min_interval=0.0)
    started = time.monotonic()
    await asyncio.wait_for(bucket.acquire(), timeout=8.0)
    await asyncio.wait_for(bucket.acquire(), timeout=8.0)
    assert time.monotonic() - started >= 3.0


@pytest.mark.asyncio
async def test_crossref_select_only_uses_supported_fields(monkeypatch):
    """Crossref /works rejects select=language with HTTP 400."""
    from app.models.schemas import TopicInput
    from app.services.sources import crossref

    captured: dict = {}

    async def fake_fetch(url, params=None, **kwargs):
        captured.update(params or {})
        return http_module.HttpOutcome({"message": {"items": []}}, False, 200, 1, 1)

    client = SourceClient()
    monkeypatch.setattr(crossref, "get_client", lambda: client)
    monkeypatch.setattr(client, "fetch_json", fake_fetch)

    topic = TopicInput(topic="agent memory", sources=["crossref"], year_from=2023)
    await crossref.search_crossref(topic, "LLM agent memory")

    fields = captured["select"].split(",")
    assert "language" not in fields
    assert {"DOI", "title", "abstract", "issued"} <= set(fields)