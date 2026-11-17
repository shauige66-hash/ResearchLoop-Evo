"""Tests for extract.py — heuristic extraction from abstracts."""

from app.models.paper import Paper
from app.services.extract import extract_from_abstract


def _make_paper(abstract: str) -> Paper:
    return Paper(
        paper_id="test:1",
        title="Test",
        source="openalex",
        source_url="https://example.com",
        abstract=abstract,
    )


def test_extract_method():
    paper = _make_paper("We propose a novel method for testing smart contracts.")
    result = extract_from_abstract(paper)
    assert result.method.is_known
    assert result.method.evidence_source == "abstract"
    assert "propose" in result.method.value.lower()


def test_extract_findings():
    paper = _make_paper("Results show that our approach outperforms baselines by 15%.")
    result = extract_from_abstract(paper)
    assert result.findings.is_known
    assert "results show" in result.findings.value.lower()


def test_extract_limitations():
    paper = _make_paper("However, our method has limitations when applied to large datasets.")
    result = extract_from_abstract(paper)
    assert result.limitations.is_known


def test_extract_multiple_fields():
    paper = _make_paper(
        "We propose a new method. Results show improvement. However, limitations remain."
    )
    result = extract_from_abstract(paper)
    assert result.method.is_known
    assert result.findings.is_known
    assert result.limitations.is_known


def test_extract_no_match_leaves_unknown():
    paper = _make_paper("This paper discusses various topics.")
    result = extract_from_abstract(paper)
    assert not result.method.is_known
    assert result.method.evidence_source == "none"


def test_extract_empty_abstract():
    paper = _make_paper("")
    result = extract_from_abstract(paper)
    assert not result.method.is_known
    assert result.evidence_status == "metadata_only"


def test_extract_preserves_evidence_span():
    paper = _make_paper("We propose a transformer-based approach for code analysis.")
    result = extract_from_abstract(paper)
    assert result.method.evidence_span is not None
    assert "propose" in result.method.evidence_span.lower()
