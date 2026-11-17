"""Tests for dedupe.py — DOI and title deduplication."""

from app.models.paper import Paper
from app.services.dedupe import dedupe


def _make_paper(paper_id: str, title: str, doi: str | None = None) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=title,
        authors=[],
        source="openalex",
        source_url="https://example.com",
        doi=doi,
    )


def test_dedupe_by_doi():
    p1 = _make_paper("oa:1", "Paper A", doi="10.1234/test")
    p2 = _make_paper("cr:1", "Paper A", doi="https://doi.org/10.1234/test")
    result = dedupe([p1, p2])
    assert len(result) == 1
    assert result[0].paper_id == "oa:1"
    assert p2.duplicate_of == "oa:1"


def test_dedupe_by_title_similarity():
    p1 = _make_paper("oa:1", "Deep Learning for Smart Contracts")
    p2 = _make_paper("cr:1", "deep learning for smart contracts")
    result = dedupe([p1, p2])
    assert len(result) == 1


def test_no_dedupe_different_titles():
    p1 = _make_paper("oa:1", "Deep Learning for Smart Contracts")
    p2 = _make_paper("cr:1", "Machine Learning for Image Recognition")
    result = dedupe([p1, p2])
    assert len(result) == 2


def test_dedupe_empty_list():
    assert dedupe([]) == []


def test_dedupe_keeps_highest_score():
    p1 = _make_paper("oa:1", "Same Title", doi="10.1/a")
    p1.citation_count = 5
    p2 = _make_paper("cr:1", "Same Title", doi="10.1/a")
    p2.citation_count = 100
    result = dedupe([p1, p2])
    assert len(result) == 1
    assert result[0].citation_count == 100
