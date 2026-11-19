"""Unit tests for the independent Python gap validator and the final gate.

No LLM is involved: the candidate, the critique and the counter-search outcome are
inputs, and every check is re-derived from papers actually stored in `temp_db`.
The tests lock in the two rules that matter most — a failed search is never "no
counter-evidence", and passing the gate is never a proof of novelty.
"""

from __future__ import annotations

import pytest

from app.config import DEFAULT_GAP_GATE, GATE_NOTICE
from app.models.gap_pipeline import (
    CandidateGap,
    CounterSearchOutcome,
    EvidenceCard,
    EvidenceCardField,
    EvidenceRef,
    GapCritique,
    GapValidation,
)
from app.models.paper import Paper
from app.services.gap_validator import decide_gate, validate_gap

ABSTRACT = (
    "We study memory consolidation for LLM agents. "
    "We propose a module that compresses episodic traces into reusable skills. "
    "We evaluate on LoCoMo and report accuracy and F1. "
    "However, evaluation protocols differ across papers and results are not comparable. "
    "Future work will release a shared benchmark for this task."
)
SPAN = "evaluation protocols differ across papers and results are not comparable"
CLAIM = (
    "Memory consolidation results are not comparable across papers because each "
    "paper evaluates on its own protocol and metric family"
)


def _papers(store, count: int = 3, *, dois: bool = True) -> list[Paper]:
    store.save_project("proj_val", "memory consolidation for LLM agents")
    papers = []
    for i in range(count):
        paper = Paper(
            paper_id=f"val:p{i + 1}",
            title=f"Memory consolidation study {i + 1}",
            doi=f"10.9999/val.{i + 1}" if dois else None,
            abstract=ABSTRACT,
            source="openalex",
            source_url=f"https://openalex.org/val:p{i + 1}",
            publication_year=2023 + i,
            retrieved_at="2025-01-01T00:00:00Z",
            run_id="run_val",
        )
        store.save_paper(paper, "proj_val")
        papers.append(paper)
    return papers


def _cards(papers) -> list[EvidenceCard]:
    return [
        EvidenceCard(
            paper_id=p.paper_id,
            title=p.title,
            doi=p.doi,
            source_url=p.source_url,
            limitations=EvidenceCardField(claim="protocols are not comparable", evidence_span=SPAN),
            grounded_fields=["limitations"],
        )
        for p in papers
    ]


def _candidate(papers, **overrides) -> CandidateGap:
    base = dict(
        gap_claim=CLAIM,
        gap_type="evaluation_gap",
        problem_context="agent memory evaluation",
        already_solved="single-paper benchmarks exist",
        unresolved_boundary="no shared protocol across papers",
        supporting_papers=[p.paper_id for p in papers],
        supporting_evidence=[
            EvidenceRef(paper_id=p.paper_id, field="limitations", evidence_span=SPAN)
            for p in papers
        ],
        candidate_research_question="Does a shared protocol change the ranking of methods?",
        minimum_experiment="Re-run two published methods under one protocol.",
        testability="testable with public code",
        novelty_risk="LOW",
    )
    base.update(overrides)
    return CandidateGap(**base)


def _critique(**overrides) -> GapCritique:
    base = dict(
        evidence_grounding=4,
        cross_paper_support=4,
        specificity=4,
        testability=4,
        novelty_risk="LOW",
        contradiction_risk="LOW",
        recommended_action="accept",
        rationale="the claim is grounded in three independent abstracts",
    )
    base.update(overrides)
    return GapCritique(**base)


def _counter(**overrides) -> CounterSearchOutcome:
    base = dict(
        status="NO_COUNTER_EVIDENCE_FOUND",
        detection_key="evaluation protocol",
        queries=["shared evaluation protocol for agent memory"],
        sources=["openalex", "crossref", "arxiv"],
        requests_made=3,
        papers_retrieved=10,
        rejected_as_not_addressing_claim=10,
    )
    base.update(overrides)
    return CounterSearchOutcome(**base)


def _run(store, papers, *, candidate=None, critique=None, counter=None, gate=None):
    candidate = candidate if candidate is not None else _candidate(papers)
    critique = critique if critique is not None else _critique()
    counter = counter if counter is not None else _counter()
    validation = validate_gap(
        store, candidate, _cards(papers), critique, counter, gate=gate
    )
    return validation, decide_gate(validation, critique, gate=gate)


# ------------------------------------------------------------------ happy path
def test_a_grounded_candidate_passes_and_the_gate_disclaims_novelty(temp_db):
    papers = _papers(temp_db)
    validation, gate = _run(temp_db, papers)

    assert validation.passed is True
    assert all(check.passed for check in validation.checks)
    assert validation.unique_supporting_papers == 3
    assert validation.valid_evidence_refs == 3
    assert validation.invalid_evidence_refs == []
    assert validation.missing_papers == []
    assert validation.unverified_dois == []
    assert gate.status == "accepted"
    assert gate.python_passed is True
    assert gate.notice == GATE_NOTICE
    assert "not a mathematical proof of novelty" in gate.notice


# ------------------------------------------------------- hard failures: reject
def test_a_supporting_paper_that_was_never_retrieved_rejects_the_gap(temp_db):
    papers = _papers(temp_db)
    candidate = _candidate(papers, supporting_papers=[p.paper_id for p in papers] + ["val:ghost"])
    validation, gate = _run(temp_db, papers, candidate=candidate)

    assert validation.missing_papers == ["val:ghost"]
    assert validation.by_name["supporting_papers_exist"].passed is False
    assert gate.status == "rejected"


def test_counting_the_same_paper_twice_rejects_the_gap(temp_db):
    papers = _papers(temp_db)
    ids = [p.paper_id for p in papers]
    candidate = _candidate(papers, supporting_papers=[ids[0], ids[0], ids[1], ids[2]])
    validation, gate = _run(temp_db, papers, candidate=candidate)

    assert validation.unique_supporting_papers == 3
    assert validation.duplicate_paper_counting is True
    assert gate.status == "rejected"


def test_the_same_doi_from_two_sources_is_one_paper(temp_db):
    papers = _papers(temp_db)
    twin = Paper(
        paper_id="val:twin",
        title="Memory consolidation study 1 (preprint)",
        doi=papers[0].doi,
        abstract=ABSTRACT,
        source="arxiv",
        source_url="https://arxiv.org/abs/val:twin",
        retrieved_at="2025-01-01T00:00:00Z",
        run_id="run_val",
    )
    temp_db.save_paper(twin, "proj_val")
    candidate = _candidate(papers, supporting_papers=[p.paper_id for p in papers] + ["val:twin"])
    validation, gate = _run(temp_db, papers, candidate=candidate)

    assert validation.duplicate_paper_counting is True
    assert "repeated DOI" in validation.by_name["no_duplicate_paper_counting"].detail
    assert gate.status == "rejected"


def test_a_hallucinated_span_is_rejected_not_trusted(temp_db):
    papers = _papers(temp_db)
    fabricated = "the authors never released code, data or evaluation scripts"
    candidate = _candidate(
        papers,
        supporting_evidence=[
            EvidenceRef(paper_id=p.paper_id, field="limitations", evidence_span=fabricated)
            for p in papers
        ],
    )
    validation, gate = _run(temp_db, papers, candidate=candidate)

    assert validation.valid_evidence_refs == 0
    assert len(validation.invalid_evidence_refs) == 3
    assert validation.by_name["evidence_spans_verbatim"].passed is False
    assert gate.status == "rejected"


def test_evidence_citing_a_non_supporting_paper_rejects_the_gap(temp_db):
    papers = _papers(temp_db, count=4)
    candidate = _candidate(papers[:3])
    candidate.supporting_evidence.append(
        EvidenceRef(paper_id=papers[3].paper_id, field="limitations", evidence_span=SPAN)
    )
    validation, gate = _run(temp_db, papers[:3], candidate=candidate)

    assert validation.by_name["evidence_subset_of_supporting_papers"].passed is False
    assert gate.status == "rejected"


def test_a_generic_claim_is_not_a_research_gap(temp_db):
    papers = _papers(temp_db)
    candidate = _candidate(papers, gap_claim="further research is needed in this area")
    validation, gate = _run(temp_db, papers, candidate=candidate)

    assert validation.by_name["claim_is_specific"].passed is False
    assert gate.status == "rejected"


def test_a_critic_reject_overrides_a_clean_python_pass(temp_db):
    papers = _papers(temp_db)
    critique = _critique(recommended_action="reject", rationale="the boundary is already solved")
    validation, gate = _run(temp_db, papers, critique=critique)

    assert gate.critic_rejected is True
    assert gate.status == "rejected"
    assert "the independent critic recommended reject" in gate.reasons


def test_an_empty_validation_is_rejected_rather_than_accepted(temp_db):
    gate = decide_gate(GapValidation(), None)
    assert gate.status == "rejected"


# --------------------------------------------- soft failures: needs_human_review
def test_a_low_critic_score_sends_the_gap_to_a_human(temp_db):
    papers = _papers(temp_db)
    validation, gate = _run(temp_db, papers, critique=_critique(evidence_grounding=2))

    assert validation.by_name["critic_evidence_grounding"].passed is False
    assert validation.passed is False
    assert gate.status == "needs_human_review"


def test_without_a_critic_review_the_gap_cannot_be_accepted(temp_db):
    papers = _papers(temp_db)
    validation = validate_gap(temp_db, _candidate(papers), _cards(papers), None, _counter())
    gate = decide_gate(validation, None)

    assert validation.by_name["critic_available"].passed is False
    assert "no independent critic review" in " ".join(validation.reasons)
    assert gate.status == "needs_human_review"


@pytest.mark.parametrize("status", ["COUNTER_SEARCH_FAILED", "NOT_RUN"])
def test_a_failed_or_unrun_search_is_never_no_counter_evidence(temp_db, status):
    papers = _papers(temp_db)
    validation, gate = _run(temp_db, papers, counter=_counter(status=status))

    assert validation.counter_search_status == status
    assert validation.by_name["counter_search_completed"].passed is False
    assert any("cannot be cleared by an absence of results" in r for r in validation.reasons)
    assert gate.status == "needs_human_review"


def test_prior_art_forces_high_novelty_risk_and_blocks_acceptance(temp_db):
    papers = _papers(temp_db)
    counter = _counter(
        status="COUNTER_EVIDENCE_FOUND",
        prior_art=[{"paper_id": "val:p1", "title": "A shared protocol", "doi": "10.9999/val.1"}],
        rejected_as_not_addressing_claim=9,
    )
    validation, gate = _run(temp_db, papers, counter=counter)

    assert validation.prior_art_collisions == 1
    assert validation.novelty_risk == "HIGH"
    assert validation.unique_counter_papers == 1
    detail = validation.by_name["novelty_risk_within_gate"].detail
    assert "potential prior art" in detail and "val:p1" in detail
    assert gate.status == "needs_human_review"


def test_duplicate_prior_art_entries_are_counted_as_one_paper(temp_db):
    papers = _papers(temp_db)
    entry = {"paper_id": "val:p1", "title": "A shared protocol"}
    counter = _counter(status="COUNTER_EVIDENCE_FOUND", prior_art=[entry, dict(entry)])
    validation, _ = _run(temp_db, papers, counter=counter)

    assert validation.prior_art_collisions == 2
    assert validation.unique_counter_papers == 1


def test_a_paper_without_a_usable_doi_is_reported_not_hidden(temp_db):
    papers = _papers(temp_db, dois=False)
    validation, gate = _run(temp_db, papers)

    assert validation.unverified_dois == [p.paper_id for p in papers]
    check = validation.by_name["doi_present_and_wellformed"]
    assert check.passed is False
    assert "not a registry lookup" in check.detail
    assert gate.status == "needs_human_review"


def test_contradicting_evidence_raises_the_contradiction_risk(temp_db):
    papers = _papers(temp_db)
    candidate = _candidate(papers)
    candidate.contradicting_evidence = [
        EvidenceRef(paper_id=papers[0].paper_id, field="limitations", evidence_span=SPAN)
    ]
    gate_rules = {**DEFAULT_GAP_GATE, "max_contradiction_risk": "LOW"}
    validation, gate = _run(temp_db, papers, candidate=candidate, gate=gate_rules)

    assert validation.evidence_contradiction is True
    assert validation.by_name["contradiction_risk_within_gate"].passed is False
    assert gate.status == "needs_human_review"


def test_a_contradiction_gap_maps_to_the_internal_type_and_flags_conflict(temp_db):
    papers = _papers(temp_db)
    candidate = _candidate(
        papers,
        gap_claim=(
            "Two retrieved papers report opposite effects of memory compression on "
            "tool-call accuracy under the same dialogue setting"
        ),
        gap_type="contradiction_gap",
    )
    candidate.contradicting_evidence = [
        EvidenceRef(paper_id=papers[1].paper_id, field="limitations", evidence_span=SPAN)
    ]
    validation, gate = _run(temp_db, papers, candidate=candidate)

    assert candidate.internal_gap_type == "contradiction"
    assert validation.evidence_contradiction is True
    assert validation.passed is True
    assert gate.status == "accepted"


# ------------------------------------------------------------- configurable gate
def test_the_support_threshold_is_configurable(temp_db):
    papers = _papers(temp_db)
    gate_rules = {**DEFAULT_GAP_GATE, "min_supporting_papers": 4}
    validation, gate = _run(temp_db, papers, gate=gate_rules)

    assert validation.by_name["min_supporting_papers"].passed is False
    assert validation.passed is False
    assert gate.status == "needs_human_review"
    assert gate.thresholds["min_supporting_papers"] == 4


def test_requiring_a_successful_counter_search_is_configurable(temp_db):
    papers = _papers(temp_db)
    gate_rules = {**DEFAULT_GAP_GATE, "require_counter_search_success": False}
    validation, gate = _run(
        temp_db, papers, counter=_counter(status="NOT_RUN"), gate=gate_rules
    )

    assert validation.by_name["counter_search_completed"].passed is True
    assert gate.status == "accepted"