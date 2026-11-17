"""Pytest fixtures for offline tests."""

from __future__ import annotations

import pytest

from app.models.paper import FieldEvidence, Paper


@pytest.fixture
def sample_paper() -> Paper:
    """A minimal Paper with metadata only."""
    return Paper(
        paper_id="test:paper1",
        title="Test Paper Title",
        authors=["Alice Smith", "Bob Jones"],
        publication_year=2024,
        venue="Test Conference",
        doi="10.1234/test.2024",
        abstract="This paper proposes a novel method for testing. We evaluate on dataset X and achieve 95% accuracy. Results show significant improvement. However, limitations remain.",
        source="openalex",
        source_url="https://openalex.org/test1",
        is_review=False,
        citation_count=10,
        language="en",
        relevance_score=0.8,
        retrieved_at="2024-01-01T00:00:00Z",
    )


@pytest.fixture
def sample_paper_with_extracts(sample_paper: Paper) -> Paper:
    """A Paper with some extracted fields filled."""
    sample_paper.method = FieldEvidence(
        value="We propose a novel testing method",
        evidence_source="abstract",
        evidence_span="We propose a novel testing method",
        confidence="medium",
    )
    sample_paper.findings = FieldEvidence(
        value="Results show significant improvement",
        evidence_source="abstract",
        evidence_span="Results show significant improvement",
        confidence="medium",
    )
    return sample_paper
