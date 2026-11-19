"""Unit tests for the shared LLM provider: budget, cache, audit and redaction.

Only `_post` (the network seam) is replaced. Everything else — hashing, budget
accounting, cache keys, schema rejection and the audit rows — is the real code.
No test here contacts a real API; the credentials come from `llm_configured` and
are test-only.
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest
from pydantic import BaseModel

from app.models.llm import LLM_NOT_CONFIGURED, NOT_CONFIGURED_REASON
from app.services.llm import (
    LLMBudgetExhausted,
    LLMCallFailed,
    LLMNotConfigured,
    LLMOutputRejected,
    LLMProvider,
)

SYSTEM = "you are a literature analyst"
USER = "extract the limitations from this abstract"
REPLY = json.dumps({"claim": "evaluation protocols differ", "evidence_span": "protocols differ"})
USAGE = {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}


class Card(BaseModel):
    claim: str
    evidence_span: str


def _prompt_hash(system: str = SYSTEM, user: str = USER) -> str:
    return hashlib.sha256(
        json.dumps({"system": system, "user": user}, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _seam(monkeypatch, provider, replies):
    """Replace the network seam with a queue of (content, usage) or exceptions."""
    calls: list[tuple[str, str, str]] = []

    async def fake_post(agent_role, system, user):
        calls.append((agent_role, system, user))
        item = replies[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(provider, "_post", fake_post)
    return calls


def _forbid_network(monkeypatch, provider):
    async def fake_post(*args, **kwargs):
        raise AssertionError("the network seam must not be reached")

    monkeypatch.setattr(provider, "_post", fake_post)


# ------------------------------------------------------------- not configured
@pytest.mark.asyncio
async def test_an_unconfigured_provider_never_reaches_the_network(temp_db, monkeypatch):
    provider = LLMProvider(temp_db)
    _forbid_network(monkeypatch, provider)

    with pytest.raises(LLMNotConfigured) as excinfo:
        await provider.complete("literature_analyst", SYSTEM, USER, schema=Card)

    assert NOT_CONFIGURED_REASON in str(excinfo.value)
    record = excinfo.value.record
    assert record.status == "not_configured"
    assert record.provider == "not_configured"
    assert record.model == ""
    assert temp_db.count_llm_attempts() == 0
    summary = provider.usage_summary()
    assert summary.configured is False
    assert summary.status == LLM_NOT_CONFIGURED
    assert summary.notice == NOT_CONFIGURED_REASON
    assert summary.calls_used == 0


# ------------------------------------------------------------------ audit row
@pytest.mark.asyncio
async def test_a_success_is_audited_with_hashes_and_the_returned_tokens(
    temp_db, llm_configured, monkeypatch
):
    provider = LLMProvider(temp_db)
    calls = _seam(monkeypatch, provider, [(REPLY, USAGE)])

    reply = await provider.complete(
        "literature_analyst", SYSTEM, USER, schema=Card, pipeline_id="gpipe_x", paper_id="p1"
    )

    assert calls == [("literature_analyst", SYSTEM, USER)]
    assert reply.from_cache is False
    assert reply.parsed == Card(claim="evaluation protocols differ", evidence_span="protocols differ")
    record = reply.record
    assert record.status == "success"
    assert record.request_id.startswith("llm_")
    assert record.prompt_hash == _prompt_hash()
    assert record.response_hash == hashlib.sha256(REPLY.encode()).hexdigest()
    assert record.prompt_version
    assert record.pipeline_id == "gpipe_x"
    assert record.paper_id == "p1"
    assert record.latency_ms is not None
    assert (record.prompt_tokens, record.completion_tokens, record.total_tokens) == (120, 30, 150)
    assert record.model == llm_configured.llm_model
    assert record.created_at

    # The audit row stores hashes and counts, never the prompt or the reply body.
    dumped = record.model_dump_json()
    assert SYSTEM not in dumped
    assert USER not in dumped
    assert "evaluation protocols differ" not in dumped


@pytest.mark.asyncio
async def test_the_api_key_reaches_neither_the_database_nor_the_error_string(
    temp_db, llm_configured, monkeypatch
):
    provider = LLMProvider(temp_db)
    key = llm_configured.llm_api_key
    boom = RuntimeError(f"401 unauthorized for bearer {key}")
    _seam(monkeypatch, provider, [boom])

    with pytest.raises(LLMCallFailed) as excinfo:
        await provider.complete("gap_critic", SYSTEM, USER)

    assert key not in str(excinfo.value)
    assert "[redacted]" in str(excinfo.value)
    record = excinfo.value.record
    assert record.status == "failed"
    assert key not in record.error
    assert key not in temp_db.list_llm_calls()[0].model_dump_json()
    assert all(r.status != "cache_hit" for r in temp_db.list_llm_calls())
    assert provider.usage_summary().failed_calls == 1


# ---------------------------------------------------------------------- cache
@pytest.mark.asyncio
async def test_a_cache_hit_is_free_and_replays_the_parsed_reply(
    temp_db, llm_configured, monkeypatch
):
    provider = LLMProvider(temp_db)
    calls = _seam(monkeypatch, provider, [(REPLY, USAGE)])

    first = await provider.complete("literature_analyst", SYSTEM, USER, schema=Card, paper_id="p1")
    second = await provider.complete("literature_analyst", SYSTEM, USER, schema=Card, paper_id="p1")

    assert len(calls) == 1
    assert first.from_cache is False
    assert second.from_cache is True
    assert second.content == REPLY
    assert second.parsed == first.parsed
    assert second.record.status == "cache_hit"
    assert second.record.latency_ms == 0
    summary = provider.usage_summary()
    assert summary.calls_used == 1
    assert summary.cache_hits == 1
    assert summary.role_usage == {"literature_analyst": 1}


@pytest.mark.asyncio
async def test_the_cache_key_is_bound_to_role_model_and_prompt_version(
    temp_db, llm_configured, monkeypatch
):
    provider = LLMProvider(temp_db)
    calls = _seam(monkeypatch, provider, [(REPLY, USAGE)] * 3)

    await provider.complete("literature_analyst", SYSTEM, USER, paper_id="p1")
    # A new prompt version is a different question, so it must be asked again.
    await provider.complete(
        "literature_analyst", SYSTEM, USER, paper_id="p1", prompt_version="gap-pipeline-v2"
    )
    # A different role with the same text is also a different question.
    await provider.complete("gap_critic", SYSTEM, USER, paper_id="p1")

    assert len(calls) == 3
    assert provider.usage_summary().calls_used == 3


@pytest.mark.asyncio
async def test_refresh_asks_again_instead_of_replaying_the_cache(
    temp_db, llm_configured, monkeypatch
):
    provider = LLMProvider(temp_db)
    calls = _seam(monkeypatch, provider, [(REPLY, USAGE), (REPLY, USAGE)])

    await provider.complete("literature_analyst", SYSTEM, USER)
    refreshed = await provider.complete("literature_analyst", SYSTEM, USER, refresh=True)

    assert len(calls) == 2
    assert refreshed.from_cache is False


# ------------------------------------------------------------ output rejection
@pytest.mark.asyncio
async def test_a_reply_that_fails_the_schema_is_rejected_and_never_cached(
    temp_db, llm_configured, monkeypatch
):
    provider = LLMProvider(temp_db)
    calls = _seam(monkeypatch, provider, [("this is not json", USAGE), (REPLY, USAGE)])

    with pytest.raises(LLMOutputRejected):
        await provider.complete("literature_analyst", SYSTEM, USER, schema=Card)

    record = temp_db.list_llm_calls()[-1]
    assert record.status == "output_rejected"
    assert record.response_hash == hashlib.sha256(b"this is not json").hexdigest()
    assert temp_db.count_llm_attempts() == 1
    # The malformed answer was not cached, so the retry is a real call.
    reply = await provider.complete("literature_analyst", SYSTEM, USER, schema=Card)
    assert len(calls) == 2
    assert reply.from_cache is False
    assert provider.usage_summary().failed_calls == 1


@pytest.mark.asyncio
async def test_an_empty_completion_is_rejected(temp_db, llm_configured, monkeypatch):
    provider = LLMProvider(temp_db)
    _seam(monkeypatch, provider, [("   ", USAGE)])

    with pytest.raises(LLMOutputRejected):
        await provider.complete("gap_analyst", SYSTEM, USER)

    assert temp_db.list_llm_calls()[-1].status == "output_rejected"


@pytest.mark.asyncio
async def test_a_markdown_fenced_reply_is_still_parsed(temp_db, llm_configured, monkeypatch):
    provider = LLMProvider(temp_db)
    fenced = f"```json\n{REPLY}\n```"
    _seam(monkeypatch, provider, [(fenced, {})])

    reply = await provider.complete("literature_analyst", SYSTEM, USER, schema=Card)

    assert reply.parsed.claim == "evaluation protocols differ"
    assert reply.record.response_hash == hashlib.sha256(fenced.encode()).hexdigest()
    summary = provider.usage_summary()
    assert summary.total_tokens is None
    assert summary.prompt_tokens is None


# ------------------------------------------------------- transport failures
@pytest.mark.asyncio
async def test_a_timeout_is_audited_as_failed_and_consumes_budget(
    temp_db, llm_configured, monkeypatch
):
    provider = LLMProvider(temp_db)
    calls = _seam(monkeypatch, provider, [httpx.ConnectTimeout("timed out after 60s")])

    with pytest.raises(LLMCallFailed) as excinfo:
        await provider.complete("literature_analyst", SYSTEM, USER)

    assert len(calls) == 1  # the provider does not silently retry and burn quota
    record = excinfo.value.record
    assert record.status == "failed"
    assert "ConnectTimeout" in record.error
    assert record.latency_ms is not None
    assert temp_db.count_llm_attempts() == 1


@pytest.mark.asyncio
async def test_a_rate_limit_response_is_reported_not_retried(
    temp_db, llm_configured, monkeypatch
):
    provider = LLMProvider(temp_db)
    request = httpx.Request("POST", llm_configured.llm_base_url + "/chat/completions")
    response = httpx.Response(429, request=request, text="rate limit exceeded")
    calls = _seam(
        monkeypatch,
        provider,
        [httpx.HTTPStatusError("429 Too Many Requests", request=request, response=response)],
    )

    with pytest.raises(LLMCallFailed) as excinfo:
        await provider.complete("gap_analyst", SYSTEM, USER)

    assert len(calls) == 1
    assert excinfo.value.record.status == "failed"
    assert "429" in excinfo.value.record.error
    assert provider.usage_summary().failed_calls == 1


@pytest.mark.asyncio
async def test_an_invalid_api_key_is_audited_without_leaking_the_key(
    temp_db, llm_configured, monkeypatch
):
    provider = LLMProvider(temp_db)
    key = llm_configured.llm_api_key
    request = httpx.Request("POST", llm_configured.llm_base_url + "/chat/completions")
    response = httpx.Response(
        401, request=request, text=f"Authentication Fails, Your api key: {key} is invalid"
    )
    _seam(
        monkeypatch,
        provider,
        [
            httpx.HTTPStatusError(
                f"401 Unauthorized: {response.text}", request=request, response=response
            )
        ],
    )

    with pytest.raises(LLMCallFailed) as excinfo:
        await provider.complete("research_planner", SYSTEM, USER)

    record = excinfo.value.record
    assert record.status == "failed"
    assert key not in record.error
    assert key not in str(excinfo.value)
    assert key not in temp_db.list_llm_calls()[0].model_dump_json()


# --------------------------------------------------------------------- budget
@pytest.mark.asyncio
async def test_the_total_budget_stops_before_the_network(temp_db, llm_configured, monkeypatch):
    monkeypatch.setattr(llm_configured, "llm_max_calls", 1)
    provider = LLMProvider(temp_db)
    calls = _seam(monkeypatch, provider, [(REPLY, USAGE)])

    await provider.complete("literature_analyst", SYSTEM, USER, paper_id="p1")
    with pytest.raises(LLMBudgetExhausted) as excinfo:
        await provider.complete("literature_analyst", SYSTEM, USER + " for paper 2", paper_id="p2")

    assert len(calls) == 1
    assert excinfo.value.record.status == "budget_exhausted"
    assert "1/1" in str(excinfo.value)
    summary = provider.usage_summary()
    assert summary.status == "budget_exhausted"
    assert summary.calls_used == 1

    # An already-paid answer is still replayable for free after the budget is gone.
    replay = await provider.complete("literature_analyst", SYSTEM, USER, paper_id="p1")
    assert replay.from_cache is True
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_failed_call_still_consumes_the_budget(temp_db, llm_configured, monkeypatch):
    monkeypatch.setattr(llm_configured, "llm_max_calls", 1)
    provider = LLMProvider(temp_db)
    _seam(monkeypatch, provider, [RuntimeError("connection reset")])

    with pytest.raises(LLMCallFailed):
        await provider.complete("gap_analyst", SYSTEM, USER)
    _forbid_network(monkeypatch, provider)
    with pytest.raises(LLMBudgetExhausted):
        await provider.complete("gap_analyst", SYSTEM, USER)


@pytest.mark.asyncio
async def test_a_role_budget_stops_only_that_role(temp_db, llm_configured, monkeypatch):
    monkeypatch.setattr(
        llm_configured, "llm_role_budgets", {"gap_critic": 1, "literature_analyst": 5}
    )
    provider = LLMProvider(temp_db)
    calls = _seam(monkeypatch, provider, [(REPLY, USAGE)] * 3)

    await provider.complete("gap_critic", SYSTEM, USER, paper_id="p1")
    with pytest.raises(LLMBudgetExhausted) as excinfo:
        await provider.complete("gap_critic", SYSTEM, USER + " for paper 2", paper_id="p2")
    assert "gap_critic" in str(excinfo.value)

    await provider.complete("literature_analyst", SYSTEM, USER, paper_id="p1")
    assert len(calls) == 2
    assert provider.usage_summary().role_usage == {"gap_critic": 1, "literature_analyst": 1}