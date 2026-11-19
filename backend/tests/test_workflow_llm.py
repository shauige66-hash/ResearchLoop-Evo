"""Offline integration tests: the LLM gap pipeline inside the 18-step workflow.

The workflow keeps its step ids and its deterministic services. These tests pin
down what changes when a provider is configured: the LLM stages run as substeps,
their records are persisted, a budget stop halts the run, and a resume reuses the
finished work instead of paying for it again.

Every LLM reply comes from `tests.fakes.FakeLLMProvider`; no real API is contacted.
"""

from __future__ import annotations

import json

import pytest

from app.models.gap_pipeline import PROMPT_VERSION
from app.services import workflow as workflow_module

from .fakes import FakeLLMProvider
from .test_workflow import _approve, _response, _start, _verify


@pytest.fixture
def offline(monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.services.workflow.search_pipeline", AsyncMock(side_effect=_response)
    )
    monkeypatch.setattr("app.services.workflow.verify_doi", AsyncMock(side_effect=_verify))
    monkeypatch.setattr("app.services.gap.search_pipeline", AsyncMock(side_effect=_response))
    monkeypatch.setattr(
        "app.services.experiment.search_pipeline", AsyncMock(side_effect=_response)
    )


@pytest.fixture
def fake_llm(temp_db, llm_configured, monkeypatch):
    fake = FakeLLMProvider(temp_db)
    monkeypatch.setattr(workflow_module, "LLMProvider", lambda store: fake)
    return fake


def _pipeline(store, workflow):
    return store.get_gap_pipeline(workflow.context["gap_pipeline_id"])


# --------------------------------------------------------------- not configured
@pytest.mark.asyncio
async def test_without_a_provider_the_workflow_stays_deterministic(temp_db, offline):
    workflow = _start(temp_db)
    workflow, executed = await workflow_module.advance(temp_db, workflow, max_steps=7)

    assert executed[-1] == "counter_evidence_search"
    assert workflow.step("human_approval").status == "pending"
    planning = workflow.step("search_planning").outputs
    assert planning["llm_pipeline"]["status"] == "not_configured"
    assert "RLE_LLM_API_KEY" in planning["llm_pipeline"]["notice"]
    assert planning["planner_queries_for_retrieval"] == []
    extraction = workflow.step("paper_extraction").outputs
    assert extraction["extraction_mode"] == "heuristic"
    assert extraction["llm_evidence_cards"] == 0
    discovery = workflow.step("gap_discovery").outputs
    assert discovery["discovery_mode"] == "rule_based"
    assert "RLE_LLM_API_KEY" in discovery["fallback_reason"]
    assert discovery["gap_count"] >= 1
    assert temp_db.count_llm_attempts() == 0
    assert temp_db.list_evidence_cards() == []


# ------------------------------------------------------------------ configured
@pytest.mark.asyncio
async def test_the_llm_chain_runs_inside_the_18_steps(temp_db, offline, fake_llm):
    workflow = _start(temp_db)
    workflow, _ = await workflow_module.advance(temp_db, workflow, max_steps=8)
    pipeline = _pipeline(temp_db, workflow)

    planning = workflow.step("search_planning").outputs
    assert planning["llm_pipeline"]["stages_executed"] == ["planner"]
    assert len(planning["planner_queries_for_retrieval"]) == 2
    discovery_step = workflow.step("literature_discovery").outputs
    assert discovery_step["planner_queries_used"] == planning["planner_queries_for_retrieval"]

    extraction = workflow.step("paper_extraction").outputs
    assert extraction["extraction_mode"] == "heuristic"
    assert extraction["llm_evidence_cards"] == 6
    assert extraction["llm_card_grounded_fields"] > 0
    assert pipeline.stage("literature_analysis").status == "completed"

    discovery = workflow.step("gap_discovery").outputs
    assert discovery["discovery_mode"] == "llm_pipeline"
    assert discovery["fallback_reason"] == ""
    assert discovery["gap_count"] == 1
    assert workflow.context["gap_ids"] == [
        item.gap_id for item in pipeline.gaps if item.gap_id
    ]

    counter = workflow.step("counter_evidence_search").outputs
    assert counter["gaps_searched"] == 1
    entry = counter["per_gap"][0]
    assert entry["counter_status"] == "NO_COUNTER_EVIDENCE_FOUND"
    assert entry["scope"]["sources"] == ["openalex", "crossref", "arxiv"]
    assert entry["scope"]["rejected_as_not_addressing_claim"] == 3

    gap = temp_db.get_gap(workflow.context["gap_ids"][0])
    assert gap.discovery_mode == "llm_pipeline"
    assert gap.pipeline_id == pipeline.pipeline_id
    assert gap.status == "accepted"
    assert gap.critique and gap.validation and gap.gate
    assert gap.candidate["gap_type"] == "evaluation_gap"
    assert all(e.extraction_method == "llm" for e in gap.supporting_evidence)
    assert len(gap.supporting_papers) == 3
    assert "not a mathematical proof" in gap.gate["notice"]

    # The human gate is still closed: a system gate pass is not a human approval.
    assert workflow.status == "awaiting_human"
    assert workflow.current_step == "human_approval"
    assert "accepted_gap_id" not in workflow.context

    roles = {r.agent_role for r in temp_db.list_llm_calls(pipeline_id=pipeline.pipeline_id)}
    assert roles == {
        "research_planner",
        "literature_analyst",
        "gap_analyst",
        "gap_critic",
        "counter_query",
    }
    assert temp_db.count_llm_attempts() == len(fake_llm.calls)
    for record in temp_db.list_llm_calls():
        assert "test-only-key" not in json.dumps(record.model_dump())


@pytest.mark.asyncio
async def test_the_heuristic_paper_fields_are_not_overwritten_by_cards(
    temp_db, offline, fake_llm
):
    workflow = _start(temp_db)
    workflow, _ = await workflow_module.advance(temp_db, workflow, max_steps=4)
    run_id = workflow.context["literature_run_id"]
    papers, _ = temp_db.list_papers(run_id=run_id, page=1, page_size=50)
    for paper in papers:
        assert paper.method.extraction_method == "heuristic"
        card = temp_db.get_evidence_card(paper.paper_id, PROMPT_VERSION)
        assert card is not None
        assert card.extraction_method == "llm"
        assert card.field("method").evidence_source == "abstract"


# ------------------------------------------------------------- budget and resume
@pytest.mark.asyncio
async def test_a_budget_stop_halts_the_step_and_resume_reuses_cards(
    temp_db, offline, fake_llm, llm_configured, monkeypatch
):
    monkeypatch.setattr(llm_configured, "llm_max_calls", 3, raising=False)
    workflow = _start(temp_db)
    workflow, executed = await workflow_module.advance(temp_db, workflow, max_steps=7)

    assert executed == [
        "research_topic",
        "search_planning",
        "literature_discovery",
        "paper_extraction",
    ]
    assert workflow.status == "awaiting_budget"
    step = workflow.step("paper_extraction")
    assert step.status == "awaiting_budget"
    assert "预算" in step.notice
    pipeline = _pipeline(temp_db, workflow)
    assert pipeline.status == "awaiting_budget"
    assert pipeline.stage("planner").status == "completed"
    assert len(temp_db.list_evidence_cards()) == 2
    assert workflow.step("literature_matrix").status == "pending"
    analyst_calls = fake_llm.roles_called().count("literature_analyst")
    assert analyst_calls == 2

    monkeypatch.setattr(llm_configured, "llm_max_calls", 60, raising=False)
    workflow, executed = await workflow_module.advance(temp_db, workflow, max_steps=3)
    assert executed == ["paper_extraction", "literature_matrix", "gap_discovery"]
    assert workflow.step("paper_extraction").status == "completed"
    assert len(temp_db.list_evidence_cards()) == 6
    assert fake_llm.roles_called().count("literature_analyst") == 6
    assert workflow.step("gap_discovery").outputs["discovery_mode"] == "llm_pipeline"


@pytest.mark.asyncio
async def test_rewinding_to_gap_discovery_does_not_repay_the_llm(
    temp_db, offline, fake_llm
):
    workflow = _start(temp_db)
    workflow, _ = await workflow_module.advance(temp_db, workflow, max_steps=7)
    paid = len(fake_llm.calls)
    gap_ids = list(workflow.context["gap_ids"])

    workflow, executed = await workflow_module.advance(
        temp_db, workflow, max_steps=2, from_step="gap_discovery"
    )
    assert executed == ["gap_discovery", "counter_evidence_search"]
    assert workflow.context["gap_ids"] == gap_ids
    assert len(fake_llm.calls) == paid
    pipeline = _pipeline(temp_db, workflow)
    assert pipeline.stage("gap_analysis").outputs["persisted_gap_ids"] == gap_ids


@pytest.mark.asyncio
async def test_a_broken_planner_does_not_block_retrieval(temp_db, offline, llm_configured, monkeypatch):
    fake = FakeLLMProvider(temp_db, fail_roles=("research_planner",))
    monkeypatch.setattr(workflow_module, "LLMProvider", lambda store: fake)
    workflow = _start(temp_db)
    workflow, executed = await workflow_module.advance(temp_db, workflow, max_steps=3)

    assert executed == ["research_topic", "search_planning", "literature_discovery"]
    assert workflow.step("search_planning").status == "completed"
    assert workflow.step("search_planning").outputs["planner_queries_for_retrieval"] == []
    pipeline = _pipeline(temp_db, workflow)
    assert pipeline.stage("planner").status == "skipped"
    assert pipeline.stage("planner").error
    assert workflow.context["paper_ids"]


# ------------------------------------------------- the dossier as an audit record
@pytest.mark.asyncio
async def test_the_dossier_alone_answers_every_audit_question(temp_db, offline, fake_llm):
    """A completed 18-step run must leave a dossier that can be audited on its own.

    Counts are not an audit trail: the dossier has to carry the claim, the papers,
    the verbatim spans, what was searched for counter-evidence, the critic's
    scores, the Python checks and the final human decision.
    """
    workflow = _start(temp_db)
    workflow, _ = await workflow_module.advance(temp_db, workflow, max_steps=18)
    assert workflow.status == "awaiting_human"
    workflow = await _approve(temp_db, workflow)
    workflow, _ = await workflow_module.advance(temp_db, workflow, max_steps=18)
    assert workflow.current_step == "promotion_decision"
    workflow = workflow_module.record_decision(
        temp_db,
        workflow,
        decision="keep",
        decided_by="reviewer",
        version_id=None,
        reason="offline e2e: reference set is not human-confirmed",
    )
    workflow, _ = await workflow_module.advance(temp_db, workflow, max_steps=18)
    assert workflow.status == "completed"

    dossier = workflow.step("research_dossier").outputs
    assert dossier["gaps"], "the dossier must describe the discovered gap"
    entry = dossier["gaps"][0]
    chain = entry["evidence_chain"]

    # 1-2. what the gap is and why it may exist
    assert chain["gap_claim"].strip()
    assert chain["why_it_matters"].strip()
    assert chain["unresolved_boundary"].strip()
    assert chain["candidate_research_question"].strip()
    assert chain["minimum_experiment"].strip()

    # 3. which real papers support it
    run_id = workflow.context["literature_run_id"]
    papers, _ = temp_db.list_papers(run_id=run_id, page=1, page_size=50)
    by_id = {p.paper_id: p for p in papers}
    assert len(chain["supporting_papers"]) >= 3
    for item in chain["supporting_papers"]:
        assert item["paper_id"] in by_id
        assert item["title"] == by_id[item["paper_id"]].title
        assert item["doi"]

    # 4. the verbatim evidence behind every supporting claim
    assert chain["supporting_evidence"]
    for ev in chain["supporting_evidence"]:
        assert ev["evidence_source"] == "abstract"
        assert ev["extraction_method"] == "llm"
        assert ev["evidence_span"] in (by_id[ev["paper_id"]].abstract or "")

    # 5-7. what may refute it, what was actively searched, and any prior art
    assert chain["counter_search"]["queries"]
    assert chain["counter_search"]["scope"]["sources"] == ["openalex", "crossref", "arxiv"]
    assert chain["counter_search"]["status"] in {
        "NO_COUNTER_EVIDENCE_FOUND",
        "COUNTER_EVIDENCE_FOUND",
        "COUNTER_SEARCH_FAILED",
        "NOT_RUN",
    }
    assert isinstance(chain["counter_evidence"], list)
    assert isinstance(chain["prior_art"], list)
    assert chain["scope_notice"]

    # 8. the critic's own scores, not a single blended number
    critic = chain["critic"]
    for dimension in ("evidence_grounding", "cross_paper_support", "specificity", "testability"):
        assert 0 <= critic[dimension] <= 5
    assert critic["recommended_action"] in {"accept", "revise", "reject"}
    assert critic["novelty_risk"] in {"LOW", "MEDIUM", "HIGH"}

    # 9. the independent Python verdict
    validation = chain["python_validation"]
    assert validation["checks"]
    assert validation["unique_supporting_papers"] >= 3
    assert {c["name"] for c in validation["checks"]} >= {
        "supporting_papers_exist",
        "evidence_spans_verbatim",
        "no_duplicate_paper_counting",
        "counter_search_completed",
    }
    assert chain["gate"]["status"] in {"accepted", "needs_human_review", "rejected"}
    assert "not a mathematical proof" in chain["gate"]["notice"]

    # 10. the final status, including the human decision
    assert chain["final_status"] == "accepted"
    assert chain["human_note"] == "ok"
    assert dossier["accepted_gap_id"] == entry["gap_id"]

    # the LLM block reports real usage and never leaks the key
    llm = dossier["llm"]
    assert llm["configured"] is True
    assert llm["model"]
    assert llm["calls_used"] == len(fake_llm.calls)
    assert llm["evidence_cards"] == len(_pipeline(temp_db, workflow).selected_paper_ids)
    assert llm["gap_pipeline_status"] == "completed"
    assert "test-only-key" not in json.dumps(dossier)