"""Offline tests for research gap detection and its evidence contract.

No network: counter-evidence search is exercised by patching the pipeline at its
use site, so the tests assert how real responses are handled without making any.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.gap import (
    Experimentability,
    GapEvidenceItem,
    ResearchGap,
)
from app.models.paper import EXTRACTED_FIELDS, FieldEvidence, Paper
from app.services.classify import UNCLASSIFIED, classify_method
from app.services.extract import extract_from_abstract
from app.services.gap import ResearchGapAnalyzer


def _paper(pid: str, **kwargs) -> Paper:
    defaults = dict(
        paper_id=pid,
        title=f"Memory mechanisms for LLM agents {pid}",
        source="openalex",
        source_url=f"https://openalex.org/{pid}",
        abstract="We propose a memory module for LLM agents.",
        publication_year=2025,
    )
    defaults.update(kwargs)
    return Paper(**defaults)


def _ev(span: str) -> FieldEvidence:
    return FieldEvidence(
        value=span,
        evidence_source="abstract",
        evidence_span=span,
        confidence="medium",
    )


def _gap(**overrides) -> ResearchGap:
    base = dict(
        gap_id="gap_1",
        title="A candidate gap",
        description="Two papers share a constraint.",
        gap_type="method",
        supporting_papers=["a", "b"],
        supporting_evidence=[
            GapEvidenceItem(
                paper_id="a", title="A", source_url="https://x/a",
                field="limitations", evidence_span="cannot scale",
            ),
            GapEvidenceItem(
                paper_id="b", title="B", source_url="https://x/b",
                field="limitations", evidence_span="cannot scale",
            ),
        ],
        unresolved_question="Can it scale?",
        experimentability=Experimentability(
            testable_minimally=False, proposed_experiment="none", blocking_reason="cost"
        ),
        confidence_label="Medium",
        confidence_rationale="two papers state the limitation",
        run_id="run_1",
    )
    base.update(overrides)
    return ResearchGap(**base)


# --------------------------------------------------------------------- contract
def test_single_paper_cannot_produce_a_gap():
    with pytest.raises(ValidationError, match="at least two distinct papers"):
        _gap(supporting_papers=["a"])


def test_duplicate_paper_ids_do_not_count_as_two():
    with pytest.raises(ValidationError, match="at least two distinct papers"):
        _gap(supporting_papers=["a", "a"])


def test_evidence_must_belong_to_a_supporting_paper():
    with pytest.raises(ValidationError, match="non-supporting papers"):
        _gap(
            supporting_evidence=[
                GapEvidenceItem(
                    paper_id="c", title="C", source_url="https://x/c",
                    field="limitations", evidence_span="cannot scale",
                )
            ]
        )


def test_evidence_span_cannot_be_empty():
    with pytest.raises(ValidationError, match="verbatim span"):
        GapEvidenceItem(
            paper_id="a", title="A", source_url="https://x/a",
            field="limitations", evidence_span="   ",
        )


def test_confidence_label_requires_rationale():
    with pytest.raises(ValidationError, match="rationale"):
        _gap(confidence_rationale="  ")


def test_default_status_is_needs_human_review():
    assert _gap().status == "needs_human_review"


def test_scope_notice_never_claims_nonexistence():
    notice = _gap().scope_notice
    assert "does not establish" in notice
    assert "current search scope" in notice


# -------------------------------------------------------------------- extraction
def test_new_agent_fields_are_part_of_the_schema():
    for name in ("agent_architecture", "memory_strategy", "skill_strategy"):
        assert name in EXTRACTED_FIELDS


def test_heuristic_extraction_labels_its_method_and_status():
    paper = _paper(
        "a",
        abstract=(
            "We propose a multi-agent planner with an episodic memory module. "
            "The skill library reuses learned skills across tasks."
        ),
    )
    extract_from_abstract(paper)
    assert paper.agent_architecture.is_known
    assert paper.memory_strategy.is_known
    assert paper.skill_strategy.is_known
    for name in ("agent_architecture", "memory_strategy", "skill_strategy"):
        ev = getattr(paper, name)
        assert ev.extraction_method == "heuristic"
        assert ev.evidence_status == "grounded"
        assert ev.evidence_span and ev.evidence_span in paper.abstract


def test_unknown_fields_stay_unknown():
    paper = _paper("a", abstract="   ")
    extract_from_abstract(paper)
    assert paper.evidence_status == "metadata_only"
    assert paper.method.extraction_method == "none"
    assert paper.method.evidence_status == "unknown"
    assert set(paper.missing_fields) == set(EXTRACTED_FIELDS)


def test_method_classification_is_deterministic():
    paper = _paper("a", abstract="We release a benchmark for agent memory evaluation.")
    first = classify_method(paper)
    assert first == classify_method(paper)
    assert first == "benchmark / evaluation"
    assert classify_method(
        _paper("b", title="An unrelated study", abstract="Nothing relevant here.")
    ) == UNCLASSIFIED


# ---------------------------------------------------------------------- analyzer
def test_method_gap_needs_two_papers_with_a_shared_limitation():
    a = _paper("a", limitations=_ev("The memory index cannot scale to long histories."))
    b = _paper("b", limitations=_ev("Retrieval cannot scale beyond short contexts."))
    a.method_class = b.method_class = "memory-augmented agent"
    gaps = ResearchGapAnalyzer([a, b], "agent memory", "run_1").analyze()
    method_gaps = [g for g in gaps if g.gap_type == "method"]
    assert len(method_gaps) == 1
    assert len(method_gaps[0].supporting_papers) == 2
    assert method_gaps[0].confidence_label in ("Medium", "High")


def test_one_paper_with_a_limitation_yields_no_method_gap():
    a = _paper("a", limitations=_ev("cannot scale"))
    b = _paper("b")
    a.method_class = b.method_class = "memory-augmented agent"
    gaps = ResearchGapAnalyzer([a, b], "agent memory", "run_1").analyze()
    assert not [g for g in gaps if g.gap_type == "method"]


def test_topic_words_are_not_treated_as_a_shared_limitation():
    a = _paper("a", limitations=_ev("memory memory memory"))
    b = _paper("b", limitations=_ev("memory memory"))
    a.method_class = b.method_class = "memory-augmented agent"
    gaps = ResearchGapAnalyzer([a, b], "memory", "run_1").analyze()
    assert not [g for g in gaps if g.gap_type == "method"]


def test_absence_gaps_are_never_high_confidence():
    papers = []
    for pid in ("a", "b", "c"):
        p = _paper(pid, abstract="We propose a memory module evaluated on LongMemEval.")
        p.method_class = "memory-augmented agent"
        papers.append(p)
    gaps = ResearchGapAnalyzer(papers, "agent memory", "run_1").analyze()
    absence = [g for g in gaps if g.gap_type in ("generalization", "reliability",
                                               "efficiency", "reproducibility")]
    assert absence, "expected absence-based candidates"
    assert all(g.confidence_label in ("Low", "Medium") for g in absence)
    assert all("abstracts only" in g.description for g in absence)


def test_evaluation_gap_requires_disjoint_metric_families():
    a = _paper("a", evaluation_metrics=_ev("We report accuracy and F1."))
    b = _paper("b", evaluation_metrics=_ev("We report BLEU and ROUGE."))
    a.method_class = b.method_class = "memory-augmented agent"
    gaps = ResearchGapAnalyzer([a, b], "agent memory", "run_1").analyze()
    assert any(g.gap_type == "evaluation" for g in gaps)


def test_shared_metrics_do_not_produce_an_evaluation_gap():
    a = _paper("a", evaluation_metrics=_ev("We report accuracy."))
    b = _paper("b", evaluation_metrics=_ev("We report accuracy as well."))
    a.method_class = b.method_class = "memory-augmented agent"
    gaps = ResearchGapAnalyzer([a, b], "agent memory", "run_1").analyze()
    assert not [g for g in gaps if g.gap_type == "evaluation"]


def test_every_gap_carries_experimentability_and_related_work():
    a = _paper("a", limitations=_ev("cannot scale to long histories"))
    b = _paper("b", limitations=_ev("cannot scale across domains"))
    a.method_class = b.method_class = "memory-augmented agent"
    for gap in ResearchGapAnalyzer([a, b], "agent memory", "run_1").analyze():
        assert gap.unresolved_question
        assert gap.experimentability.proposed_experiment
        assert gap.closest_related_work
        assert gap.counter_search_queries


def test_counter_query_targets_all_three_sources():
    analyzer = ResearchGapAnalyzer([_paper("a"), _paper("b")], "agent memory", "run_1")
    query = analyzer.counter_query("generalization", "unused")
    assert "agent memory" in query
    assert "unseen" in query


# ------------------------------------------------------- counter-evidence wiring
@pytest.mark.asyncio
async def test_counter_evidence_downgrades_confidence(monkeypatch):
    from app.models.schemas import SearchResponse
    from app.services import gap as gap_module

    a = _paper("a", limitations=_ev("cannot scale to long histories"))
    b = _paper("b", limitations=_ev("cannot scale across domains"))
    a.method_class = b.method_class = "memory-augmented agent"
    analyzer = ResearchGapAnalyzer([a, b], "agent memory", "run_1")
    gaps = [g for g in analyzer.analyze() if g.gap_type == "method"]
    assert gaps and gaps[0].confidence_label in ("Medium", "High")

    counter = _paper(
        "counter",
        source="crossref",
        doi="10.1/real",
        abstract="We scale the memory module to long agent histories.",
    )
    response = SearchResponse(
        run_id="run_counter", project_id="proj_1", topic="agent memory",
        meta={"requests_made": 3, "cache_hits": 0}, papers=[counter], source_errors=[],
        stats={},
    )

    async def fake_pipeline(topic):
        assert topic.sources == ["openalex", "crossref", "arxiv"]
        return response

    monkeypatch.setattr(gap_module, "search_pipeline", fake_pipeline)
    result = await analyzer.add_counter_evidence(gaps, top_k=5)

    assert len(result[0].counter_evidence) == 1
    assert result[0].counter_evidence[0].doi == "10.1/real"
    assert result[0].counter_evidence[0].matched_cue == gaps[0].detection_key
    assert result[0].counter_evidence[0].evidence_span
    assert result[0].confidence_label == "Low"
    assert "downgraded" in result[0].confidence_rationale
    assert result[0].counter_search_scope["sources"] == ["openalex", "crossref", "arxiv"]


@pytest.mark.asyncio
async def test_topical_paper_is_not_counter_evidence(monkeypatch):
    """Sharing the topic is not enough: the paper must address the specific claim."""
    from app.models.schemas import SearchResponse
    from app.services import gap as gap_module

    a = _paper("a", limitations=_ev("cannot scale to long histories"))
    b = _paper("b", limitations=_ev("cannot scale across domains"))
    a.method_class = b.method_class = "memory-augmented agent"
    analyzer = ResearchGapAnalyzer([a, b], "agent memory", "run_1")
    gaps = [g for g in analyzer.analyze() if g.gap_type == "method"]
    assert gaps[0].detection_key == "scale"

    topical = _paper("topical", source="openalex", doi="10.2/topical")
    response = SearchResponse(
        run_id="run_counter", project_id="proj_1", topic="agent memory",
        meta={"requests_made": 3}, papers=[topical], source_errors=[], stats={},
    )

    async def fake_pipeline(topic):
        return response

    monkeypatch.setattr(gap_module, "search_pipeline", fake_pipeline)
    result = await analyzer.add_counter_evidence(gaps, top_k=5)

    assert result[0].counter_evidence == []
    assert result[0].confidence_label in ("Medium", "High")
    assert "no counter-evidence found" in result[0].confidence_rationale
    scope = result[0].counter_search_scope
    assert scope["papers_retrieved"] == 1
    assert scope["rejected_as_not_addressing_claim"] == 1


@pytest.mark.asyncio
async def test_absence_gap_counter_evidence_must_show_the_missing_capability(monkeypatch):
    from app.models.schemas import SearchResponse
    from app.services import gap as gap_module

    a = _paper("a")
    b = _paper("b")
    a.method_class = b.method_class = "planning / reasoning"
    analyzer = ResearchGapAnalyzer([a, b], "agent planning", "run_1")
    gaps = [g for g in analyzer.analyze() if g.gap_type == "generalization"]
    assert gaps and gaps[0].detection_key == "generalization"

    solves = _paper(
        "solves", source="arxiv", doi="10.3/gen",
        abstract="We evaluate on held-out unseen subtopics to test generalization.",
    )
    ignores = _paper("ignores", source="openalex", doi="10.4/ign")
    response = SearchResponse(
        run_id="run_counter", project_id="proj_1", topic="agent planning",
        meta={}, papers=[ignores, solves], source_errors=[], stats={},
    )

    async def fake_pipeline(topic):
        return response

    monkeypatch.setattr(gap_module, "search_pipeline", fake_pipeline)
    result = await analyzer.add_counter_evidence(gaps, top_k=5)

    assert [c.paper_id for c in result[0].counter_evidence] == ["solves"]
    assert result[0].counter_evidence[0].matched_cue in ("held-out", "unseen", "generaliz")
    assert result[0].counter_search_scope["rejected_as_not_addressing_claim"] == 1


@pytest.mark.asyncio
async def test_evaluation_gap_needs_a_paper_bridging_two_metric_families(monkeypatch):
    from app.models.schemas import SearchResponse
    from app.services import gap as gap_module

    a = _paper("a", evaluation_metrics=_ev("accuracy on the test split"))
    b = _paper("b", evaluation_metrics=_ev("BLEU and ROUGE scores"))
    a.method_class = b.method_class = "benchmark / evaluation"
    analyzer = ResearchGapAnalyzer([a, b], "agent benchmarks", "run_1")
    gaps = [g for g in analyzer.analyze() if g.gap_type == "evaluation"]
    assert gaps

    single = _paper(
        "single", source="openalex", doi="10.5/single",
        abstract="We report accuracy only.",
    )
    bridge = _paper(
        "bridge", source="crossref", doi="10.6/bridge",
        abstract="We report accuracy alongside BLEU for the same tasks.",
    )
    response = SearchResponse(
        run_id="run_counter", project_id="proj_1", topic="agent benchmarks",
        meta={}, papers=[single, bridge], source_errors=[], stats={},
    )

    async def fake_pipeline(topic):
        return response

    monkeypatch.setattr(gap_module, "search_pipeline", fake_pipeline)
    result = await analyzer.add_counter_evidence(gaps, top_k=5)

    assert [c.paper_id for c in result[0].counter_evidence] == ["bridge"]
    assert "accuracy" in result[0].counter_evidence[0].matched_cue
    assert "generation" in result[0].counter_evidence[0].matched_cue


@pytest.mark.asyncio
async def test_counter_search_records_real_source_errors(monkeypatch):
    from app.models.paper import SourceError
    from app.models.schemas import SearchResponse
    from app.services import gap as gap_module

    a = _paper("a", limitations=_ev("cannot scale to long histories"))
    b = _paper("b", limitations=_ev("cannot scale across domains"))
    a.method_class = b.method_class = "memory-augmented agent"
    analyzer = ResearchGapAnalyzer([a, b], "agent memory", "run_1")
    gaps = [g for g in analyzer.analyze() if g.gap_type == "method"]

    response = SearchResponse(
        run_id="run_counter", project_id="proj_1", topic="agent memory",
        meta={"requests_made": 1, "cache_hits": 0}, papers=[],
        source_errors=[SourceError(source="arxiv", status=429, detail="rate limited")],
        stats={},
    )

    async def fake_pipeline(topic):
        return response

    monkeypatch.setattr(gap_module, "search_pipeline", fake_pipeline)
    result = await analyzer.add_counter_evidence(gaps, top_k=5)

    assert result[0].counter_evidence == []
    assert result[0].counter_search_errors[0]["source"] == "arxiv"
    assert result[0].counter_search_errors[0]["status"] == 429
    assert "no counter-evidence found" in result[0].confidence_rationale


@pytest.mark.asyncio
async def test_supporting_papers_are_not_returned_as_counter_evidence(monkeypatch):
    from app.models.schemas import SearchResponse
    from app.services import gap as gap_module

    a = _paper("a", limitations=_ev("cannot scale to long histories"))
    b = _paper("b", limitations=_ev("cannot scale across domains"))
    a.method_class = b.method_class = "memory-augmented agent"
    analyzer = ResearchGapAnalyzer([a, b], "agent memory", "run_1")
    gaps = [g for g in analyzer.analyze() if g.gap_type == "method"]

    response = SearchResponse(
        run_id="run_counter", project_id="proj_1", topic="agent memory",
        meta={}, papers=[a, b], source_errors=[], stats={},
    )

    async def fake_pipeline(topic):
        return response

    monkeypatch.setattr(gap_module, "search_pipeline", fake_pipeline)
    result = await analyzer.add_counter_evidence(gaps, top_k=5)
    assert result[0].counter_evidence == []