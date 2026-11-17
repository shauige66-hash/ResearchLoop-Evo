"""Export literature matrix to CSV or JSON.

CSV includes a BOM for Excel compatibility with Chinese characters.
JSON preserves all evidence metadata.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Literal

from ..models.paper import EXTRACTED_FIELDS, Paper

ExportFormat = Literal["csv", "json"]

MATRIX_COLUMNS = [
    "paper_id",
    "title",
    "publication_year",
    "venue",
    "doi",
    "source",
    "source_url",
    "is_review",
    "citation_count",
    "evidence_status",
    *EXTRACTED_FIELDS,
]


def _paper_to_row(paper: Paper) -> dict:
    """Convert a Paper to a flat row for export."""
    row: dict = {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "publication_year": paper.publication_year or "",
        "venue": paper.venue or "",
        "doi": paper.doi or "",
        "source": paper.source,
        "source_url": paper.source_url,
        "is_review": paper.is_review,
        "citation_count": paper.citation_count or 0,
        "evidence_status": paper.evidence_status,
    }
    for field in EXTRACTED_FIELDS:
        evidence = getattr(paper, field)
        row[field] = evidence.value or ""
    return row


def export_csv(papers: list[Paper]) -> str:
    """Export papers as CSV with BOM for Excel compatibility."""
    output = io.StringIO()
    # UTF-8 BOM for Excel
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=MATRIX_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for paper in papers:
        writer.writerow(_paper_to_row(paper))
    return output.getvalue()


def export_json(papers: list[Paper]) -> str:
    """Export papers as JSON with full evidence metadata."""
    rows = [_paper_to_row(paper) for paper in papers]
    return json.dumps(rows, indent=2, ensure_ascii=False)


def export_matrix(papers: list[Paper], format: ExportFormat) -> tuple[str, str]:
    """Export papers in the requested format.

    Returns:
        (content, content_type) where content_type is 'text/csv' or 'application/json'.
    """
    if format == "csv":
        return export_csv(papers), "text/csv; charset=utf-8"
    elif format == "json":
        return export_json(papers), "application/json; charset=utf-8"
    else:
        raise ValueError(f"unsupported format: {format}")
