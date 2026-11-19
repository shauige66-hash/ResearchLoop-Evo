"""Offline tests for the multi-agent gap pipeline.

Every LLM reply here comes from `tests.fakes.FakeLLMProvider`, which replaces only
the network seam. Budgets, caching, auditing, span verification and the Python
gate are the real implementations. Nothing in this file contacts a real API, and
all records live in the throwaway `temp_db`.
"""

from __future__ import annotations

import json

import pytest

from app.models.gap_pipeline import (
    PROMPT_VERSION,
    STAGE_SEQUENCE,
    PipelineStartRequest,
)
from app.models.paper import Paper
from app.models.schemas import SearchResponse, SourceError
from app.services import gap as gap_module
from app.services import gap_pipeline as service

from .fakes import FakeLLMProvider, gap_reply

TOPIC = "memory consolidation for LLM agents"


def _abstract(index: int) -> str:
    return (
        f"We study memory consolidation for LLM agents in setting {index}. "
        "We propose a module that compresses episodic traces into reusable skills. "
        "The agent runs in a multi-session dialogue environment. "
        "We evaluate on LoCoMo and on a private long-history dataset. "
        "We report accuracy and F1 on the authors' own benchmark. "
        "However, evaluation protocols differ across papers and results are not comparable. "
        "Future work will release a shared benchmark for this task."
    )


def _store_papers(store, count: int = 4, run_id: str = "run_pipe") -> list[Paper]:
    store.save_project("proj_pipe", TOPIC)
    papers: list[Paper] = []
    for i in range(count):
        pid = f"pipe:p{i + 1}"
        paper = Paper(
            paper_id=pid,
            title=f"Memory consolidation for LLM agents {i + 1}",
            authors=["A. Researcher", "B. Scholar"],
            publication_year=2023 + i,
            venue="Test Conference",
            doi=f"10.9999/pipe.{i + 1}",
            abstract=_abstract(i + 1),
            source="openalex",
            source_url=f"https://openalex.org/{pid}",
            citation_count=20 - i,
            relevance_score=0.9 - i * 0.05,
            language="en",
            retrieved_at="2025-01-01T00:00:00Z",
            run_id=run_id,
        )
        store.save_paper(paper, "proj_pipe")
        papers.append(paper)
    return papers


def _request(papers, **overrides) -> PipelineStartRequest:
    base = dict(
        topic=TOPIC,
        run_id="run_pipe",
        paper_ids=[p.paper_id for p in papers],
        max_papers=25,
        max_gaps=3,
    )
    base.update(overrides)
    return PipelineStartRequest(**base)


def _search_response(papers, errors=None, requests=3) -> SearchResponse:
    return SearchResponse(
        run_id="run_counter",
        project_id="proj_pipe",
        topic=TOPIC,
        meta={"requests_made": requests, "cache_hits": 0},
        papers=papers,
        source_errors=errors or [],
        stats={},
    )


def _patch_search(monkeypatch, response):
    async def fake_pipeline(topic):
        return response

    monkeypatch.setattr(gap_module, "search_pipeline", fake_pipeline)


def _counter_paper(pid: str, abstract: str, doi: str) -> Paper:
    return Paper(
        paper_id=pid,
        title="A shared benchmark for agent memory",
        doi=doi,
        abstract=abstract,
        source="arxiv",
        source_url=f"https://arxiv.org/abs/{pid}",
        publication_year=2025,
        retrieved_at="2025-01-01T00:00:00Z",
    )


# --------------------------------------------------------------- not configured
@pytest.mark.asyncio
async def test_without_a_provider_the_pipeline_reports_not_configured(temp_db):
    papers = _store_papers(temp_db)
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, executed = await service.advance(temp_db, pipeline)

    assert executed == []
    assert pipeline.status == "not_configured"
    assert pipeline.provider == "LLM_NOT_CONFIGURED"
    assert "RLE_LLM_API_KEY" in pipeline.stage("planner").error
    assert pipeline.gaps == []
    assert temp_db.list_evidence_cards() == []
    assert temp_db.list_gaps() == []
    assert temp_db.count_llm_attempts() == 0
    assert all(r.status == "not_configured" for r in temp_db.list_llm_calls())


# ------------------------------------------------------------------ offline E2E
@pytest.mark.asyncio
async def test_offline_e2e_produces_a_full_auditable_chain(temp_db, llm_configured, monkeypatch):
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    fake = FakeLLMProvider(temp_db)
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, executed = await service.advance(temp_db, pipeline, provider=fake)

    assert executed == list(STAGE_SEQUENCE)
    assert pipeline.status == "completed"
    assert len(pipeline.selected_paper_ids) == 4
    cards = temp_db.list_evidence_cards(pipeline_id=pipeline.pipeline_id)
    assert len(cards) == 4
    assert all(c.extraction_method == "llm" for c in cards)
    assert all(c.field("method").evidence_source == "abstract" for c in cards)
    assert all(c.grounded_fields for c in cards)

    assert len(pipeline.gaps) == 1
    item = pipeline.gaps[0]
    assert item.critique is not None
    assert item.critique.evidence_grounding == 4
    assert item.counter.status == "NO_COUNTER_EVIDENCE_FOUND"
    assert item.validation.passed
    assert item.validation.unique_supporting_papers == 3
    assert item.gate.status == "accepted"
    assert "not a mathematical proof" in item.gate.notice

    gap = temp_db.get_gap(item.gap_id)
    assert gap is not None
    assert gap.discovery_mode == "llm_pipeline"
    assert gap.status == "accepted"
    assert gap.pipeline_id == pipeline.pipeline_id
    assert gap.candidate and gap.critique and gap.validation and gap.gate
    assert all(e.extraction_method == "llm" for e in gap.supporting_evidence)

    records = temp_db.list_llm_calls(pipeline_id=pipeline.pipeline_id)
    assert {r.agent_role for r in records} == {
        "research_planner",
        "literature_analyst",
        "gap_analyst",
        "gap_critic",
        "counter_query",
    }
    for record in records:
        assert record.prompt_hash and len(record.prompt_hash) == 64
        assert record.model == "fake-model"
        assert record.request_id
        assert record.created_at
        assert "test-only-key" not in json.dumps(record.model_dump())
    assert temp_db.count_llm_attempts() == len(fake.calls)


@pytest.mark.asyncio
async def test_hallucinated_span_is_rejected_not_trusted(temp_db, llm_configured, monkeypatch):
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    fake = FakeLLMProvider(temp_db, hallucinate={"pipe:p2": "limitations"})
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, _ = await service.advance(temp_db, pipeline, provider=fake)

    card = temp_db.get_evidence_card("pipe:p2", PROMPT_VERSION)
    assert "limitations" in [r["field"] for r in card.rejected_fields]
    assert "limitations" not in card.grounded_fields
    assert not card.field("limitations").is_filled
    clean = temp_db.get_evidence_card("pipe:p1", PROMPT_VERSION)
    assert clean.rejected_fields == []


@pytest.mark.asyncio
async def test_prior_art_raises_novelty_risk_and_blocks_acceptance(
    temp_db, llm_configured, monkeypatch
):
    papers = _store_papers(temp_db)
    prior = _counter_paper(
        "counter:1",
        "We introduce a shared benchmark reporting accuracy and F1 for agent memory.",
        "10.9999/counter.1",
    )
    _patch_search(monkeypatch, _search_response([prior]))
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, _ = await service.advance(temp_db, pipeline, provider=FakeLLMProvider(temp_db))

    item = pipeline.gaps[0]
    assert item.counter.status == "COUNTER_EVIDENCE_FOUND"
    assert item.counter.prior_art[0]["paper_id"] == "counter:1"
    assert item.validation.prior_art_collisions == 1
    assert item.validation.novelty_risk == "HIGH"
    assert item.gate.status != "accepted"
    gap = temp_db.get_gap(item.gap_id)
    assert gap.novelty_risk == "HIGH"
    assert gap.prior_art and gap.status == "needs_human_review"


@pytest.mark.asyncio
async def test_a_failed_search_is_not_reported_as_no_counter_evidence(
    temp_db, llm_configured, monkeypatch
):
    papers = _store_papers(temp_db)
    errors = [SourceError(source="openalex", keyword=TOPIC, status=503, detail="upstream down")]
    _patch_search(monkeypatch, _search_response([], errors=errors, requests=0))
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, _ = await service.advance(temp_db, pipeline, provider=FakeLLMProvider(temp_db))

    item = pipeline.gaps[0]
    assert item.counter.status == "COUNTER_SEARCH_FAILED"
    assert item.counter.errors
    assert item.gate.status != "accepted"
    assert not item.validation.passed
    assert any("did not complete" in r for r in item.validation.reasons)


# ------------------------------------------------------------- budget and resume
@pytest.mark.asyncio
async def test_budget_stop_keeps_finished_work_and_resumes(temp_db, llm_configured, monkeypatch):
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    llm_configured.llm_max_calls = 3
    fake = FakeLLMProvider(temp_db)
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, executed = await service.advance(temp_db, pipeline, provider=fake)

    assert pipeline.status == "awaiting_budget"
    assert "planner" in executed
    assert pipeline.stage("literature_analysis").status == "failed"
    assert "budget exhausted" in pipeline.stage("literature_analysis").error
    paid_cards = len(temp_db.list_evidence_cards(pipeline_id=pipeline.pipeline_id))
    assert 0 < paid_cards < 4
    assert temp_db.count_llm_attempts() == 3

    llm_configured.llm_max_calls = 60
    resumed = service.get_pipeline(temp_db, pipeline.pipeline_id)
    resumed, executed2 = await service.advance(temp_db, resumed, provider=fake)
    assert resumed.status == "completed"
    assert "planner" not in executed2
    assert len(temp_db.list_evidence_cards(pipeline_id=pipeline.pipeline_id)) == 4
    analyst_calls = [c for c in fake.calls if c["role"] == "literature_analyst"]
    assert len(analyst_calls) == 4


@pytest.mark.asyncio
async def test_a_finished_pipeline_does_not_call_the_llm_again(temp_db, llm_configured, monkeypatch):
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    fake = FakeLLMProvider(temp_db)
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, _ = await service.advance(temp_db, pipeline, provider=fake)
    before = len(fake.calls)
    attempts_before = temp_db.count_llm_attempts()

    again = service.get_pipeline(temp_db, pipeline.pipeline_id)
    again, executed = await service.advance(temp_db, again, provider=fake)
    assert executed == []
    assert again.status == "completed"
    assert len(fake.calls) == before
    assert temp_db.count_llm_attempts() == attempts_before


@pytest.mark.asyncio
async def test_a_second_pipeline_reuses_cached_cards_for_free(temp_db, llm_configured, monkeypatch):
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    first = FakeLLMProvider(temp_db)
    pipeline = service.create_pipeline(temp_db, _request(papers))
    await service.advance(temp_db, pipeline, provider=first)
    attempts_after_first = temp_db.count_llm_attempts()

    second = FakeLLMProvider(temp_db)
    pipeline2 = service.create_pipeline(temp_db, _request(papers))
    pipeline2, _ = await service.advance(temp_db, pipeline2, provider=second)
    assert pipeline2.status == "completed"
    assert not [c for c in second.calls if c["role"] == "literature_analyst"]
    assert temp_db.count_llm_attempts() == attempts_after_first
    # Cards belong to the paper, not to the run: the second pipeline reuses the
    # stored cards and records the reuse instead of paying for them again.
    assert pipeline2.stage("literature_analysis").outputs["from_cache"] == 4
    for paper_id in pipeline2.selected_paper_ids:
        assert temp_db.get_evidence_card(paper_id, PROMPT_VERSION) is not None
    assert len(pipeline2.gaps) == 1


@pytest.mark.asyncio
async def test_role_budget_stops_only_that_role(temp_db, llm_configured, monkeypatch):
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    llm_configured.llm_role_budgets = {**llm_configured.llm_role_budgets, "literature_analyst": 2}
    fake = FakeLLMProvider(temp_db)
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, _ = await service.advance(temp_db, pipeline, provider=fake)

    assert pipeline.status == "awaiting_budget"
    assert "role budget exhausted for literature_analyst" in pipeline.stage(
        "literature_analysis"
    ).error
    assert temp_db.count_llm_attempts("literature_analyst") == 2


# ------------------------------------------------------------------ critic input
@pytest.mark.asyncio
async def test_critic_never_sees_the_proposers_reasoning(temp_db, llm_configured, monkeypatch):
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    fake = FakeLLMProvider(temp_db)
    pipeline = service.create_pipeline(temp_db, _request(papers))
    await service.advance(temp_db, pipeline, provider=fake)

    critic_calls = [c for c in fake.calls if c["role"] == "gap_critic"]
    assert len(critic_calls) == 1
    payload = critic_calls[0]["payload"]
    for withheld in ("problem_context", "already_solved", "why_it_matters", "uncertainties", "novelty_risk", "novelty_rationale"):
        assert withheld not in payload
    assert payload["supporting_evidence"]
    assert all(ref["evidence_span"] for ref in payload["supporting_evidence"])


# ------------------------------------------------------------- malformed replies
@pytest.mark.asyncio
async def test_a_malformed_reply_fails_the_stage_and_is_not_cached(temp_db, llm_configured, monkeypatch):
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    fake = FakeLLMProvider(temp_db, malformed_roles=("gap_analyst",))
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, executed = await service.advance(temp_db, pipeline, provider=fake)

    assert pipeline.status == "failed"
    assert "gap_analysis" not in executed
    assert pipeline.gaps == []
    rejected = [r for r in temp_db.list_llm_calls() if r.status == "output_rejected"]
    assert len(rejected) == 1
    assert rejected[0].agent_role == "gap_analyst"
    cached_roles = [
        r["agent_role"] for r in temp_db.conn.execute("SELECT agent_role FROM llm_cache").fetchall()
    ]
    assert "gap_analyst" not in cached_roles

    good = FakeLLMProvider(temp_db)
    resumed = service.get_pipeline(temp_db, pipeline.pipeline_id)
    resumed, executed2 = await service.advance(temp_db, resumed, provider=good)
    assert resumed.status == "completed"
    assert "gap_analysis" in executed2


@pytest.mark.asyncio
async def test_a_risk_label_carrying_prose_is_rejected_not_coerced(
    temp_db, llm_configured, monkeypatch
):
    """A real DeepSeek reply was "MEDIUM: <justification>". The enum stays strict.

    The fix is a place to put the justification, not a lenient parser: silently
    splitting the string would hide a model that ignored the output contract.
    """
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))

    def prose_risk(payload):
        reply = gap_reply(payload)
        reply["candidates"][0]["novelty_risk"] = "MEDIUM: no shared metric family is reported."
        return reply

    fake = FakeLLMProvider(temp_db, replies={"gap_analyst": prose_risk})
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, executed = await service.advance(temp_db, pipeline, provider=fake)

    assert pipeline.status == "failed"
    assert "gap_analysis" not in executed
    assert pipeline.gaps == []
    rejected = [r for r in temp_db.list_llm_calls() if r.status == "output_rejected"]
    assert rejected[-1].agent_role == "gap_analyst"
    assert "novelty_risk" in rejected[-1].error
    cached_roles = [
        r["agent_role"] for r in temp_db.conn.execute("SELECT agent_role FROM llm_cache").fetchall()
    ]
    assert "gap_analyst" not in cached_roles


@pytest.mark.asyncio
async def test_the_risk_justification_is_persisted_beside_the_label(
    temp_db, llm_configured, monkeypatch
):
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    reason = "Only abstracts were available and no shared metric family is reported."

    def with_rationale(payload):
        reply = gap_reply(payload)
        reply["candidates"][0]["novelty_rationale"] = reason
        return reply

    fake = FakeLLMProvider(temp_db, replies={"gap_analyst": with_rationale})
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, _ = await service.advance(temp_db, pipeline, provider=fake)
    assert pipeline.status == "completed"

    # The proposer is told where the justification goes, and it survives to the record.
    analyst = next(c for c in fake.calls if c["role"] == "gap_analyst")
    assert "novelty_rationale" in analyst["payload"]["candidate_schema"]
    gap = temp_db.get_gap(pipeline.gaps[0].gap_id)
    assert gap.candidate["novelty_risk"] == "MEDIUM"
    assert gap.candidate["novelty_rationale"] == reason


@pytest.mark.asyncio
async def test_a_network_failure_is_recorded_and_falls_back_to_nothing(
    temp_db, llm_configured, monkeypatch
):
    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    fake = FakeLLMProvider(temp_db, fail_roles=("research_planner",))
    pipeline = service.create_pipeline(temp_db, _request(papers))
    pipeline, executed = await service.advance(temp_db, pipeline, provider=fake)

    assert executed == []
    assert pipeline.status == "failed"
    assert "fake provider unreachable" in pipeline.stage("planner").error
    failed = [r for r in temp_db.list_llm_calls() if r.status == "failed"]
    assert len(failed) == 1
    assert failed[0].latency_ms is not None
    assert temp_db.count_llm_attempts() == 1


# --------------------------------------------------------------------- selection
def test_selection_requires_an_abstract_and_dedupes_by_doi(temp_db):
    papers = _store_papers(temp_db, count=3)
    no_abstract = Paper(
        paper_id="pipe:noabs",
        title="Metadata only record",
        source="crossref",
        source_url="https://doi.org/10.9999/noabs",
        doi="10.9999/noabs",
        run_id="run_pipe",
        retrieved_at="2025-01-01T00:00:00Z",
    )
    temp_db.save_paper(no_abstract, "proj_pipe")
    duplicate = papers[0].model_copy(deep=True)
    duplicate.paper_id = "pipe:dup"
    duplicate.source = "crossref"
    temp_db.save_paper(duplicate, "proj_pipe")

    pipeline = service.create_pipeline(
        temp_db,
        _request(papers, paper_ids=[p.paper_id for p in papers] + ["pipe:noabs", "pipe:dup"]),
    )
    selected, detail = service.select_papers(temp_db, pipeline, max_papers=25)
    ids = [p.paper_id for p in selected]
    assert "pipe:noabs" not in ids
    assert "pipe:dup" not in ids
    assert detail["dropped_no_abstract"] == 1
    assert detail["dropped_duplicate_doi"] == 1
    assert len(selected) == 3


def test_selection_is_capped_and_never_expands_its_own_scope(temp_db):
    papers = _store_papers(temp_db, count=6)
    pipeline = service.create_pipeline(temp_db, _request(papers, max_papers=3))
    selected, detail = service.select_papers(temp_db, pipeline, max_papers=3)
    assert len(selected) == 3
    assert detail["selected"] == 3


# ------------------------------------------------------------------- provider API
@pytest.mark.asyncio
async def test_llm_status_and_audit_endpoints(temp_db, llm_configured, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    papers = _store_papers(temp_db)
    _patch_search(monkeypatch, _search_response([]))
    fake = FakeLLMProvider(temp_db)
    monkeypatch.setattr("app.services.gap_agents.LLMProvider", lambda store: fake)

    with TestClient(create_app()) as client:
        status = client.get("/api/llm/status").json()
        assert status["configured"] is True
        assert status["provider"] == "fake.invalid"
        assert status["calls_used"] == 0

        started = client.post(
            "/api/gap-pipeline/start",
            json={"topic": TOPIC, "run_id": "run_pipe", "paper_ids": [p.paper_id for p in papers]},
        )
        assert started.status_code == 200
        body = started.json()
        pipeline_id = body["pipeline"]["pipeline_id"]
        assert body["pipeline"]["status"] == "completed"

        detail = client.get(f"/api/gap-pipeline/{pipeline_id}").json()
        assert len(detail["evidence_cards"]) == 4
        assert len(detail["gaps"]) == 1
        assert detail["llm_calls"]
        assert "test-only-key" not in json.dumps(detail)

        listing = client.get("/api/gap-pipeline").json()
        assert listing["total"] == 1

        calls = client.get("/api/llm/calls", params={"agent_role": "gap_critic"}).json()
        assert len(calls) == 1
        assert calls[0]["prompt_hash"]

        advanced = client.post(
            f"/api/gap-pipeline/{pipeline_id}/advance", json={"max_stages": 7}
        ).json()
        assert advanced["executed"] == []

        missing = client.get("/api/gap-pipeline/does-not-exist")
        assert missing.status_code == 404


def test_start_requires_a_real_paper_scope(temp_db):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        response = client.post("/api/gap-pipeline/start", json={"topic": TOPIC})
        assert response.status_code == 400
        assert client.get("/api/llm/status").json()["status"] == "LLM_NOT_CONFIGURED"