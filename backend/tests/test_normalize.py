"""Tests for normalize.py — DOI normalization and record normalization."""

from app.services.normalize import canonical_doi, normalize_record
from app.services.sources.base import RawWorkRecord


def test_canonical_doi_strips_https():
    assert canonical_doi("https://doi.org/10.1234/test") == "10.1234/test"


def test_canonical_doi_strips_http():
    assert canonical_doi("http://doi.org/10.1234/test") == "10.1234/test"


def test_canonical_doi_strips_prefix():
    assert canonical_doi("doi:10.1234/test") == "10.1234/test"


def test_canonical_doi_lowercases():
    assert canonical_doi("10.1234/TEST") == "10.1234/test"


def test_canonical_doi_handles_none():
    assert canonical_doi(None) is None


def test_canonical_doi_handles_empty():
    assert canonical_doi("") is None


def test_normalize_record_basic():
    record = RawWorkRecord(
        source="openalex",
        raw_id="W123",
        title="Test Paper",
        authors=["Alice"],
        year=2024,
        doi="https://doi.org/10.1234/test",
        source_url="https://openalex.org/W123",
    )
    paper = normalize_record(record, run_id="run_1")
    assert paper.paper_id == "openalex:W123"
    assert paper.doi == "10.1234/test"
    assert paper.run_id == "run_1"
    assert paper.title == "Test Paper"


def test_normalize_record_preserves_provenance():
    record = RawWorkRecord(
        source="crossref",
        raw_id="10.5678/xyz",
        title="Another Paper",
        source_url="https://doi.org/10.5678/xyz",
    )
    paper = normalize_record(record)
    assert paper.source == "crossref"
    assert paper.source_url == "https://doi.org/10.5678/xyz"
    assert paper.evidence_status == "metadata_only"
