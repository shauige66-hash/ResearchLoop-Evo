"""Offline tests for the 18-step workflow orchestrator.

No network: retrieval, DOI verification and counter-evidence search are patched at
their use sites with responses built from the real heuristic extractor, so every
step is exercised against the same record shapes the live pipeline writes.
"""

from __future__ import annotations

import json
from itertools import count
from unittest.mock import AsyncMock, patch

import pytest

from app.models.experiment import BenchmarkReference
from app.models.paper import Paper, SearchMeta
from app.models.schemas import SearchResponse, TopicInput
from app.models.skill import SKILL_ID
from app.models.workflow import HUMAN_STEPS, STEP_SEQUENCE, new_steps
from app.services.classify import classify_method
from app.services.extract import extract_from_abstract
from app.services.experiment import ensure_seed_skill
from app.services.evolution import salient_terms
from app.services.workflow import advance, create_workflow, record_approval, record_decision

TOPIC = "agent experience learning"
_RUN_COUNTER = count(1)

_ABSTRACTS = [
    (
        "skill / experience learning",
        "We propose a skill library that records reusable procedures. We evaluate on the "
        "AgentBench dataset and report accuracy. Results show improved task completion. "
        "However, a limitation is that generalization to unseen subtopics cannot be guaranteed.",
    ),
    (
        "skill / experience learning",
        "We present a skill learning loop built from failure trajectories. We evaluate on the "
        "WebArena corpus and measure recall. Results show better reuse of procedures. "
        "However, the limitation of weak generalization across domains still remains.",
    ),
    (
        "memory-augmented agent",
        "We develop an episodic memory module for long horizon tasks. We evaluate on the "
        "LongMem dataset and report precision. Results show fewer repeated mistakes. "
        "However, a limitation is that generalization to new task families cannot be assured.",
    ),
    (
        "memory-augmented agent",
        "We propose a semantic memory bank with consolidation. Experiments on the MemoryBench "
        "corpus report F1. Results show improved retention. However, the limitation of "
        "limited generalization beyond the training distribution remains.",
    ),
    (
        "retrieval-augmented generation",
        "We design a retrieval-augmented pipeline with dense retrieval. We evaluate on the "
        "SciDocs corpus and report MRR. Results show higher evidence coverage. However, a "
        "limitation is that generalization to unseen subtopics cannot be verified.",
    ),
    (
        "retrieval-augmented generation",
        "We present a retrieval augmented agent with reranking. We evaluate on the BEIR "
        "dataset and measure accuracy. Results show stronger grounding. However, the "
        "limitation of poor generalization to new domains still remains.",
    ),
]


def _papers(run_id: str = "run_test") -> list[Paper]:
    papers = []
    for index, (_label, abstract) in enumerate(_ABSTRACTS, start=1):
        paper = Paper(
            paper_id=f"openalex:W{index}",
            title=f"Study {index} of {TOPIC}",
            authors=["A. Researcher"],
            publication_year=2023 + (index % 3),
            venue="Test Venue",
            doi=f"10.1234/wf.{index}",
            abstract=abstract,
            source="openalex" if index % 2 else "crossref",
            source_url=f"https://example.org/{index}",
            run_id=run_id,
        )
        extract_from_abstract(paper)
        paper.method_class = classify_method(paper)
        papers.append(paper)
    return papers


def _response(topic: TopicInput, run_id: str | None = None) -> SearchResponse:
    # The real pipeline mints a fresh run id per call; a retry must not collide with
    # the failed attempt's record.
    run_id = run_id or f"run_test_{next(_RUN_COUNTER)}"
    papers = _papers(run_id)
    return SearchResponse(
        run_id=run_id,
        project_id="proj_test",
        topic=topic.topic,
        meta=SearchMeta(
            retrieved_at="2026-01-01T00:00:00+00:00",
            duration_ms=120,
            cache_hits=1,
            requests_made=3,
            sources_requested=list(topic.sources),
            sources_failed=[],
            keywords_used=[],
        ).model_dump(),
        papers=papers[: topic.top_k],
        source_errors=[],
        stats={"cache_hits": 1, "requests_made": 3},
    )


def _empty_response(topic: TopicInput) -> SearchResponse:
    response = _response(topic)
    response.papers = []
    return response


async def _verify(doi: str) -> BenchmarkReference:
    return BenchmarkReference(
        doi=doi.strip().lower(),
        title=f"Verified work for {doi}",
        source_url=f"https://doi.org/{doi}",
        publication_year=2024,
        verified_via="crossref",
        verified_at="2026-01-01T00:00:00+00:00",
    )


@pytest.fixture
def offline(monkeypatch):
    """Patch every network entry point the workflow can reach."""
    monkeypatch.setattr(
        "app.services.workflow.search_pipeline", AsyncMock(side_effect=_response)
    )
    monkeypatch.setattr("app.services.workflow.verify_doi", AsyncMock(side_effect=_verify))
    monkeypatch.setattr("app.services.gap.search_pipeline", AsyncMock(side_effect=_response))
    monkeypatch.setattr(
        "app.services.experiment.search_pipeline", AsyncMock(side_effect=_response)
    )


def _start(store, **kw) -> object:
    ensure_seed_skill(store)
    defaults = dict(
        topic=TOPIC,
        query=TOPIC,
        sources=["openalex", "crossref", "arxiv"],
        top_k=12,
        year_from=None,
        year_to=None,
        prefer_reviews=False,
    )
    defaults.update(kw)
    return create_workflow(store, **defaults)


async def _to_approval(store, workflow):
    workflow, _ = await advance(store, workflow, max_steps=18)
    return workflow


async def _approve(store, workflow, decision="accepted"):
    gap_id = workflow.context["gap_ids"][0]
    return record_approval(
        store, workflow, gap_id=gap_id, decision=decision, decided_by="reviewer", human_note="ok"
    )


async def _to_decision(store, workflow):
    workflow = await _to_approval(store, workflow)
    workflow = await _approve(store, workflow)
    workflow, _ = await advance(store, workflow, max_steps=18)
    return workflow


# ------------------------------------------------------------------ structure
def test_the_sequence_has_eighteen_ordered_steps():
    assert len(STEP_SEQUENCE) == 18
    assert len(set(STEP_SEQUENCE)) == 18
    assert [s.step_id for s in new_steps()] == list(STEP_SEQUENCE)
    assert [s.index for s in new_steps()] == list(range(1, 19))


def test_only_two_steps_wait_for_a_human():
    assert HUMAN_STEPS == {"human_approval", "promotion_decision"}


def test_a_new_workflow_is_persisted_with_every_step_pending(temp_db):
    workflow = _start(temp_db)
    stored = temp_db.get_workflow(workflow.workflow_id)
    assert stored is not None
    assert stored.status == "running"
    assert all(s.status == "pending" for s in stored.steps)
    assert stored.completed_steps == 0


@pytest.mark.asyncio
async def test_advance_is_bounded_by_max_steps(temp_db, offline):
    workflow = _start(temp_db)
    workflow, executed = await advance(temp_db, workflow, max_steps=2)
    assert executed == ["research_topic", "search_planning"]
    assert workflow.step("literature_discovery").status == "pending"


@pytest.mark.asyncio
async def test_each_step_records_real_inputs_and_outputs(temp_db, offline):
    workflow = _start(temp_db)
    workflow, _ = await advance(temp_db, workflow, max_steps=5)
    for step_id in STEP_SEQUENCE[:5]:
        step = workflow.step(step_id)
        assert step.status == "completed", step_id
        assert step.inputs, f"{step_id} recorded no input"
        assert step.outputs, f"{step_id} recorded no output"
        assert step.attempts == 1
        assert step.finished_at


@pytest.mark.asyncio
async def test_state_survives_a_reload_between_steps(temp_db, offline):
    workflow = _start(temp_db)
    await advance(temp_db, workflow, max_steps=3)
    reloaded = temp_db.get_workflow(workflow.workflow_id)
    assert reloaded.step("literature_discovery").status == "completed"
    assert reloaded.context["literature_run_id"]
    _, executed = await advance(temp_db, reloaded, max_steps=1)
    assert executed == ["paper_extraction"]


# ------------------------------------------------------------------ retrieval
@pytest.mark.asyncio
async def test_discovery_persists_the_retrieved_papers(temp_db, offline):
    workflow = _start(temp_db)
    workflow, _ = await advance(temp_db, workflow, max_steps=3)
    outputs = workflow.step("literature_discovery").outputs
    assert outputs["paper_count"] == 6
    assert outputs["requests_made"] == 3
    run_id = workflow.context["literature_run_id"]
    papers, total = temp_db.list_papers(run_id=run_id, page=1, page_size=50)
    assert total == 6
    assert all(p.run_id == run_id for p in papers)


@pytest.mark.asyncio
async def test_an_empty_retrieval_fails_the_step_with_a_real_error(temp_db, offline, monkeypatch):
    monkeypatch.setattr(
        "app.services.workflow.search_pipeline", AsyncMock(side_effect=_empty_response)
    )
    workflow = _start(temp_db)
    workflow, executed = await advance(temp_db, workflow, max_steps=18)
    assert executed == ["research_topic", "search_planning", "literature_discovery"]
    assert workflow.status == "failed"
    step = workflow.step("literature_discovery")
    assert step.status == "failed"
    assert "no paper" in step.error
    assert workflow.step("paper_extraction").status == "pending"


@pytest.mark.asyncio
async def test_a_failed_step_can_be_retried_in_place(temp_db, offline, monkeypatch):
    failing = AsyncMock(side_effect=_empty_response)
    monkeypatch.setattr("app.services.workflow.search_pipeline", failing)
    workflow = _start(temp_db)
    workflow, _ = await advance(temp_db, workflow, max_steps=3)
    assert workflow.status == "failed"
    monkeypatch.setattr(
        "app.services.workflow.search_pipeline", AsyncMock(side_effect=_response)
    )
    workflow, executed = await advance(temp_db, workflow, max_steps=1)
    assert executed == ["literature_discovery"]
    assert workflow.step("literature_discovery").status == "completed"
    assert workflow.step("literature_discovery").attempts == 2
    assert workflow.step("literature_discovery").error is None


@pytest.mark.asyncio
async def test_retrieval_transport_errors_are_recorded_not_swallowed(temp_db, offline, monkeypatch):
    monkeypatch.setattr(
        "app.services.workflow.search_pipeline",
        AsyncMock(side_effect=RuntimeError("connection reset by peer")),
    )
    workflow = _start(temp_db)
    workflow, _ = await advance(temp_db, workflow, max_steps=3)
    step = workflow.step("literature_discovery")
    assert step.status == "failed"
    assert "connection reset by peer" in step.error


# ------------------------------------------------------------------ extraction
@pytest.mark.asyncio
async def test_extraction_reports_heuristic_mode_and_keeps_unknown_fields(temp_db, offline):
    workflow = _start(temp_db)
    workflow, _ = await advance(temp_db, workflow, max_steps=4)
    outputs = workflow.step("paper_extraction").outputs
    assert outputs["extraction_mode"] == "heuristic"
    assert outputs["fields_audited"] == 10
    assert outputs["grounded_cells"] > 0
    assert outputs["unknown_cells"] > 0
    grounded = [f for f, v in outputs["per_field"].items() if v["grounded"]]
    assert "limitations" in grounded
    assert outputs["per_field"]["limitations"]["example_span"]


@pytest.mark.asyncio
async def test_matrix_step_summarises_the_real_rows(temp_db, offline):
    workflow = _start(temp_db)
    workflow, _ = await advance(temp_db, workflow, max_steps=5)
    outputs = workflow.step("literature_matrix").outputs
    assert outputs["row_count"] == 6
    assert len(outputs["method_distribution"]) == 3
    assert outputs["available_filters"]["method_class"]
    assert outputs["year_range"] == [2023, 2025]


# ------------------------------------------------------------------ gaps
@pytest.mark.asyncio
async def test_gap_discovery_produces_reviewable_candidates(temp_db, offline):
    workflow = _start(temp_db)
    workflow, _ = await advance(temp_db, workflow, max_steps=6)
    outputs = workflow.step("gap_discovery").outputs
    assert outputs["gap_count"] >= 1
    for gap in outputs["gaps"]:
        assert gap["status"] == "needs_human_review"
        assert len(gap["supporting_papers"]) >= 2
    assert workflow.context["gap_ids"]


@pytest.mark.asyncio
async def test_counter_evidence_records_the_real_search_scope(temp_db, offline):
    workflow = _start(temp_db)
    workflow, _ = await advance(temp_db, workflow, max_steps=7)
    outputs = workflow.step("counter_evidence_search").outputs
    assert outputs["gaps_searched"] == len(workflow.context["gap_ids"])
    for entry in outputs["per_gap"]:
        assert entry["scope"]["sources"] == ["openalex", "crossref", "arxiv"]
        assert entry["query"]
        assert "acceptance_rule" in entry["scope"]


@pytest.mark.asyncio
async def test_the_workflow_stops_at_the_human_gate(temp_db, offline):
    workflow = _start(temp_db)
    workflow, executed = await advance(temp_db, workflow, max_steps=18)
    assert workflow.status == "awaiting_human"
    assert workflow.current_step == "human_approval"
    assert executed[-1] == "human_approval"
    assert workflow.step("hypothesis").status == "pending"
    assert "accepted_gap_id" not in workflow.context


@pytest.mark.asyncio
async def test_rejecting_every_candidate_keeps_the_gate_closed(temp_db, offline):
    workflow = _start(temp_db)
    workflow = await _to_approval(temp_db, workflow)
    for gap_id in workflow.context["gap_ids"]:
        workflow = record_approval(
            temp_db, workflow, gap_id=gap_id, decision="rejected",
            decided_by="reviewer", human_note="not convincing",
        )
    workflow, _ = await advance(temp_db, workflow, max_steps=18)
    assert workflow.status == "awaiting_human"
    assert workflow.step("hypothesis").status == "pending"
    assert temp_db.get_gap(workflow.context["gap_ids"][0]).status == "rejected"


@pytest.mark.asyncio
async def test_a_gap_from_another_workflow_cannot_be_approved(temp_db, offline):
    workflow = _start(temp_db)
    workflow = await _to_approval(temp_db, workflow)
    other = await _to_approval(temp_db, _start(temp_db))
    foreign_gap = other.context["gap_ids"][0]
    assert temp_db.get_gap(foreign_gap) is not None
    with pytest.raises(ValueError, match="not produced by this workflow"):
        record_approval(
            temp_db, workflow, gap_id=foreign_gap, decision="accepted",
            decided_by="reviewer", human_note="",
        )


@pytest.mark.asyncio
async def test_approval_is_recorded_in_the_gap_review_trail(temp_db, offline):
    workflow = _start(temp_db)
    workflow = await _to_approval(temp_db, workflow)
    workflow = await _approve(temp_db, workflow)
    gap_id = workflow.context["accepted_gap_id"]
    assert temp_db.get_gap(gap_id).status == "accepted"
    reviews = temp_db.list_gap_reviews(gap_id)
    assert reviews and reviews[-1]["status"] == "accepted"
    workflow, _ = await advance(temp_db, workflow, max_steps=1)
    assert workflow.step("human_approval").status == "completed"
    assert workflow.step("human_approval").outputs["decided_by"] == "reviewer"


# ------------------------------------------------------------------ hypothesis
@pytest.mark.asyncio
async def test_hypothesis_is_marked_under_test_and_cites_the_gap(temp_db, offline):
    workflow = _start(temp_db)
    workflow = await _to_approval(temp_db, workflow)
    workflow = await _approve(temp_db, workflow)
    workflow, _ = await advance(temp_db, workflow, max_steps=2)
    outputs = workflow.step("hypothesis").outputs
    assert outputs["hypothesis_status"] == "under_test"
    assert outputs["gap_id"] == workflow.context["accepted_gap_id"]
    gap = temp_db.get_gap(outputs["gap_id"])
    assert gap.unresolved_question in outputs["hypothesis"]


# ------------------------------------------------------------------ spec
@pytest.mark.asyncio
async def test_spec_derives_cases_from_retrieved_dois_and_verifies_them(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    outputs = workflow.step("experiment_spec").outputs
    assert outputs["verification_errors"] == []
    assert len(outputs["case_ids"]) == 3
    assert set(outputs["split_counts"]) == {"development", "validation", "holdout"}
    for case in outputs["cases"]:
        assert case["reference_count"] > 0
        assert case["confirmed_count"] == 0
        assert case["reference_status"] == "awaiting_reference_set"
        stored = temp_db.get_benchmark_case(case["case_id"])
        assert stored.source == "derived_from_run"
        assert stored.verified_by == "crossref/openalex"
        assert all(r.verified_via != "manual" for r in stored.references)


@pytest.mark.asyncio
async def test_spec_discloses_that_references_come_from_its_own_retrieval(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    outputs = workflow.step("experiment_spec").outputs
    assert "own retrieval" in outputs["reference_provenance"]
    for case in outputs["cases"]:
        assert "own retrieval" in temp_db.get_benchmark_case(case["case_id"]).notes


@pytest.mark.asyncio
async def test_spec_refuses_to_build_a_benchmark_on_unverified_dois(temp_db, offline, monkeypatch):
    from app.services.http import HttpFailure

    monkeypatch.setattr(
        "app.services.workflow.verify_doi",
        AsyncMock(side_effect=HttpFailure(status=404, detail="not found", source="crossref")),
    )
    workflow = _start(temp_db)
    workflow = await _to_approval(temp_db, workflow)
    workflow = await _approve(temp_db, workflow)
    workflow, _ = await advance(temp_db, workflow, max_steps=18)
    step = workflow.step("experiment_spec")
    assert step.status == "failed"
    assert "unverified identifiers" in step.error
    assert workflow.step("baseline_execution").status == "pending"


@pytest.mark.asyncio
async def test_spec_arms_differ_and_the_candidate_stays_inside_the_budget(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    spec = temp_db.get_spec(workflow.context["spec_id"])
    assert spec.baseline_version_id != spec.candidate_version_id
    baseline = temp_db.get_skill_version(spec.baseline_version_id)
    candidate = temp_db.get_skill_version(spec.candidate_version_id)
    assert candidate.parent_version == baseline.version_id
    assert candidate.status == "candidate"
    assert candidate.strategy.retrieval_budget.max_api_requests <= spec.max_api_requests
    assert candidate.strategy.retrieval_budget.top_k == spec.top_k
    assert candidate.strategy.query_templates != baseline.strategy.query_templates
    assert candidate.source_trials


@pytest.mark.asyncio
async def test_the_seed_term_is_vocabulary_the_case_does_not_already_use(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    seed = workflow.step("experiment_spec").outputs["seed"]
    case = temp_db.get_benchmark_case(seed["preview_case_id"])
    gap = temp_db.get_gap(workflow.context["accepted_gap_id"])
    template = seed["after_templates"][0]
    if template == "{query} {topic}":
        assert "no term absent" in seed["grounding"]
        assert "same papers as the baseline" in seed["grounding"]
    else:
        added = template.removeprefix("{query} ")
        known = set(salient_terms(f"{case.topic} {case.query}")) | set(
            salient_terms(gap.unresolved_question)
        )
        assert added not in known
        assert added in seed["grounding"]


@pytest.mark.asyncio
async def test_the_active_version_is_untouched_by_spec_creation(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    active = temp_db.list_skill_versions(skill_id=SKILL_ID, status="active")
    assert len(active) == 1
    assert active[0].version_number == 1


# ------------------------------------------------------------------ execution
@pytest.mark.asyncio
async def test_both_arms_execute_over_development_and_validation_only(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    baseline = workflow.step("baseline_execution").outputs
    candidate = workflow.step("candidate_execution").outputs
    assert baseline["run_count"] > 0
    assert candidate["run_count"] == baseline["run_count"]
    assert {r["split"] for r in baseline["runs"]} <= {"development", "validation"}
    assert all(r["arm"] == "baseline" for r in baseline["runs"])
    assert all(r["arm"] == "candidate" for r in candidate["runs"])
    assert "holdout: no case in this split" not in baseline["skipped_splits"]
    spec_id = workflow.context["spec_id"]
    assert temp_db.list_experiment_runs(spec_id=spec_id, split="holdout") == []


@pytest.mark.asyncio
async def test_every_executed_run_keeps_a_raw_snapshot(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    runs = temp_db.list_experiment_runs(spec_id=workflow.context["spec_id"])
    assert runs
    for run in runs:
        assert run.raw_snapshot_path
        payload = json.loads(open(run.raw_snapshot_path, encoding="utf-8").read())
        assert payload["response"]["papers"]
        assert payload["skill_version"]["version_id"] == run.skill_version_id


@pytest.mark.asyncio
async def test_independent_evaluation_recomputes_from_the_snapshot(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    outputs = workflow.step("independent_evaluation").outputs
    assert outputs["runs_without_snapshot"] == []
    for entry in outputs["evaluations"]:
        assert entry["recomputed_from"].endswith(".json")
        assert entry["status"] == "awaiting_reference_set"
        assert entry["coverage_at_k"] is None
        assert entry["reference_set_size"] == 0
        assert entry["api_query_count"] == 3
    assert outputs["promotion_gate"]["allowed"] is False
    assert any("no human-confirmed reference set" in r for r in outputs["promotion_gate"]["reasons"])


@pytest.mark.asyncio
async def test_coverage_stays_null_rather_than_zero_without_references(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    comparisons = workflow.step("independent_evaluation").outputs["comparisons"]
    assert comparisons
    for comparison in comparisons:
        assert comparison["coverage_delta"] is None
        assert comparison["reference_status"] == "awaiting_reference_set"


@pytest.mark.asyncio
async def test_confirming_references_opens_coverage_on_re_evaluation(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    spec = temp_db.get_spec(workflow.context["spec_id"])
    for case_id in spec.case_ids:
        case = temp_db.get_benchmark_case(case_id)
        for ref in case.references:
            ref.confirmed_by = "reviewer"
            ref.confirmed_at = "2026-01-02T00:00:00+00:00"
        temp_db.save_benchmark_case(case)
    workflow, _ = await advance(temp_db, workflow, max_steps=1, from_step="independent_evaluation")
    outputs = workflow.step("independent_evaluation").outputs
    scored = [e for e in outputs["evaluations"] if e["split"] != "holdout"]
    assert all(e["status"] == "computed" for e in scored)
    assert all(e["coverage_at_k"] is not None for e in scored)
    assert all(e["reference_set_size"] > 0 for e in scored)


# ------------------------------------------------------------------ evolution
@pytest.mark.asyncio
async def test_failure_diagnosis_reads_the_executed_trials(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    outputs = workflow.step("failure_diagnosis").outputs
    assert outputs["experience_count"] > 0
    assert outputs["diagnosis_count"] > 0
    for diagnosis in outputs["diagnoses"]:
        assert diagnosis["evidence"]
        assert diagnosis["rationale"]
    tallies = outputs["source_tallies"]
    assert any(t["source"] == "arxiv" and t["paper_count"] == 0 for entry in tallies for t in entry["tallies"])


@pytest.mark.asyncio
async def test_skill_mutation_registers_at_most_three_real_candidates(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    outputs = workflow.step("skill_mutation").outputs
    assert outputs["round_id"]
    assert len(outputs["proposals"]) <= 3
    assert temp_db.get_evolution_round(outputs["round_id"]) is not None
    for proposal in outputs["proposals"]:
        version = temp_db.get_skill_version(proposal["version_id"])
        assert version is not None
        assert version.status == "candidate"
        assert proposal["source_trials"]


@pytest.mark.asyncio
async def test_replay_evaluates_each_candidate_under_a_new_frozen_spec(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    outputs = workflow.step("replay_evaluation").outputs
    proposals = workflow.step("skill_mutation").outputs["proposals"]
    if not proposals:
        assert outputs["replay_count"] == 0
        return
    assert outputs["replay_count"] == len(proposals)
    base_spec = temp_db.get_spec(workflow.context["spec_id"])
    for replay in outputs["replays"]:
        spec = temp_db.get_spec(replay["spec_id"])
        assert spec.spec_id != base_spec.spec_id
        assert spec.case_ids == base_spec.case_ids
        assert spec.max_api_requests == base_spec.max_api_requests
        assert spec.baseline_version_id == base_spec.baseline_version_id
        assert spec.candidate_version_id == replay["candidate_version_id"]
        assert replay["runs"]
        assert temp_db.list_experiment_runs(spec_id=spec.spec_id, split="holdout") == []


@pytest.mark.asyncio
async def test_the_workflow_never_opens_holdout(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    spec_ids = [workflow.context["spec_id"], *workflow.context.get("replay_spec_ids", [])]
    for spec_id in spec_ids:
        assert temp_db.list_experiment_runs(spec_id=spec_id, split="holdout") == []
        assert temp_db.get_spec(spec_id).candidate_locked_at is None


# ------------------------------------------------------------------ decision
@pytest.mark.asyncio
async def test_promotion_waits_for_a_human_decision(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    assert workflow.status == "awaiting_human"
    assert workflow.current_step == "promotion_decision"
    assert workflow.step("research_dossier").status == "pending"
    assert workflow.step("promotion_decision").outputs["promotion_gate"]["allowed"] is False


@pytest.mark.asyncio
async def test_a_refused_promotion_is_recorded_and_keeps_the_active_version(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    workflow = record_decision(
        temp_db, workflow, decision="promote", decided_by="reviewer", version_id=None, reason=""
    )
    workflow, _ = await advance(temp_db, workflow, max_steps=18)
    outcome = workflow.step("promotion_decision").outputs
    assert outcome["outcome"] == "refused"
    assert outcome["reasons"]
    assert outcome["active_version_number"] == 1
    assert workflow.status == "completed"
    assert workflow.step("research_dossier").status == "completed"


@pytest.mark.asyncio
async def test_keeping_the_active_version_is_a_valid_recorded_decision(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    workflow = record_decision(
        temp_db, workflow, decision="keep", decided_by="reviewer",
        version_id=None, reason="references are not confirmed yet",
    )
    workflow, _ = await advance(temp_db, workflow, max_steps=18)
    outcome = workflow.step("promotion_decision").outputs
    assert outcome["outcome"] == "kept"
    assert outcome["active_version_number"] == 1


@pytest.mark.asyncio
async def test_rollback_without_a_target_is_rejected(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    workflow = record_decision(
        temp_db, workflow, decision="rollback", decided_by="reviewer", version_id=None, reason=""
    )
    workflow, _ = await advance(temp_db, workflow, max_steps=18)
    step = workflow.step("promotion_decision")
    assert step.status == "failed"
    assert "target version_id" in step.error


# ------------------------------------------------------------------ dossier
@pytest.mark.asyncio
async def test_the_dossier_aggregates_only_stored_records(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    workflow = record_decision(
        temp_db, workflow, decision="keep", decided_by="reviewer", version_id=None, reason=""
    )
    workflow, _ = await advance(temp_db, workflow, max_steps=18)
    dossier = workflow.step("research_dossier").outputs
    assert dossier["acceptance_status"] == "awaiting_reference_set"
    assert dossier["literature"]["paper_count"] == 6
    assert dossier["literature"]["extraction_mode"] == "heuristic"
    assert dossier["literature"]["section_kind_counts"]
    assert dossier["experiment"]["run_count"] == len(
        temp_db.list_experiment_runs(spec_id=workflow.context["spec_id"])
    )
    assert dossier["experiment"]["confirmed_reference_cases"] == 0
    assert dossier["skill"]["active_version_number"] == 1
    assert dossier["hypothesis"] == workflow.context["hypothesis"]
    assert temp_db.get_workflow(workflow.workflow_id).context["dossier"] == dossier


@pytest.mark.asyncio
async def test_the_dossier_reports_acceptance_only_after_a_real_promotion(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    spec = temp_db.get_spec(workflow.context["spec_id"])
    for case_id in spec.case_ids:
        case = temp_db.get_benchmark_case(case_id)
        for ref in case.references:
            ref.confirmed_by = "reviewer"
        temp_db.save_benchmark_case(case)
    workflow = record_decision(
        temp_db, workflow, decision="promote", decided_by="reviewer", version_id=None, reason=""
    )
    workflow, _ = await advance(temp_db, workflow, max_steps=18)
    dossier = workflow.step("research_dossier").outputs
    outcome = workflow.step("promotion_decision").outputs
    if outcome["outcome"] == "promoted":
        assert dossier["acceptance_status"] == "self_evolution_accepted"
    else:
        assert dossier["acceptance_status"] == "evolution_not_accepted"
        assert outcome["reasons"]


# ------------------------------------------------------------------ rewinding
@pytest.mark.asyncio
async def test_rewinding_resets_the_step_and_everything_after_it(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    workflow, _ = await advance(temp_db, workflow, max_steps=1, from_step="failure_diagnosis")
    assert workflow.step("failure_diagnosis").status == "completed"
    assert workflow.step("skill_mutation").status == "pending"
    assert workflow.step("skill_mutation").outputs == {}
    assert workflow.step("independent_evaluation").status == "completed"


@pytest.mark.asyncio
async def test_rewinding_to_the_human_gate_reopens_it_instead_of_reusing_the_approval(
    temp_db, offline
):
    workflow = await _to_decision(temp_db, _start(temp_db))
    assert workflow.context["accepted_gap_id"]
    literature_run_id = workflow.context["literature_run_id"]
    workflow, _ = await advance(temp_db, workflow, max_steps=1, from_step="human_approval")
    assert "accepted_gap_id" not in workflow.context
    assert "spec_id" not in workflow.context
    assert "promotion_outcome" not in workflow.context
    assert workflow.step("human_approval").status == "awaiting_human"
    assert workflow.status == "awaiting_human"
    assert workflow.step("literature_matrix").status == "completed"
    assert workflow.context["literature_run_id"] == literature_run_id
    assert workflow.context["gap_ids"]


@pytest.mark.asyncio
async def test_rewinding_is_refused_once_holdout_was_opened(temp_db, offline):
    workflow = await _to_decision(temp_db, _start(temp_db))
    spec = temp_db.get_spec(workflow.context["spec_id"])
    holdout = next(c for c in temp_db.list_benchmark_cases() if c.case_id in spec.case_ids and c.split == "holdout")
    from app.models.experiment import ExperimentRun

    temp_db.save_experiment_run(
        ExperimentRun(
            run_id="exprun_holdout",
            spec_id=spec.spec_id,
            case_id=holdout.case_id,
            arm="baseline",
            skill_version_id=spec.baseline_version_id,
            skill_snapshot=temp_db.get_skill_version(spec.baseline_version_id).strategy,
        ),
        "holdout",
    )
    with pytest.raises(ValueError, match="one-shot holdout"):
        await advance(temp_db, workflow, max_steps=1, from_step="research_topic")


@pytest.mark.asyncio
async def test_rewinding_to_an_unknown_step_is_refused(temp_db, offline):
    workflow = _start(temp_db)
    with pytest.raises(ValueError, match="unknown step"):
        await advance(temp_db, workflow, max_steps=1, from_step="not_a_step")


# ------------------------------------------------------------------ HTTP layer
@pytest.fixture
def api(temp_db, offline):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_step_catalog_endpoint_lists_all_eighteen(api):
    response = api.get("/api/workflows/steps")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 18
    assert [s["step_id"] for s in payload["steps"]] == list(STEP_SEQUENCE)
    assert [s["step_id"] for s in payload["steps"] if s["requires_human"]] == [
        "human_approval", "promotion_decision"
    ]


def test_start_and_advance_endpoints(api):
    created = api.post("/api/workflows", json={"topic": TOPIC, "top_k": 12})
    assert created.status_code == 200
    workflow_id = created.json()["workflow"]["workflow_id"]
    advanced = api.post(f"/api/workflows/{workflow_id}/advance", json={"max_steps": 3})
    assert advanced.status_code == 200
    assert advanced.json()["executed"] == [
        "research_topic", "search_planning", "literature_discovery"
    ]
    listing = api.get("/api/workflows")
    assert listing.json()["total"] == 1
    detail = api.get(f"/api/workflows/{workflow_id}")
    assert detail.json()["workflow"]["context"]["literature_run_id"]


def test_advance_rejects_an_unbounded_loop(api):
    created = api.post("/api/workflows", json={"topic": TOPIC})
    workflow_id = created.json()["workflow"]["workflow_id"]
    response = api.post(f"/api/workflows/{workflow_id}/advance", json={"max_steps": 99})
    assert response.status_code == 422


def test_dossier_endpoint_is_409_before_the_step_ran(api):
    created = api.post("/api/workflows", json={"topic": TOPIC})
    workflow_id = created.json()["workflow"]["workflow_id"]
    assert api.get(f"/api/workflows/{workflow_id}/dossier").status_code == 409


def test_unknown_workflow_is_404(api):
    assert api.get("/api/workflows/wf_missing").status_code == 404
    assert api.post("/api/workflows/wf_missing/advance", json={}).status_code == 404


def test_approval_endpoint_drives_the_human_gate(api):
    created = api.post("/api/workflows", json={"topic": TOPIC})
    workflow_id = created.json()["workflow"]["workflow_id"]
    api.post(f"/api/workflows/{workflow_id}/advance", json={"max_steps": 18})
    detail = api.get(f"/api/workflows/{workflow_id}").json()["workflow"]
    assert detail["status"] == "awaiting_human"
    gap_id = detail["context"]["gap_ids"][0]
    approved = api.post(
        f"/api/workflows/{workflow_id}/approval",
        json={"gap_id": gap_id, "decision": "accepted", "decided_by": "reviewer"},
    )
    assert approved.status_code == 200
    advanced = api.post(f"/api/workflows/{workflow_id}/advance", json={"max_steps": 18})
    workflow = advanced.json()["workflow"]
    assert workflow["current_step"] == "promotion_decision"
    assert workflow["status"] == "awaiting_human"
    decided = api.post(
        f"/api/workflows/{workflow_id}/decision",
        json={"decision": "keep", "decided_by": "reviewer", "reason": "not confirmed"},
    )
    assert decided.status_code == 200
    finished = api.post(f"/api/workflows/{workflow_id}/advance", json={"max_steps": 18})
    assert finished.json()["workflow"]["status"] == "completed"
    dossier = api.get(f"/api/workflows/{workflow_id}/dossier")
    assert dossier.status_code == 200
    assert dossier.json()["dossier"]["acceptance_status"] == "awaiting_reference_set"