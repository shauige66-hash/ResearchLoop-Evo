"""Deduplicate papers by DOI and title similarity.

Two papers are considered the same if:
1. They share a canonical DOI (exact match after normalization), OR
2. Their titles are highly similar (token Jaccard ≥ 0.85 OR SequenceMatcher ratio ≥ 0.92).

When duplicates are found, we keep the record with the most information and
mark the others with `duplicate_of` pointing to the keeper.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Iterable

from ..config import get_settings
from ..models.paper import Paper
from .normalize import canonical_doi


def _tokenize_title(title: str) -> set[str]:
    """Lowercase and split title into tokens, removing punctuation."""
    title = title.lower()
    tokens = set()
    for word in title.split():
        cleaned = "".join(c for c in word if c.isalnum())
        if cleaned and len(cleaned) > 2:
            tokens.add(cleaned)
    return tokens


def _jaccard_similarity(a: set[str], b: set[str]) -> float:
    """Compute Jaccard similarity between two token sets."""
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union if union > 0 else 0.0


def _title_similarity(a: str, b: str) -> float:
    """Compute title similarity using both Jaccard and SequenceMatcher."""
    tokens_a = _tokenize_title(a)
    tokens_b = _tokenize_title(b)
    jaccard = _jaccard_similarity(tokens_a, tokens_b)
    ratio = SequenceMatcher(None, a.lower(), b.lower()).ratio()
    return max(jaccard, ratio)


def _score_paper(paper: Paper) -> int:
    """Score a paper by how much information it carries (higher = better)."""
    score = 0
    if paper.abstract:
        score += 10
    if paper.doi:
        score += 5
    if paper.venue:
        score += 2
    if paper.authors:
        score += len(paper.authors)
    if paper.citation_count:
        score += min(paper.citation_count, 100)  # cap at 100
    if paper.relevance_score:
        score += int(paper.relevance_score * 10)
    return score


def dedupe(papers: Iterable[Paper]) -> list[Paper]:
    """Remove duplicates and return unique papers.

    Duplicates are identified by DOI or title similarity. The paper with the
    highest information score is kept; others are marked with `duplicate_of`.
    """
    settings = get_settings()
    papers_list = list(papers)
    if not papers_list:
        return []

    # Step 1: DOI dedupe
    doi_groups: dict[str, list[Paper]] = {}
    no_doi: list[Paper] = []
    for paper in papers_list:
        doi = canonical_doi(paper.doi)
        if doi:
            doi_groups.setdefault(doi, []).append(paper)
        else:
            no_doi.append(paper)

    unique_papers: list[Paper] = []
    for doi, group in doi_groups.items():
        group.sort(key=_score_paper, reverse=True)
        keeper = group[0]
        for dup in group[1:]:
            dup.duplicate_of = keeper.paper_id
            keeper.merged_from.append(dup.paper_id)
        unique_papers.append(keeper)

    # Step 2: Title similarity dedupe on remaining (no DOI)
    title_groups: list[list[Paper]] = []
    for paper in no_doi:
        matched = False
        for group in title_groups:
            if _title_similarity(paper.title, group[0].title) >= settings.title_jaccard_threshold:
                group.append(paper)
                matched = True
                break
        if not matched:
            title_groups.append([paper])

    for group in title_groups:
        group.sort(key=_score_paper, reverse=True)
        keeper = group[0]
        for dup in group[1:]:
            dup.duplicate_of = keeper.paper_id
            keeper.merged_from.append(dup.paper_id)
        unique_papers.append(keeper)

    # Also check title similarity across DOI groups (papers with DOI but similar titles)
    # This catches cases where two sources have the same paper but one has a DOI typo
    final: list[Paper] = []
    for paper in unique_papers:
        matched = False
        for existing in final:
            if _title_similarity(paper.title, existing.title) >= settings.title_ratio_threshold:
                # Keep the one with higher score
                if _score_paper(paper) > _score_paper(existing):
                    existing.duplicate_of = paper.paper_id
                    paper.merged_from.append(existing.paper_id)
                    final.remove(existing)
                    final.append(paper)
                else:
                    paper.duplicate_of = existing.paper_id
                    existing.merged_from.append(paper.paper_id)
                matched = True
                break
        if not matched:
            final.append(paper)

    return final
