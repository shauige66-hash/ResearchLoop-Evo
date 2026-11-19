"""Offline tests for the evolution engine, promotion gate and rollback.

No network: every trial is a stored ExperimentRun with a real snapshot file on
disk, so the diagnoses are exercised against the same artifacts the live loop
writes. The optional LLM proposer is tested by patching its HTTP call.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.models.evolution import (
    MAX_CANDIDATES_PER_ROUND,
    CandidateProposal,
    EvolutionRound,
    SourceTally,
    TrialExperience,
)
from app.models.experiment import (
    BenchmarkCase,
    BenchmarkReference,
    ExperimentRun,
    ExperimentSpec,
)
from app.models.skill import SKILL_ID, SearchStrategy, SkillVersion, baseline_strategy, plan_queries
from app.services.evolution import (
    CandidateProposer,
    affordable_budget,
    collect_experiences,
    diagnose,
    llm_proposal,
    run_evolution_round,
    salient_terms,
    strategy_diff,
)
from app.services.experiment import effective_years, ensure_seed_skill, order_sources
from app.services.evaluator import evaluate_run
from app.services.promotion import PromotionRefused, promote, rollback


def _version(vid: str, number: int, strategy: SearchStrategy | None = None, **kw) -> SkillVersion:
    return SkillVersion(
        version_id=vid,
        version_number=number,
        strategy=strategy or baseline_strategy(),
        created_at="2026-01-01T00:00:00+00:00",
        **kw,
    )


def _case(cid: str = "case_a", split: str = "development", confirmed: bool = False, **kw) -> BenchmarkCase:
    refs = [
        BenchmarkReference(
            doi="10.1/alpha",
            title="Episodic retrieval for long horizon agents",
            publication_year=2024,
            verified_via="crossref",
            confirmed_by="reviewer" if confirmed else None,
        ),
        BenchmarkReference(
            doi="10.1/beta",
            title="Episodic consolidation in agent memory",
            publication_year=2019,
            verified_via="openalex",
            confirmed_by="reviewer" if confirmed else None,
        ),
    ]
    return BenchmarkCase(
        case_id=cid,
        topic="agent memory consolidation",
        query="LLM agent memory",
        reference_dois=[r.doi for r in refs],
        references=refs,
        split=split,
        **kw,
    )


def _spec(**kw) -> ExperimentSpec:
    base = dict(
        spec_id="spec_1",
        case_ids=["case_a"],
        baseline_version_id="v_base",
        candidate_version_id="v_cand",
        top_k=20,
        max_api_requests=6,
        year_from=2020,
        year_to=2026,
    )
    base.update(kw)
    return ExperimentSpec(**base)


def _exp(**kw) -> TrialExperience:
    base = dict(
        run_id="exprun_1",
        spec_id="spec_1",
        case_id="case_a",
        topic="agent memory consolidation",
        query="LLM agent memory",
        split="development",
        arm="candidate",
        skill_version_id="v_cand",
        queries_used=["LLM agent memory"],
        status="completed",
        reference_status="awaiting_reference_set",
        unique_paper_count=20,
        top_k=20,
        api_request_count=3,
        cache_hits=0,
        retrieved_titles=["A study of LLM agent memory mechanisms"] * 20,
        source_tallies=[
            SourceTally(source="openalex", paper_count=12),
            SourceTally(source="crossref", paper_count=8),
        ],
    )
    base.update(kw)
    return TrialExperience(**base)


def _store_trial(store, spec, case, arm="candidate", **run_kw):
    """Persist a run plus the raw snapshot the diagnosis reads."""
    version_id = spec.baseline_version_id if arm == "baseline" else spec.candidate_version_id
    version = store.get_skill_version(version_id)
    fields = dict(
        run_id=f"exprun_{arm}_{case.case_id}",
        spec_id=spec.spec_id,
        case_id=case.case_id,
        arm=arm,
        skill_version_id=version_id,
        skill_snapshot=version.strategy.model_copy(deep=True),
        queries_used=plan_queries(version.strategy, case.topic, case.query),
        status="completed",
        unique_paper_count=20,
        api_request_count=3,
    )
    fields.update(run_kw)
    run = ExperimentRun(**fields)
    directory = store.db_path.parent / "experiments"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{run.run_id}.json"
    path.write_text(
        json.dumps(
            {
                "response": {
                    "papers": [
                        {"title": "A study of LLM agent memory mechanisms", "source": "openalex"}
                        for _ in range(12)
                    ]
                    + [
                        {"title": "Agent memory consolidation survey", "source": "crossref"}
                        for _ in range(8)
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    run.raw_snapshot_path = str(path)
    run.evaluation = evaluate_run(run, case.confirmed_dois, "fp_test")
    store.save_experiment_run(run, case.split)
    return run


def _setup(store, confirmed=False, split="development"):
    ensure_seed_skill(store)
    base = store.list_skill_versions(skill_id=SKILL_ID, status="active")[0]
    cand = _version("v_cand", 2, parent_version=base.version_id, status="candidate")
    store.save_skill_version(cand)
    case = _case(split=split, confirmed=confirmed)
    store.save_benchmark_case(case)
    spec = _spec(baseline_version_id=base.version_id, case_ids=[case.case_id])
    store.save_spec(spec)
    return spec, case, base, cand


# ------------------------------------------------------------------ frozen surface
def test_source_priority_permutes_but_never_changes_the_source_set():
    frozen = ["openalex", "crossref", "arxiv"]
    ordered = order_sources(["arxiv", "openalex"], frozen)
    assert sorted(ordered) == sorted(frozen)
    assert ordered[0] == "arxiv"
    assert order_sources([], frozen) == frozen


def test_a_strategy_may_narrow_the_year_window_but_never_widen_it():
    spec = _spec(year_from=2020, year_to=2026)
    wider = baseline_strategy()
    wider.search_filters.year_from = 1990
    wider.search_filters.year_to = 2030
    assert effective_years(spec, wider) == (2020, 2026)
    narrower = baseline_strategy()
    narrower.search_filters.year_from = 2023
    assert effective_years(spec, narrower) == (2023, 2026)


def test_a_proposal_cannot_name_a_non_evolvable_component():
    with pytest.raises(ValidationError, match="not an evolvable component"):
        CandidateProposal(
            version_id="v",
            parent_version="p",
            version_number=3,
            mutation_description="try to rewrite the evaluator",
            strategy=baseline_strategy(),
            created_at="now",
            changes=[{"component": "evaluator code and formulas", "before": 1, "after": 2}],
        )


def test_a_round_cannot_exceed_three_candidates():
    proposal = CandidateProposal(
        version_id="v",
        parent_version="p",
        version_number=3,
        mutation_description="a mutation",
        strategy=baseline_strategy(),
        created_at="now",
    )
    with pytest.raises(ValidationError, match="at most 3 candidates"):
        EvolutionRound(
            round_id="r",
            spec_id="s",
            parent_version_id="p",
            proposals=[proposal] * (MAX_CANDIDATES_PER_ROUND + 1),
        )


# ------------------------------------------------------------------------- budget
def test_affordable_budget_uses_the_measured_baseline_cost():
    # 3 baseline requests, 3 sources, 1.5x ceiling -> 4 requests -> still one query.
    assert affordable_budget(3, 3, 6) == (4, 1)
    # A cheaper baseline cannot buy a second query either.
    assert affordable_budget(6, 3, 12) == (9, 3)
    # The spec ceiling always wins over the ratio.
    assert affordable_budget(30, 3, 6) == (6, 2)


def test_a_warm_cache_does_not_buy_extra_queries(temp_db):
    spec, case, base, cand = _setup(temp_db)
    _store_trial(temp_db, spec, case, arm="baseline", api_request_count=0, cache_hits=3)
    _store_trial(temp_db, spec, case)
    experiences = collect_experiences(temp_db, spec)
    proposer = CandidateProposer(cand, spec, experiences, [])
    assert proposer.baseline_requests == 3
    assert proposer.affordable_queries == 1


# ---------------------------------------------------------------------- diagnosis
def test_api_failure_is_not_blamed_on_the_prompt():
    diagnoses = diagnose(
        _exp(source_errors=[{"source": "arxiv", "status": 503, "detail": "unavailable"}])
    )
    kinds = {d.failure_type for d in diagnoses}
    assert "api_failure" in kinds
    failure = next(d for d in diagnoses if d.failure_type == "api_failure")
    assert failure.evidence["sources"] == ["arxiv"]
    assert "transport" in failure.rationale


def test_budget_truncation_is_not_an_api_failure():
    diagnoses = diagnose(
        _exp(source_errors=[{"source": "budget", "status": None, "detail": "truncated"}])
    )
    assert "api_failure" not in {d.failure_type for d in diagnoses}


def test_query_too_narrow_requires_a_short_page():
    assert "query_too_narrow" in {d.failure_type for d in diagnose(_exp(unique_paper_count=4))}
    assert "query_too_narrow" not in {d.failure_type for d in diagnose(_exp(unique_paper_count=20))}


def test_silent_source_is_detected_from_real_tallies():
    diagnoses = diagnose(
        _exp(
            source_priority=["arxiv", "openalex"],
            source_tallies=[
                SourceTally(source="openalex", paper_count=20),
                SourceTally(source="arxiv", paper_count=0),
            ],
        )
    )
    found = next(d for d in diagnoses if d.failure_type == "source_coverage_insufficient")
    assert found.evidence["silent_sources"] == ["arxiv"]
    assert found.evidence["priority_misaligned"] is True
    assert "works against this case" in found.rationale


def test_silent_source_does_not_blame_priority_when_priority_is_already_right():
    diagnoses = diagnose(
        _exp(
            source_priority=["openalex", "arxiv"],
            source_tallies=[
                SourceTally(source="openalex", paper_count=20),
                SourceTally(source="arxiv", paper_count=0),
            ],
        )
    )
    found = next(d for d in diagnoses if d.failure_type == "source_coverage_insufficient")
    assert found.evidence["priority_misaligned"] is False
    assert "cannot recover the missing coverage" in found.rationale


def test_a_source_absent_from_the_snapshot_is_still_counted_as_zero(temp_db):
    """arXiv returning nothing must not disappear from the tallies."""
    spec, case, base, cand = _setup(temp_db)
    _store_trial(temp_db, spec, case)
    experiences = collect_experiences(temp_db, spec)
    tallies = {t.source: t.paper_count for t in experiences[0].source_tallies}
    assert tallies["arxiv"] == 0
    assert tallies["openalex"] == 12
    diagnoses = [d for e in experiences for d in diagnose(e)]
    found = next(d for d in diagnoses if d.failure_type == "source_coverage_insufficient")
    assert found.evidence["silent_sources"] == ["arxiv"]


def test_wrong_terminology_needs_low_overlap_with_retrieved_titles():
    diagnoses = diagnose(
        _exp(
            queries_used=["quantum flux capacitor calibration"],
            retrieved_titles=["Agent memory consolidation for LLM agents"] * 10,
        )
    )
    found = next(d for d in diagnoses if d.failure_type == "wrong_research_terminology")
    assert found.evidence["overlap_ratio"] < 0.34


def test_no_reference_dependent_diagnosis_without_a_confirmed_set():
    diagnoses = diagnose(
        _exp(
            reference_status="awaiting_reference_set",
            missed_references=["10.1/alpha"],
            reference_titles=["Episodic retrieval"],
            reference_years=[1990],
        )
    )
    kinds = {d.failure_type for d in diagnoses}
    assert "missing_synonym" not in kinds
    assert "time_filter_too_restrictive" not in kinds


def test_missing_synonym_names_the_absent_reference_term():
    diagnoses = diagnose(
        _exp(
            reference_status="confirmed",
            missed_references=["10.1/alpha"],
            reference_titles=["Episodic retrieval for long horizon agents"],
        )
    )
    found = next(d for d in diagnoses if d.failure_type == "missing_synonym")
    terms = {t["term"] for t in found.evidence["absent_reference_terms"]}
    assert "episodic" in terms


def test_time_filter_diagnosis_refuses_to_propose_a_frozen_change():
    diagnoses = diagnose(
        _exp(
            reference_status="confirmed",
            reference_years=[2019, 2024],
            effective_year_from=2020,
            effective_year_to=2026,
        )
    )
    found = next(d for d in diagnoses if d.failure_type == "time_filter_too_restrictive")
    assert found.evidence["excluded_reference_years"] == [2019]
    assert found.suggested_component.startswith("none")


def test_a_failed_run_only_reports_transport_failure():
    diagnoses = diagnose(_exp(status="failed", unique_paper_count=0))
    assert {d.failure_type for d in diagnoses} <= {"api_failure"}


# ----------------------------------------------------------------------- proposer
def test_no_proposal_without_an_executed_development_trial(temp_db):
    spec, case, base, cand = _setup(temp_db)
    proposer = CandidateProposer(cand, spec, [], [])
    assert proposer.propose() == []
    assert proposer.skipped[0]["mutation"] == "all"


def test_reference_grounded_mutation_is_refused_without_ground_truth(temp_db):
    spec, case, base, cand = _setup(temp_db, confirmed=False)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    experiences = collect_experiences(temp_db, spec)
    proposer = CandidateProposer(cand, spec, experiences, [])
    proposals = proposer.propose()
    assert proposals, "the topic-coverage mutation is still available"
    assert all("reference" not in p.grounding for p in proposals)
    assert any(
        s["mutation"] == "reference_grounded_reformulation" and "refusing to invent" in s["reason"]
        for s in proposer.skipped
    )


def test_confirmed_references_unlock_the_grounded_mutation(temp_db):
    spec, case, base, cand = _setup(temp_db, confirmed=True)
    _store_trial(temp_db, spec, case, arm="baseline")
    run = _store_trial(temp_db, spec, case)
    experiences = collect_experiences(temp_db, spec)
    diagnoses = [d for e in experiences for d in diagnose(e)]
    proposer = CandidateProposer(cand, spec, experiences, diagnoses)
    proposals = proposer.propose()
    grounded = [p for p in proposals if "reference titles" in p.grounding]
    assert grounded
    assert "episodic" in grounded[0].strategy.query_templates[0]
    assert run.run_id in grounded[0].source_trials
    assert "missing_synonym" in grounded[0].addressed_failures


def test_every_proposal_stays_inside_the_cost_ceiling(temp_db):
    spec, case, base, cand = _setup(temp_db, confirmed=True)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    experiences = collect_experiences(temp_db, spec)
    diagnoses = [d for e in experiences for d in diagnose(e)]
    proposer = CandidateProposer(cand, spec, experiences, diagnoses)
    for proposal in proposer.propose():
        assert proposal.projected_request_ratio is not None
        assert proposal.projected_request_ratio <= 1.5
        assert proposal.projected_api_requests <= spec.max_api_requests
        assert proposal.strategy.retrieval_budget.max_api_requests == spec.max_api_requests
        assert proposal.strategy.retrieval_budget.top_k == spec.top_k


def test_validation_and_holdout_material_never_reaches_a_mutation(temp_db):
    spec, case, base, cand = _setup(temp_db, confirmed=True)
    holdout = _case(cid="case_h", split="holdout", confirmed=True)
    temp_db.save_benchmark_case(holdout)
    spec = spec.model_copy(update={"case_ids": [case.case_id, holdout.case_id]})
    temp_db.save_spec(spec)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    holdout_run = _store_trial(temp_db, spec, holdout)
    experiences = collect_experiences(temp_db, spec)
    assert any(e.split == "holdout" for e in experiences), "holdout trials are still recorded"
    holdout_exp = next(e for e in experiences if e.split == "holdout")
    assert holdout_exp.reference_titles == [], "holdout ground truth must not be exposed"
    proposer = CandidateProposer(cand, spec, experiences, [])
    assert all(holdout_run.run_id not in p.source_trials for p in proposer.propose())


def test_source_priority_mutation_is_grounded_in_measured_tallies(temp_db):
    spec, case, base, cand = _setup(temp_db)
    wrong_order = baseline_strategy()
    wrong_order.source_priority = ["arxiv", "crossref", "openalex"]
    cand = cand.model_copy(update={"strategy": wrong_order})
    temp_db.conn.execute(
        "UPDATE skill_versions SET json=? WHERE version_id=?",
        (cand.model_dump_json(), cand.version_id),
    )
    temp_db.conn.commit()
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    experiences = collect_experiences(temp_db, spec)
    proposer = CandidateProposer(cand, spec, experiences, [])
    reorder = [p for p in proposer.propose() if "source priority" in p.mutation_description.lower()]
    assert reorder
    assert reorder[0].strategy.source_priority[0] == "openalex"
    assert sorted(reorder[0].strategy.source_priority) == ["arxiv", "crossref", "openalex"]
    assert reorder[0].projected_request_ratio == 1.0


def test_a_no_op_source_reorder_is_not_proposed(temp_db):
    spec, case, base, cand = _setup(temp_db)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    experiences = collect_experiences(temp_db, spec)
    proposer = CandidateProposer(cand, spec, experiences, [])
    reorder = [p for p in proposer.propose() if "source priority" in p.mutation_description.lower()]
    assert reorder == []
    assert any(
        s["mutation"] == "source_priority_reorder" and "no-op" in s["reason"]
        for s in proposer.skipped
    )


def test_strategy_diff_reports_only_real_changes():
    parent = baseline_strategy()
    child = parent.model_copy(deep=True)
    assert strategy_diff(parent, child) == []
    child.query_templates = ["{query} episodic"]
    diff = strategy_diff(parent, child)
    assert [c.component for c in diff] == ["query_templates"]


def test_salient_terms_drop_filler_words():
    terms = salient_terms("We propose a novel approach using episodic consolidation")
    assert "episodic" in terms and "consolidation" in terms
    assert "novel" not in terms and "using" not in terms


# -------------------------------------------------------------------- round trip
@pytest.mark.asyncio
async def test_round_persists_candidates_without_activating_them(temp_db):
    spec, case, base, cand = _setup(temp_db, confirmed=True)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    record = await run_evolution_round(temp_db, spec)
    assert record.proposer_mode == "deterministic"
    assert record.llm_skip_reason
    assert 1 <= len(record.proposals) <= MAX_CANDIDATES_PER_ROUND
    for proposal in record.proposals:
        stored = temp_db.get_skill_version(proposal.version_id)
        assert stored.status == "candidate"
        assert stored.created_by == "proposer"
        assert stored.parent_version == cand.version_id
        assert stored.version_number == proposal.version_number
    assert temp_db.list_skill_versions(skill_id=SKILL_ID, status="active")[0].version_id == base.version_id
    assert temp_db.get_evolution_round(record.round_id).round_id == record.round_id
    assert temp_db.list_evolution_rounds(spec.spec_id)[0].round_id == record.round_id


@pytest.mark.asyncio
async def test_round_is_refused_without_trials_but_records_why(temp_db):
    spec, case, base, cand = _setup(temp_db)
    record = await run_evolution_round(temp_db, spec)
    assert record.proposals == []
    assert record.skipped_mutations[0]["mutation"] == "all"
    assert record.diagnoses == []


@pytest.mark.asyncio
async def test_candidate_cap_is_respected(temp_db):
    spec, case, base, cand = _setup(temp_db, confirmed=True)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    record = await run_evolution_round(temp_db, spec, max_candidates=1)
    assert len(record.proposals) == 1


@pytest.mark.asyncio
async def test_llm_mode_falls_back_honestly_without_a_provider(temp_db, monkeypatch):
    spec, case, base, cand = _setup(temp_db, confirmed=True)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    record = await run_evolution_round(temp_db, spec, use_llm=True)
    assert record.proposer_mode == "deterministic"
    assert "RLE_LLM_API_KEY" in record.llm_skip_reason
    assert not [e for e in temp_db.list_skill_events() if e["event"] == "llm_call"]


@pytest.mark.asyncio
async def test_llm_reply_is_validated_and_budget_clamped(temp_db, monkeypatch):
    import app.services.evolution as evolution_module
    import app.services.llm as llm_module

    spec, case, base, cand = _setup(temp_db, confirmed=True)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    experiences = collect_experiences(temp_db, spec)
    proposer = CandidateProposer(cand, spec, experiences, [])

    settings = evolution_module.get_settings()
    monkeypatch.setattr(settings, "llm_enabled", True, raising=False)
    monkeypatch.setattr(settings, "llm_api_key", "test-key", raising=False)
    monkeypatch.setattr(settings, "llm_base_url", "https://example.invalid/v1", raising=False)
    monkeypatch.setattr(settings, "llm_model", "test-model", raising=False)

    oversized = baseline_strategy()
    oversized.query_templates = ["{query} episodic", "{query} consolidation", "{topic}"]
    oversized.retrieval_budget.max_keywords = 6
    oversized.retrieval_budget.max_api_requests = 60
    payload = {
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        {
                            "strategy": oversized.model_dump(),
                            "mutation_description": "LLM suggests episodic reformulation",
                        }
                    )
                }
            }
        ]
    }

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return _Response()

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _Client)
    proposal, reason = await llm_proposal(temp_db, proposer)
    assert reason == ""
    assert proposal is not None
    assert proposal.strategy.retrieval_budget.max_keywords == proposer.affordable_queries
    assert proposal.strategy.retrieval_budget.max_api_requests == spec.max_api_requests
    assert proposal.projected_request_ratio <= 1.5
    assert [e for e in temp_db.list_skill_events() if e["event"] == "llm_call"]


@pytest.mark.asyncio
async def test_llm_quota_is_enforced(temp_db, monkeypatch):
    import app.services.evolution as evolution_module

    spec, case, base, cand = _setup(temp_db, confirmed=True)
    _store_trial(temp_db, spec, case, arm="baseline")
    experiences = collect_experiences(temp_db, spec)
    proposer = CandidateProposer(cand, spec, experiences, [])
    settings = evolution_module.get_settings()
    for name, value in (
        ("llm_enabled", True),
        ("llm_api_key", "k"),
        ("llm_base_url", "https://example.invalid/v1"),
        ("llm_model", "m"),
        ("llm_max_calls", 1),
    ):
        monkeypatch.setattr(settings, name, value, raising=False)
    temp_db.add_skill_event(cand.version_id, "llm_call", {})
    proposal, reason = await llm_proposal(temp_db, proposer)
    assert proposal is None
    assert "quota exhausted" in reason


@pytest.mark.asyncio
async def test_a_malformed_llm_reply_creates_no_candidate(temp_db, monkeypatch):
    import app.services.evolution as evolution_module
    import app.services.llm as llm_module

    spec, case, base, cand = _setup(temp_db, confirmed=True)
    _store_trial(temp_db, spec, case, arm="baseline")
    experiences = collect_experiences(temp_db, spec)
    proposer = CandidateProposer(cand, spec, experiences, [])
    settings = evolution_module.get_settings()
    for name, value in (
        ("llm_enabled", True),
        ("llm_api_key", "k"),
        ("llm_base_url", "https://example.invalid/v1"),
        ("llm_model", "m"),
    ):
        monkeypatch.setattr(settings, name, value, raising=False)

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            raise RuntimeError("provider unreachable")

    monkeypatch.setattr(llm_module.httpx, "AsyncClient", _Client)
    proposal, reason = await llm_proposal(temp_db, proposer)
    assert proposal is None
    assert "provider unreachable" in reason
    assert temp_db.list_skill_versions(skill_id=SKILL_ID, status="candidate")[0].version_id == cand.version_id


# --------------------------------------------------------------- promotion / rollback
def test_promotion_is_refused_without_a_confirmed_reference_set(temp_db):
    spec, case, base, cand = _setup(temp_db, confirmed=False)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    with pytest.raises(PromotionRefused) as exc:
        promote(temp_db, spec.spec_id, cand.version_id, "reviewer")
    assert any("human-confirmed reference set" in r for r in exc.value.reasons)
    assert temp_db.get_skill_version(cand.version_id).status == "candidate"
    assert temp_db.list_skill_versions(skill_id=SKILL_ID, status="active")[0].version_id == base.version_id


def test_promotion_refuses_a_version_that_is_not_the_spec_candidate(temp_db):
    spec, case, base, cand = _setup(temp_db)
    other = _version("v_other", 3, status="candidate")
    temp_db.save_skill_version(other)
    with pytest.raises(ValueError, match="only the candidate version of this spec"):
        promote(temp_db, spec.spec_id, other.version_id, "reviewer")


def test_rollback_requires_a_version_that_was_active_before(temp_db):
    spec, case, base, cand = _setup(temp_db)
    with pytest.raises(ValueError, match="never activated"):
        rollback(temp_db, cand.version_id, "reviewer", "regression suspected")


def test_rollback_restores_the_seed_and_records_the_decision(temp_db):
    spec, case, base, cand = _setup(temp_db)
    temp_db.set_skill_status(base.version_id, "archived")
    temp_db.set_skill_status(cand.version_id, "active")
    temp_db.add_skill_event(cand.version_id, "promoted", {"spec_id": spec.spec_id})
    restored = rollback(temp_db, base.version_id, "reviewer", "coverage regressed on validation")
    assert restored.version_id == base.version_id
    assert restored.status == "active"
    assert temp_db.get_skill_version(cand.version_id).status == "archived"
    events = temp_db.list_skill_events(base.version_id)
    entry = next(e for e in events if e["event"] == "rolled_back")
    assert entry["detail"]["decided_by"] == "reviewer"
    assert "coverage regressed" in entry["detail"]["reason"]
    assert "claims no improvement" in entry["detail"]["note"]


def test_rollback_refuses_the_already_active_version(temp_db):
    spec, case, base, cand = _setup(temp_db)
    with pytest.raises(ValueError, match="already active"):
        rollback(temp_db, base.version_id, "reviewer", "")


def test_versions_are_never_overwritten(temp_db):
    spec, case, base, cand = _setup(temp_db)
    duplicate = _version(cand.version_id, 99)
    with pytest.raises(ValueError):
        temp_db.save_skill_version(duplicate)
    assert temp_db.get_skill_version(cand.version_id).version_number == 2


# ---------------------------------------------------------------------- HTTP layer
@pytest.fixture
def api(temp_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_evolve_endpoint_registers_candidates(api, temp_db):
    spec, case, base, cand = _setup(temp_db, confirmed=True)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    response = api.post("/api/evolve/skills", json={"spec_id": spec.spec_id})
    assert response.status_code == 200
    body = response.json()
    assert body["proposer_mode"] == "deterministic"
    assert 1 <= len(body["proposals"]) <= 3
    assert body["notice"].startswith("Candidates are proposals")
    listing = api.get("/api/evolve/rounds", params={"spec_id": spec.spec_id}).json()
    assert listing["total"] == 1
    detail = api.get(f"/api/evolve/rounds/{body['round_id']}").json()
    assert detail["round"]["round_id"] == body["round_id"]


def test_evolve_endpoint_rejects_an_unknown_spec(api, temp_db):
    assert api.post("/api/evolve/skills", json={"spec_id": "nope"}).status_code == 404


def test_evolve_endpoint_caps_candidates_at_three(api, temp_db):
    response = api.post("/api/evolve/skills", json={"spec_id": "s", "max_candidates": 4})
    assert response.status_code == 422


def test_promote_endpoint_returns_409_with_the_real_reasons(api, temp_db):
    spec, case, base, cand = _setup(temp_db, confirmed=False)
    _store_trial(temp_db, spec, case, arm="baseline")
    _store_trial(temp_db, spec, case)
    response = api.post(
        "/api/skills/promote",
        json={"spec_id": spec.spec_id, "version_id": cand.version_id, "decided_by": "reviewer"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["message"] == "promotion refused by the independent gate"
    assert any("human-confirmed reference set" in r for r in detail["reasons"])
    assert api.get("/api/skills/active").json()["version"]["version_id"] == base.version_id


def test_promote_endpoint_requires_a_decider(api, temp_db):
    response = api.post("/api/skills/promote", json={"spec_id": "s", "version_id": "v"})
    assert response.status_code == 422


def test_rollback_endpoint_restores_a_previous_active_version(api, temp_db):
    spec, case, base, cand = _setup(temp_db)
    temp_db.set_skill_status(base.version_id, "archived")
    temp_db.set_skill_status(cand.version_id, "active")
    temp_db.add_skill_event(cand.version_id, "promoted", {})
    response = api.post(
        "/api/skills/rollback",
        json={"version_id": base.version_id, "decided_by": "reviewer", "reason": "regression"},
    )
    assert response.status_code == 200
    assert response.json()["version"]["version_id"] == base.version_id
    assert api.get("/api/skills/active").json()["version"]["version_id"] == base.version_id
    history = api.get("/api/skills/history").json()
    assert any(e["event"] == "rolled_back" for e in history["events"])


def test_rollback_endpoint_refuses_a_never_active_version(api, temp_db):
    spec, case, base, cand = _setup(temp_db)
    response = api.post(
        "/api/skills/rollback",
        json={"version_id": cand.version_id, "decided_by": "reviewer"},
    )
    assert response.status_code == 400
    assert "never activated" in response.json()["detail"]


def test_failure_types_endpoint_lists_all_six(api, temp_db):
    body = api.get("/api/evolve/failure-types").json()
    assert len(body["failure_types"]) == 6
    assert body["max_candidates_per_round"] == 3


def test_llm_credentials_never_appear_in_an_api_response(api, temp_db, monkeypatch):
    import app.config as config_module

    monkeypatch.setenv("RLE_LLM_API_KEY", "super-secret-key")
    config_module.get_settings.cache_clear()
    try:
        for path in ("/api/skills/versions", "/api/skills/active", "/api/evolve/failure-types"):
            assert "super-secret-key" not in api.get(path).text
    finally:
        monkeypatch.delenv("RLE_LLM_API_KEY", raising=False)
        config_module.get_settings.cache_clear()