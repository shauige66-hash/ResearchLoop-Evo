"""Offline tests for report generation, including the empty-input edge case."""

from __future__ import annotations

from app.models.paper import FieldEvidence, Paper
from app.models.schemas import MatrixResponse
from app.services.report import generate_report


def _paper(pid: str, **kwargs) -> Paper:
    defaults = dict(
        paper_id=pid,
        title=f"Paper {pid}",
        source="openalex",
        source_url=f"https://openalex.org/{pid}",
        venue="Nature",
        document_type="article",
        publication_year=2025,
    )
    defaults.update(kwargs)
    return Paper(**defaults)


def test_empty_paper_list_does_not_divide_by_zero():
    report = generate_report([], "agent memory")
    assert report.paper_count == 0
    overview = report.sections[0]
    assert "n/a" in overview.paragraphs[1]
    assert "if total else" not in overview.paragraphs[1]


def test_categories_report_counts_not_paper_objects():
    report = generate_report([_paper("a"), _paper("b")], "agent memory")
    categories = next(s for s in report.sections if s.id == "categories")
    text = " ".join(categories.paragraphs)
    assert "Nature (2)" in text
    assert "Paper(" not in text
    assert "paper_id=" not in text


def test_representative_section_handles_unknown_relevance():
    papers = [_paper("a", relevance_score=None), _paper("b", relevance_score=8.0)]
    report = generate_report(papers, "agent memory")
    assert any(s.id == "representative" for s in report.sections)


def test_report_separates_facts_claims_and_inference():
    span = "Results show a 12% improvement."
    paper = _paper(
        "a",
        findings=FieldEvidence(
            value=span, evidence_source="abstract", evidence_span=span, confidence="medium"
        ),
    )
    report = generate_report([paper], "agent memory")
    kinds = {s.id: s.kind for s in report.sections}
    assert kinds["overview"] == "facts"
    assert kinds["conclusions"] == "author_claims"
    assert kinds["open_questions"] == "system_inference"
    assert any("Heuristic Mode" in c for c in report.caveats)


def test_method_section_is_labelled_mixed_when_system_classes_are_used():
    span = "We propose a memory module."
    paper = _paper(
        "a",
        abstract=span,
        method=FieldEvidence(
            value=span, evidence_source="abstract", evidence_span=span, confidence="medium"
        ),
    )
    report = generate_report([paper], "agent memory")
    methods = next(s for s in report.sections if s.id == "methods")
    assert methods.kind == "mixed"
    assert "system-assigned" in methods.paragraphs[0]

def test_extraction_mode_is_reported_not_hardcoded_in_the_ui():
    """The UI banner must be bound to a backend value that reflects the extractor."""
    from app.models.gap import GapListResponse
    from app.models.paper import EXTRACTION_MODE, SearchMeta

    report = generate_report([_paper("a")], "agent memory")
    assert report.extraction_mode == EXTRACTION_MODE == "heuristic"
    assert GapListResponse(gaps=[], total=0).extraction_mode == "heuristic"
    assert MatrixResponse(
        columns=[], rows=[], generated_at="now", notice="n"
    ).extraction_mode == "heuristic"
    meta = SearchMeta(
        retrieved_at="now", duration_ms=1, cache_hits=0, requests_made=1,
        sources_requested=["openalex"], sources_failed=[],
    )
    assert meta.extraction_mode == "heuristic"
    assert "Heuristic Mode" in meta.notice
