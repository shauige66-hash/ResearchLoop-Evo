"""Tests for rank.py — paper ranking by composite score."""

from app.models.paper import Paper
from app.services.rank import rank_papers


def _make_paper(
    paper_id: str,
    relevance: float = 0.0,
    year: int | None = None,
    citations: int | None = None,
    is_review: bool = False,
) -> Paper:
    return Paper(
        paper_id=paper_id,
        title=f"Paper {paper_id}",
        source="openalex",
        source_url="https://example.com",
        relevance_score=relevance,
        publication_year=year,
        citation_count=citations,
        is_review=is_review,
    )


def test_rank_by_relevance():
    p1 = _make_paper("1", relevance=0.5)
    p2 = _make_paper("2", relevance=0.9)
    result = rank_papers([p1, p2], keywords=[])
    assert result[0].paper_id == "2"


def test_rank_by_citations():
    p1 = _make_paper("1", citations=10)
    p2 = _make_paper("2", citations=1000)
    result = rank_papers([p1, p2], keywords=[])
    assert result[0].paper_id == "2"


def test_rank_by_year():
    p1 = _make_paper("1", year=2010)
    p2 = _make_paper("2", year=2024)
    result = rank_papers([p1, p2], keywords=[])
    assert result[0].paper_id == "2"


def test_rank_review_bonus():
    p1 = _make_paper("1", is_review=False)
    p2 = _make_paper("2", is_review=True)
    result = rank_papers([p1, p2], keywords=[], prefer_reviews=True)
    assert result[0].paper_id == "2"


def test_rank_keyword_overlap():
    p1 = _make_paper("1")
    p1.title = "Deep Learning for Smart contracts"
    p2 = _make_paper("2")
    p2.title = "Machine Learning for image recognition"
    result = rank_papers([p1, p2], keywords=["smart", "contracts"])
    assert result[0].paper_id == "1"


def test_rank_empty_list():
    assert rank_papers([], keywords=[]) == []


def test_missing_source_signals_do_not_structurally_sink_a_paper():
    """arXiv reports neither relevance nor citations; it must still be rankable."""
    arxiv_style = Paper(
        paper_id="arxiv:1",
        title="LLM agent memory mechanisms",
        source="arxiv",
        source_url="https://arxiv.org/abs/1",
        relevance_score=None,
        citation_count=None,
        publication_year=2026,
    )
    openalex_style = Paper(
        paper_id="openalex:1",
        title="Unrelated older work",
        source="openalex",
        source_url="https://openalex.org/1",
        relevance_score=1.0,
        citation_count=1,
        publication_year=2010,
    )
    result = rank_papers([openalex_style, arxiv_style], keywords=["agent", "memory"])
    assert result[0].paper_id == "arxiv:1"


def test_unknown_relevance_is_distinct_from_zero_relevance():
    unknown = _make_paper("unknown", year=2026)
    unknown.relevance_score = None
    zero = _make_paper("zero", relevance=0.0, year=2026)
    result = rank_papers([zero, unknown], keywords=["agent"])
    assert result[0].paper_id == "unknown"
