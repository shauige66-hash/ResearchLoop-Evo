"""Offline tests for the minimal experiment lab.

No network: retrieval is patched at its use site and DOI verification is patched
in the benchmark service, so these tests assert how real records are handled
without calling any external API.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.experiment import (
    BenchmarkCase,
    BenchmarkReference,
    EvaluationReport,
    ExperimentRun,
    ExperimentSpec,
)
from app.models.paper import Paper
from app.models.schemas import SearchResponse
from app.models.skill import (
    RetrievalBudget,
    SearchStrategy,
    SkillVersion,
    baseline_strategy,
    plan_queries,
)
from app.services import benchmark as benchmark_module
from app.services import experiment as experiment_module
from app.services.evaluator import (
    coverage_delta,
    dataset_fingerprint,
    evaluate,
    normalize_doi,
    promotion_blockers,
    reference_fingerprint,
    request_ratio,
)
from app.services.http import HttpFailure

client = TestClient(app)


# --------------------------------------------------------------------- factories
def _paper(pid: str, doi: str) -> Paper:
    return Paper(
        paper_id=pid,
        title=f"Agent memory paper {pid}",
        source="openalex",
        source_url=f"https://openalex.org/{pid}",
        doi=doi,
        abstract="We study memory for LLM agents.",
        publication_year=2025,
    )


def _ref(doi: str, confirmed: bool = True) -> BenchmarkReference:
    return BenchmarkReference(
        doi=doi,
        title=f"Real work {doi}",
        source_url=f"https://doi.org/{doi}",
        verified_via="crossref",
        verified_at="2026-01-01T00:00:00+00:00",
        confirmed_by="human" if confirmed else None,
        confirmed_at="2026-01-01T00:00:00+00:00" if confirmed else None,
    )


def _case(case_id: str, topic: str, split: str, dois: list[str], confirmed: bool = True) -> BenchmarkCase:
    return BenchmarkCase(
        case_id=case_id,
        topic=topic,
        query=f"{topic} retrieval",
        reference_dois=dois,
        split=split,
        references=[_ref(d, confirmed) for d in dois],
        created_at="2026-01-01T00:00:00+00:00",
    )


def _spec(case_ids: list[str], **overrides) -> ExperimentSpec:
    base = dict(
        spec_id="spec_test",
        case_ids=case_ids,
        baseline_version_id="skillv_base",
        candidate_version_id="skillv_cand",
        created_at="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return ExperimentSpec(**base)


def _arm(
    case: BenchmarkCase,
    arm: str,
    *,
    retrieved: list[str],
    requests: int,
    spec_cases: list[BenchmarkCase],
    errors: list[dict] | None = None,
) -> ExperimentRun:
    run = ExperimentRun(
        run_id=f"exprun_{case.case_id}_{arm}",
        spec_id="spec_test",
        case_id=case.case_id,
        arm=arm,
        skill_version_id="skillv_base" if arm == "baseline" else "skillv_cand",
        skill_snapshot=baseline_strategy(),
        queries_used=[case.query],
        status="completed",
        api_request_count=requests,
        unique_paper_count=len(retrieved),
        execution_time_ms=1200,
        retrieved_dois=retrieved,
        source_errors=errors or [],
    )
    run.evaluation = evaluate(
        retrieved_dois=retrieved,
        confirmed_dois=case.confirmed_dois,
        api_query_count=requests,
        unique_paper_count=len(retrieved),
        execution_time_ms=1200,
        dataset_fp=dataset_fingerprint(
            [
                {"case_id": c.case_id, "topic": c.topic, "query": c.query, "split": c.split}
                for c in spec_cases
            ]
        ),
    )
    return run


def _response(papers: list[Paper], requests: int = 3) -> SearchResponse:
    return SearchResponse(
        run_id="run_lit",
        project_id="proj_lit",
        topic="agent memory",
        meta={"requests_made": requests, "cache_hits": 0, "duration_ms": 900},
        papers=papers,
        source_errors=[],
        stats={},
    )


# ------------------------------------------------------------ skill query planning
def test_baseline_sends_exactly_the_original_question():
    assert plan_queries(baseline_strategy(), "agent memory", "agent memory survey") == [
        "agent memory survey"
    ]


def test_expansion_is_capped_by_the_strategy_budget():
    strategy = SearchStrategy(
        query_templates=["{query}"],
        keyword_expansion_rules=["topic_terms"],
        retrieval_budget=RetrievalBudget(max_keywords=3),
    )
    queries = plan_queries(strategy, "agent memory evolution for long horizon tasks", "agent memory")
    assert len(queries) == 3
    assert queries[0] == "agent memory"


def test_domain_synonyms_only_fire_when_the_term_is_present():
    strategy = SearchStrategy(
        query_templates=["{query}"],
        domain_synonyms={"memory": ["episodic recall", "long-term store"]},
        keyword_expansion_rules=["domain_synonyms"],
        retrieval_budget=RetrievalBudget(max_keywords=6),
    )
    hit = plan_queries(strategy, "agent memory", "agent memory")
    miss = plan_queries(strategy, "agent planning", "agent planning")
    assert "agent memory episodic recall" in hit
    assert miss == ["agent planning"]


def test_a_synonym_already_in_the_query_is_not_appended():
    strategy = SearchStrategy(
        query_templates=["{query}"],
        domain_synonyms={"skill": ["skill library", "procedural knowledge"]},
        keyword_expansion_rules=["domain_synonyms"],
        retrieval_budget=RetrievalBudget(max_keywords=6),
    )
    queries = plan_queries(strategy, "agent skill learning", "LLM agent skill library learning")
    assert queries == [
        "LLM agent skill library learning",
        "LLM agent skill library learning procedural knowledge",
    ]


def test_query_planning_is_deterministic_and_deduplicated():
    strategy = SearchStrategy(
        query_templates=["{query}", "{query}"],
        keyword_expansion_rules=["topic_terms", "query_terms"],
        retrieval_budget=RetrievalBudget(max_keywords=6),
    )
    first = plan_queries(strategy, "agent memory", "agent memory")
    second = plan_queries(strategy, "agent memory", "agent memory")
    assert first == second
    assert len(first) == len({q.lower() for q in first})


def test_strategy_rejects_unrenderable_templates():
    with pytest.raises(ValidationError):
        SearchStrategy(query_templates=["{query} {doi}"])
    with pytest.raises(ValidationError):
        SearchStrategy(query_templates=[])


def test_a_strategy_cannot_reach_the_evaluator_or_the_reference_set():
    """The evolvable surface is exactly the six strategy components."""
    assert set(SearchStrategy.model_fields) == {
        "query_templates",
        "domain_synonyms",
        "keyword_expansion_rules",
        "source_priority",
        "search_filters",
        "retrieval_budget",
    }


# ------------------------------------------------------------------- the evaluator
def test_without_confirmed_references_no_coverage_is_reported():
    report = evaluate(
        retrieved_dois=["10.1/a", "10.1/b"],
        confirmed_dois=[],
        api_query_count=3,
        unique_paper_count=2,
        execution_time_ms=800,
        dataset_fp="fp",
    )
    assert report.status == "awaiting_reference_set"
    assert report.coverage_at_k is None
    assert report.hit_references == [] and report.missed_references == []
    # Cost metrics are still real.
    assert report.api_query_count == 3
    assert report.unique_paper_count == 2
    assert report.execution_time_ms == 800
    assert "No human-confirmed reference DOIs" in report.notice


def test_unconfirmed_references_are_not_ground_truth():
    report = evaluate(
        retrieved_dois=["10.1/a"],
        confirmed_dois=[],
        api_query_count=1,
        unique_paper_count=1,
        execution_time_ms=10,
        dataset_fp="fp",
    )
    assert report.reference_set_size == 0
    assert report.reference_fingerprint == ""


def test_coverage_is_hits_over_the_confirmed_set():
    report = evaluate(
        retrieved_dois=["10.1/a", "10.1/c", "10.1/extra"],
        confirmed_dois=["10.1/a", "10.1/b", "10.1/c", "10.1/d"],
        api_query_count=3,
        unique_paper_count=3,
        execution_time_ms=500,
        dataset_fp="fp",
    )
    assert report.status == "computed"
    assert report.coverage_at_k == 0.5
    assert report.hit_references == ["10.1/a", "10.1/c"]
    assert report.missed_references == ["10.1/b", "10.1/d"]
    assert report.reference_set_size == 4
    assert "not the absolute recall" in report.notice


def test_doi_url_forms_match_the_bare_doi():
    assert normalize_doi("https://doi.org/10.1/A") == "10.1/a"
    assert normalize_doi("doi:10.1/a") == "10.1/a"
    report = evaluate(
        retrieved_dois=["https://doi.org/10.1/A"],
        confirmed_dois=["10.1/a"],
        api_query_count=1,
        unique_paper_count=1,
        execution_time_ms=1,
        dataset_fp="fp",
    )
    assert report.coverage_at_k == 1.0


def test_report_model_refuses_coverage_without_references():
    with pytest.raises(ValidationError):
        EvaluationReport(status="awaiting_reference_set", coverage_at_k=0.9)
    with pytest.raises(ValidationError):
        EvaluationReport(status="computed", coverage_at_k=0.9, reference_set_size=0)


def test_reference_fingerprint_ignores_order_and_duplicates():
    assert reference_fingerprint(["10.1/b", "10.1/a", "10.1/a"]) == reference_fingerprint(
        ["10.1/a", "10.1/b"]
    )
    assert reference_fingerprint(["10.1/a"]) != reference_fingerprint(["10.1/a", "10.1/b"])


def test_dataset_fingerprint_tracks_splits_but_not_references():
    cases = [{"case_id": "c1", "topic": "t", "query": "q", "split": "development"}]
    base = dataset_fingerprint(cases)
    assert base == dataset_fingerprint(list(reversed(cases)))
    moved = [{**cases[0], "split": "validation"}]
    assert dataset_fingerprint(moved) != base


def test_delta_and_ratio_are_none_without_a_reference_set():
    case = _case("c1", "agent memory", "validation", ["10.1/a"], confirmed=False)
    baseline = _arm(case, "baseline", retrieved=["10.1/a"], requests=3, spec_cases=[case])
    candidate = _arm(case, "candidate", retrieved=["10.1/a"], requests=6, spec_cases=[case])
    assert coverage_delta(baseline, candidate) is None
    assert request_ratio(baseline, candidate) == 2.0


def test_a_warm_cache_cannot_hide_extra_retrieval_cost():
    case = _case("c1", "agent memory", "validation", ["10.1/a"])
    baseline = _arm(case, "baseline", retrieved=["10.1/a"], requests=3, spec_cases=[case])
    candidate = _arm(case, "candidate", retrieved=["10.1/a"], requests=3, spec_cases=[case])
    candidate.cache_hits = 3  # second query served entirely from cache
    assert candidate.api_request_count == baseline.api_request_count
    assert candidate.total_api_queries == 6
    assert request_ratio(baseline, candidate) == 2.0
    spec = _spec(["c1"], max_api_requests=6, candidate_locked_at="now")
    reasons = promotion_blockers(spec=spec, cases=[case], runs=[baseline, candidate])
    assert any("1.5x" in r or "2.00x" in r for r in reasons)


# ------------------------------------------------------------- promotion gate rules
def _two_split_setup(**candidate_kwargs):
    validation = _case("cv", "agent memory", "validation", ["10.1/a", "10.1/b"])
    holdout = _case("ch", "agent skill learning", "holdout", ["10.2/a"])
    cases = [validation, holdout]
    spec = _spec([c.case_id for c in cases], candidate_locked_at="2026-01-02T00:00:00+00:00")
    runs = [
        _arm(validation, "baseline", retrieved=["10.1/a"], requests=3, spec_cases=cases),
        _arm(validation, "candidate", retrieved=["10.1/a", "10.1/b"], requests=4, spec_cases=cases),
        _arm(holdout, "baseline", retrieved=["10.2/a"], requests=3, spec_cases=cases),
        _arm(holdout, "candidate", retrieved=["10.2/a"], requests=4, spec_cases=cases),
    ]
    if candidate_kwargs:
        runs[1] = _arm(
            validation, "candidate", spec_cases=cases,
            retrieved=candidate_kwargs.get("retrieved", ["10.1/a", "10.1/b"]),
            requests=candidate_kwargs.get("requests", 4),
            errors=candidate_kwargs.get("errors"),
        )
    return spec, cases, runs


def test_promotion_allowed_when_every_rule_holds():
    spec, cases, runs = _two_split_setup()
    assert promotion_blockers(spec=spec, cases=cases, runs=runs) == []


def test_promotion_blocked_without_a_confirmed_reference_set():
    validation = _case("cv", "agent memory", "validation", ["10.1/a"], confirmed=False)
    holdout = _case("ch", "agent skill", "holdout", ["10.2/a"])
    cases = [validation, holdout]
    spec = _spec([c.case_id for c in cases], candidate_locked_at="now")
    runs = [
        _arm(c, arm, retrieved=[], requests=3, spec_cases=cases)
        for c in cases
        for arm in ("baseline", "candidate")
    ]
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    assert any("no human-confirmed reference set" in r for r in reasons)


def test_promotion_blocked_when_validation_coverage_does_not_improve():
    spec, cases, runs = _two_split_setup(retrieved=["10.1/a"])
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    assert any("validation coverage did not improve" in r for r in reasons)


def test_promotion_blocked_when_holdout_regresses():
    validation = _case("cv", "agent memory", "validation", ["10.1/a", "10.1/b"])
    holdout = _case("ch", "agent skill", "holdout", ["10.2/a", "10.2/b"])
    cases = [validation, holdout]
    spec = _spec([c.case_id for c in cases], candidate_locked_at="now")
    runs = [
        _arm(validation, "baseline", retrieved=["10.1/a"], requests=3, spec_cases=cases),
        _arm(validation, "candidate", retrieved=["10.1/a", "10.1/b"], requests=3, spec_cases=cases),
        _arm(holdout, "baseline", retrieved=["10.2/a", "10.2/b"], requests=3, spec_cases=cases),
        _arm(holdout, "candidate", retrieved=["10.2/a"], requests=3, spec_cases=cases),
    ]
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    assert any("holdout coverage regressed" in r for r in reasons)


def test_promotion_blocked_above_the_request_ratio_limit():
    spec, cases, runs = _two_split_setup(requests=5)  # 5 / 3 > 1.5
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    assert any("1.67x the baseline API requests" in r for r in reasons)


def test_promotion_blocked_on_unhandled_api_errors():
    spec, cases, runs = _two_split_setup(
        errors=[{"source": "crossref", "status": 500, "detail": "boom"}]
    )
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    assert any("unhandled API errors" in r for r in reasons)


def test_rate_limit_errors_are_not_unhandled_failures():
    spec, cases, runs = _two_split_setup(
        errors=[{"source": "arxiv", "status": 429, "detail": "slow down"}]
    )
    assert promotion_blockers(spec=spec, cases=cases, runs=runs) == []


def test_promotion_blocked_when_fingerprints_diverge():
    spec, cases, runs = _two_split_setup()
    runs[1].evaluation.reference_fingerprint = "tampered"
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    assert any("reference-set fingerprint differs" in r for r in reasons)


def test_promotion_blocked_before_the_holdout_check_runs():
    spec, cases, runs = _two_split_setup()
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs[:2])
    assert any("final holdout check has not been executed" in r for r in reasons)


def test_promotion_blocked_when_the_candidate_was_never_locked():
    spec, cases, runs = _two_split_setup()
    spec.candidate_locked_at = None
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    assert any("never locked" in r for r in reasons)


# ----------------------------------------------------------------- benchmark splits
def test_splits_never_separate_cases_of_the_same_topic():
    cases = [
        _case(f"c{i}", topic, "development", [])
        for i, topic in enumerate(["agent memory", "agent memory", "skill learning", "tool use", "planning"])
    ]
    benchmark_module.assign_splits(cases)
    by_topic: dict[str, set[str]] = {}
    for case in cases:
        by_topic.setdefault(case.topic, set()).add(case.split)
    assert all(len(splits) == 1 for splits in by_topic.values())


def test_split_assignment_is_deterministic():
    cases = [_case(f"c{i}", t, "development", []) for i, t in enumerate(["a topic", "b topic", "c topic"])]
    first = [c.split for c in benchmark_module.assign_splits(cases)]
    second = [c.split for c in benchmark_module.assign_splits(cases)]
    assert first == second


def test_three_or_more_topics_fill_all_three_buckets():
    cases = [
        _case(f"c{i}", f"topic number {i}", "development", [])
        for i in range(7)
    ]
    benchmark_module.assign_splits(cases)
    counts = {s: sum(1 for c in cases if c.split == s) for s in ("development", "validation", "holdout")}
    assert all(counts.values()), counts
    assert counts["development"] >= counts["holdout"]


def test_too_few_topics_are_not_pretended_into_three_buckets():
    cases = [_case(f"c{i}", f"topic {i}", "development", []) for i in range(2)]
    benchmark_module.assign_splits(cases)
    assert {c.split for c in cases} == {"development"}


def test_api_assign_splits_returns_the_listing(temp_db):
    """Regression: the endpoint must not leak FastAPI Query defaults into SQLite."""
    for i in range(3):
        temp_db.save_benchmark_case(_case(f"c{i}", f"topic {i}", "development", []))
    response = client.post("/api/experiments/benchmark/assign-splits")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert set(body["split_counts"]) == {"development", "validation", "holdout"}


@pytest.mark.asyncio
async def test_doi_verification_reports_both_real_failures(monkeypatch):
    class FailingClient:
        async def fetch_json(self, *args, **kwargs):
            raise HttpFailure(status=404, detail="Resource not found", source="crossref")

    monkeypatch.setattr(benchmark_module, "get_client", lambda: FailingClient())
    with pytest.raises(HttpFailure) as exc:
        await benchmark_module.verify_doi("10.9999/does-not-exist")
    assert "crossref: 404" in exc.value.detail
    assert "openalex: 404" in exc.value.detail


@pytest.mark.asyncio
async def test_doi_verification_falls_back_to_openalex(monkeypatch):
    class Outcome:
        payload = {"title": "A Real Paper", "id": "https://openalex.org/W1"}

    class Client:
        async def fetch_json(self, url, **kwargs):
            if "crossref" in url:
                raise HttpFailure(status=404, detail="not found", source="crossref")
            return Outcome()

    monkeypatch.setattr(benchmark_module, "get_client", lambda: Client())
    ref = await benchmark_module.verify_doi("https://doi.org/10.1/REAL")
    assert ref.doi == "10.1/real"
    assert ref.verified_via == "openalex"
    assert ref.title == "A Real Paper"
    assert not ref.is_confirmed  # metadata verification is not human confirmation


# ------------------------------------------------------------------ store contracts
def test_skill_versions_are_immutable(temp_db):
    version = SkillVersion(
        version_id="skillv_x",
        version_number=1,
        strategy=baseline_strategy(),
        created_at="2026-01-01T00:00:00+00:00",
    )
    temp_db.save_skill_version(version)
    with pytest.raises(ValueError, match="immutable"):
        temp_db.save_skill_version(version)
    assert temp_db.next_version_number("literature_search_strategy") == 2


def test_experiment_runs_roundtrip_with_split_filter(temp_db):
    case = _case("c1", "agent memory", "validation", ["10.1/a"])
    temp_db.save_benchmark_case(case)
    run = _arm(case, "baseline", retrieved=["10.1/a"], requests=3, spec_cases=[case])
    temp_db.save_experiment_run(run, case.split)
    loaded = temp_db.get_experiment_run(run.run_id)
    assert loaded is not None
    assert loaded.evaluation.coverage_at_k == 1.0
    assert loaded.skill_snapshot.query_templates == ["{query}"]
    assert temp_db.list_experiment_runs(split="validation")
    assert temp_db.list_experiment_runs(split="holdout") == []


def test_benchmark_reference_status_is_derived_from_confirmation(temp_db):
    case = _case("c1", "agent memory", "development", ["10.1/a"], confirmed=False)
    temp_db.save_benchmark_case(case)
    assert temp_db.list_benchmark_cases(reference_status="awaiting_reference_set")
    assert temp_db.list_benchmark_cases(reference_status="confirmed") == []
    case.references[0].confirmed_by = "human"
    temp_db.save_benchmark_case(case)
    assert temp_db.list_benchmark_cases(reference_status="confirmed")


def test_a_reference_outside_reference_dois_is_rejected():
    with pytest.raises(ValidationError):
        BenchmarkCase(
            case_id="c1",
            topic="t",
            query="q",
            reference_dois=["10.1/a"],
            references=[_ref("10.1/b")],
        )


def test_spec_requires_two_different_versions():
    with pytest.raises(ValidationError):
        _spec(["c1"], candidate_version_id="skillv_base")


# ------------------------------------------------------------------- arm execution
@pytest.mark.asyncio
async def test_both_arms_obey_the_same_frozen_protocol(temp_db, monkeypatch):
    case = _case("c1", "agent memory", "development", ["10.1/a"], confirmed=False)
    temp_db.save_benchmark_case(case)
    spec = _spec(["c1"], top_k=15, max_api_requests=6, year_from=2020, year_to=2025)
    seen: list[dict] = []

    async def fake_pipeline(topic):
        seen.append(topic.model_dump())
        return _response([_paper("p1", "10.1/a")], requests=3)

    monkeypatch.setattr(experiment_module, "search_pipeline", fake_pipeline)
    baseline = SkillVersion(
        version_id="skillv_base", version_number=1, strategy=baseline_strategy(),
        created_at="2026-01-01T00:00:00+00:00", status="active",
    )
    candidate = SkillVersion(
        version_id="skillv_cand", version_number=2, parent_version="skillv_base",
        strategy=SearchStrategy(
            query_templates=["{query}"],
            keyword_expansion_rules=["topic_terms"],
            retrieval_budget=RetrievalBudget(max_keywords=2),
        ),
        created_at="2026-01-01T00:00:00+00:00",
    )
    temp_db.save_skill_version(baseline)
    temp_db.save_skill_version(candidate)
    runs = await experiment_module.run_spec(spec, temp_db, arms=("baseline", "candidate"))
    assert [r.arm for r in runs] == ["baseline", "candidate"]
    # The protocol is identical; only the query plan differs.
    assert seen[0]["sources"] == seen[1]["sources"] == spec.sources
    assert seen[0]["top_k"] == seen[1]["top_k"] == 15
    assert seen[0]["year_from"] == seen[1]["year_from"] == 2020
    assert seen[0]["keywords"] == [case.query]
    assert len(seen[1]["keywords"]) == 2
    assert runs[0].status == runs[1].status == "awaiting_reference_set"
    assert runs[0].evaluation.coverage_at_k is None
    assert runs[0].api_request_count == 3
    assert runs[0].raw_snapshot_path and runs[1].raw_snapshot_path


@pytest.mark.asyncio
async def test_candidate_cannot_exceed_the_request_ceiling(temp_db, monkeypatch):
    case = _case("c1", "agent memory", "development", [])
    temp_db.save_benchmark_case(case)
    spec = _spec(["c1"], max_api_requests=3)  # 3 sources -> 1 query allowed
    seen: list[list[str]] = []

    async def fake_pipeline(topic):
        seen.append(topic.keywords)
        return _response([], requests=len(topic.keywords) * 3)

    monkeypatch.setattr(experiment_module, "search_pipeline", fake_pipeline)
    candidate = SkillVersion(
        version_id="skillv_cand", version_number=2,
        strategy=SearchStrategy(
            query_templates=["{query}"],
            keyword_expansion_rules=["topic_terms"],
            retrieval_budget=RetrievalBudget(max_keywords=6),
        ),
        created_at="2026-01-01T00:00:00+00:00",
    )
    temp_db.save_skill_version(candidate)
    baseline = SkillVersion(
        version_id="skillv_base", version_number=1, strategy=baseline_strategy(),
        created_at="2026-01-01T00:00:00+00:00",
    )
    temp_db.save_skill_version(baseline)
    runs = await experiment_module.run_spec(spec, temp_db, arms=("candidate",))
    assert len(seen[0]) == 1
    assert any(e["source"] == "budget" for e in runs[0].source_errors)


@pytest.mark.asyncio
async def test_holdout_is_closed_until_locked_and_then_one_shot(temp_db, monkeypatch):
    case = _case("ch", "agent skill learning", "holdout", ["10.2/a"])
    temp_db.save_benchmark_case(case)
    for vid, num in (("skillv_base", 1), ("skillv_cand", 2)):
        temp_db.save_skill_version(
            SkillVersion(
                version_id=vid, version_number=num, strategy=baseline_strategy(),
                created_at="2026-01-01T00:00:00+00:00",
            )
        )
    spec = _spec(["ch"])
    temp_db.save_spec(spec)

    async def fake_pipeline(topic):
        return _response([_paper("p1", "10.2/a")])

    monkeypatch.setattr(experiment_module, "search_pipeline", fake_pipeline)
    with pytest.raises(ValueError, match="holdout is closed"):
        await experiment_module.run_spec(spec, temp_db)

    spec.candidate_locked_at = "2026-01-02T00:00:00+00:00"
    temp_db.save_spec(spec)
    await experiment_module.run_spec(spec, temp_db)
    with pytest.raises(ValueError, match="one-shot"):
        await experiment_module.run_spec(spec, temp_db)


# ------------------------------------------------------------------------- the API
def test_api_creates_a_case_without_inventing_references(temp_db):
    response = client.post(
        "/api/experiments/benchmark/cases",
        json={"topic": "agent memory", "query": "agent memory survey", "reference_dois": []},
    )
    assert response.status_code == 200
    case = response.json()["case"]
    assert case["reference_dois"] == []
    assert case["references"] == []
    listing = client.get("/api/experiments/benchmark/cases").json()
    assert listing["awaiting_cases"] == 1
    assert listing["confirmed_cases"] == 0


def test_api_reports_unverifiable_dois_instead_of_hiding_them(temp_db, monkeypatch):
    async def fake_verify(doi):
        raise HttpFailure(status=None, detail="DOI could not be verified", source="benchmark")

    monkeypatch.setattr(benchmark_module, "verify_doi", fake_verify)
    monkeypatch.setattr(
        "app.api.routes_experiments.verify_doi", fake_verify
    )
    response = client.post(
        "/api/experiments/benchmark/cases",
        json={
            "topic": "agent memory",
            "query": "agent memory survey",
            "reference_dois": ["10.9999/fake"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["case"]["reference_dois"] == []
    assert body["verification_errors"][0]["doi"] == "10.9999/fake"


def test_api_confirmation_is_the_only_path_to_ground_truth(temp_db, monkeypatch):
    async def fake_verify(doi):
        return _ref(normalize_doi(doi), confirmed=False)

    monkeypatch.setattr("app.api.routes_experiments.verify_doi", fake_verify)
    created = client.post(
        "/api/experiments/benchmark/cases",
        json={
            "topic": "agent memory",
            "query": "agent memory survey",
            "reference_dois": ["10.1/a"],
        },
    ).json()["case"]
    assert created["references"][0]["confirmed_by"] is None

    refused = client.post(
        f"/api/experiments/benchmark/cases/{created['case_id']}/confirm",
        json={"confirmed_by": ""},
    )
    assert refused.status_code == 422

    confirmed = client.post(
        f"/api/experiments/benchmark/cases/{created['case_id']}/confirm",
        json={"confirmed_by": "reviewer"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["case"]["references"][0]["confirmed_by"] == "reviewer"


def test_api_design_rejects_a_topic_spanning_two_splits(temp_db):
    for split in ("development", "validation"):
        temp_db.save_benchmark_case(_case(f"c_{split}", "agent memory", split, []))
    for vid, num in (("skillv_base", 1), ("skillv_cand", 2)):
        temp_db.save_skill_version(
            SkillVersion(
                version_id=vid, version_number=num, strategy=baseline_strategy(),
                created_at="2026-01-01T00:00:00+00:00",
            )
        )
    response = client.post(
        "/api/experiments/design",
        json={
            "case_ids": ["c_development", "c_validation"],
            "baseline_version_id": "skillv_base",
            "candidate_version_id": "skillv_cand",
        },
    )
    assert response.status_code == 400
    assert "leak" in response.json()["detail"]


def test_api_run_and_verify_score_a_case_after_confirmation(temp_db, monkeypatch):
    case = _case("c1", "agent memory", "development", ["10.1/a"], confirmed=False)
    temp_db.save_benchmark_case(case)
    for vid, num in (("skillv_base", 1), ("skillv_cand", 2)):
        temp_db.save_skill_version(
            SkillVersion(
                version_id=vid, version_number=num, strategy=baseline_strategy(),
                created_at="2026-01-01T00:00:00+00:00",
            )
        )
    spec = client.post(
        "/api/experiments/design",
        json={
            "case_ids": ["c1"],
            "baseline_version_id": "skillv_base",
            "candidate_version_id": "skillv_cand",
        },
    ).json()

    async def fake_pipeline(topic):
        return _response([_paper("p1", "10.1/a"), _paper("p2", "10.1/b")], requests=3)

    monkeypatch.setattr(experiment_module, "search_pipeline", fake_pipeline)
    run_body = client.post("/api/experiments/run", json={"spec_id": spec["spec_id"]}).json()
    assert len(run_body["runs"]) == 2
    assert all(r["status"] == "awaiting_reference_set" for r in run_body["runs"])
    assert run_body["promotion_gate"]["allowed"] is False
    assert any("no human-confirmed reference set" in r for r in run_body["promotion_gate"]["reasons"])
    assert run_body["comparisons"][0]["coverage_delta"] is None

    # Confirm the reference, then independently re-score the stored snapshot.
    temp_db.save_benchmark_case(_case("c1", "agent memory", "development", ["10.1/a"]))
    run_id = run_body["runs"][0]["run_id"]
    verified = client.post("/api/experiments/verify", json={"run_id": run_id}).json()
    assert verified["matches_stored"] is False
    assert verified["evaluation"]["status"] == "computed"
    assert verified["evaluation"]["coverage_at_k"] == 1.0
    assert verified["evaluation"]["missed_references"] == []
    assert verified["evaluation"]["api_query_count"] == 3
    assert verified["recomputed_from"].endswith(".json")

    again = client.post("/api/experiments/verify", json={"run_id": run_id}).json()
    assert again["matches_stored"] is True


def test_api_verify_refuses_a_run_without_a_snapshot(temp_db):
    case = _case("c1", "agent memory", "development", [])
    temp_db.save_benchmark_case(case)
    run = _arm(case, "baseline", retrieved=[], requests=0, spec_cases=[case])
    run.raw_snapshot_path = None
    temp_db.save_experiment_run(run, case.split)
    response = client.post("/api/experiments/verify", json={"run_id": run.run_id})
    assert response.status_code == 409
    assert "snapshot" in response.json()["detail"]


def test_api_skill_version_creation_never_activates(temp_db):
    seeded = client.get("/api/skills/active").json()["version"]
    created = client.post(
        "/api/skills/versions",
        json={
            "strategy": {
                "query_templates": ["{query}"],
                "keyword_expansion_rules": ["topic_terms"],
                "retrieval_budget": {"top_k": 20, "max_keywords": 2, "max_api_requests": 3},
            },
            "mutation_description": "add topic-term expansion after a narrow-query failure",
            "source_trials": ["exprun_1"],
        },
    )
    assert created.status_code == 200
    version = created.json()
    assert version["status"] == "candidate"
    assert version["parent_version"] == seeded["version_id"]
    assert version["version_number"] == seeded["version_number"] + 1
    assert client.get("/api/skills/active").json()["version"]["version_id"] == seeded["version_id"]

    preview = client.post(
        "/api/skills/preview",
        json={"version_id": version["version_id"], "topic": "agent memory", "query": "agent memory"},
    ).json()
    assert preview["query_count"] == 2


def test_api_templates_describe_the_hypothesis_as_unproven(temp_db):
    body = client.get("/api/experiments/templates").json()
    template = body["templates"][0]
    assert template["hypothesis_status"] == "under_test"
    assert template["evaluator_version"]
    assert {m["key"] for m in template["metrics"]} == {
        "coverage_at_k", "missed_references", "api_query_count",
        "unique_paper_count", "execution_time_ms",
    }