"""Rank papers by relevance, recency, citations, and review status.

The scoring formula combines multiple signals:
- Source relevance score (from OpenAlex)
- Keyword overlap (how many search keywords appear in title/abstract)
- Year recency (newer papers score higher)
- Citation count (normalized to 0-1 range)
- Review bonus (review papers get a boost if prefer_reviews=True)
"""

from __future__ import annotations

from typing import Iterable

from ..models.paper import Paper


def _normalize_citations(count: int | None) -> float:
    """Normalize citation count to 0-1 range using log scale."""
    if count is None or count < 0:
        return 0.0
    if count == 0:
        return 0.0
    # log scale: 1→0.0, 10→0.5, 100→0.75, 1000→1.0
    import math
    return min(1.0, math.log10(count + 1) / 3.0)


def _year_recency(year: int | None, current_year: int = 2026) -> float:
    """Score year recency: newer papers get higher scores."""
    if year is None:
        return 0.5  # unknown year gets middle score
    age = current_year - year
    if age < 0:
        return 1.0  # future year (shouldn't happen but handle gracefully)
    if age > 20:
        return 0.0  # very old
    return 1.0 - (age / 20.0)


def _keyword_overlap(paper: Paper, keywords: list[str]) -> float:
    """Compute fraction of keywords that appear in title or abstract."""
    if not keywords:
        return 0.0
    text = (paper.title + " " + (paper.abstract or "")).lower()
    matches = sum(1 for kw in keywords if kw.lower() in text)
    return matches / len(keywords)


def rank_papers(
    papers: Iterable[Paper],
    keywords: list[str],
    prefer_reviews: bool = False,
    weights: dict[str, float] | None = None,
) -> list[Paper]:
    """Sort papers by composite relevance score.

    Args:
        papers: Iterable of Paper objects to rank.
        keywords: Search keywords for overlap scoring.
        prefer_reviews: If True, review papers get a bonus.
        weights: Optional dict of weight names to values. Defaults:
            {"relevance": 0.3, "keyword_overlap": 0.2, "year": 0.15,
             "citations": 0.2, "review_bonus": 0.15}

    Returns:
        List of papers sorted by score (highest first).
    """
    if weights is None:
        weights = {
            "relevance": 0.3,
            "keyword_overlap": 0.2,
            "year": 0.15,
            "citations": 0.2,
            "review_bonus": 0.15,
        }

    papers_list = list(papers)
    scored: list[tuple[float, Paper]] = []

    for paper in papers_list:
        relevance = min(1.0, paper.relevance_score / 10.0) if paper.relevance_score else 0.0
        keyword_score = _keyword_overlap(paper, keywords)
        year_score = _year_recency(paper.publication_year)
        citation_score = _normalize_citations(paper.citation_count)
        review_score = 1.0 if (prefer_reviews and paper.is_review) else 0.0

        total = (
            weights["relevance"] * relevance
            + weights["keyword_overlap"] * keyword_score
            + weights["year"] * year_score
            + weights["citations"] * citation_score
            + weights["review_bonus"] * review_score
        )

        scored.append((total, paper))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [paper for _, paper in scored]
