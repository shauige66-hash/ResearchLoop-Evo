"""Generate a 7-section literature research report with evidence separation.

The report separates three kinds of content:
- facts: directly observable from paper metadata/abstracts
- author_claims: statements made by paper authors (with citations)
- system_inference: deductions made by the system (with uncertainty notes)

This ensures readers can distinguish what was found from what was concluded.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Literal

from ..models.paper import EXTRACTED_FIELDS, Paper
from ..models.schemas import ReportResponse, ReportSection


def _group_by_field(papers: list[Paper], field: str) -> list[tuple[str, list[Paper]]]:
    """Group papers by a field value (e.g., venue, document_type)."""
    groups: dict[str, list[Paper]] = {}
    for paper in papers:
        value = getattr(paper, field, None)
        if value:
            groups.setdefault(str(value), []).append(paper)
    return sorted(groups.items(), key=lambda x: len(x[1]), reverse=True)


def _format_citations(paper_ids: list[str]) -> str:
    """Format paper IDs as citations."""
    if not paper_ids:
        return ""
    return ", ".join(f"[{pid}]" for pid in paper_ids[:5])


def _section_overview(papers: list[Paper], topic: str) -> ReportSection:
    """Section 1: Topic overview with basic statistics."""
    total = len(papers)
    reviews = sum(1 for p in papers if p.is_review)
    years = [p.publication_year for p in papers if p.publication_year]
    year_range = f"{min(years)}–{max(years)}" if years else "unknown"

    paragraphs = [
        f"This report covers {total} papers related to '{topic}', spanning {year_range}.",
        f"Among them, {reviews} are review papers ({reviews/total*100:.1f}% if total else 0).",
        f"The papers come from {len(set(p.source for p in papers))} sources: {', '.join(sorted(set(p.source for p in papers)))}.",
    ]

    return ReportSection(
        id="overview",
        title="1. 研究主题概览 / Topic Overview",
        kind="facts",
        paragraphs=paragraphs,
        paper_ids=[p.paper_id for p in papers[:5]],
    )


def _section_categories(papers: list[Paper]) -> ReportSection:
    """Section 2: Related research categories by venue/type."""
    venue_groups = _group_by_field(papers, "venue")
    type_groups = _group_by_field(papers, "document_type")

    paragraphs = []
    if venue_groups:
        top_venues = venue_groups[:5]
        paragraphs.append(f"Top venues: {', '.join(f'{v} ({n})' for v, (_, n) in zip([g[0] for g in top_venues], top_venues))}.")

    if type_groups:
        paragraphs.append(f"Document types: {', '.join(f'{t} ({n})' for t, (_, n) in zip([g[0] for g in type_groups], type_groups))}.")

    if not paragraphs:
        paragraphs.append("No clear categorization available from metadata.")

    return ReportSection(
        id="categories",
        title="2. 相关研究分类 / Related Research Categories",
        kind="facts",
        paragraphs=paragraphs,
        paper_ids=[p.paper_id for p in papers[:10]],
    )


def _section_representative(papers: list[Paper]) -> ReportSection:
    """Section 3: Representative papers (top 5 by relevance/citations)."""
    # Sort by citation count (desc), then relevance (desc)
    sorted_papers = sorted(papers, key=lambda p: (p.citation_count or 0, p.relevance_score), reverse=True)
    top5 = sorted_papers[:5]

    paragraphs = []
    for paper in top5:
        authors = ", ".join(paper.authors[:3])
        if len(paper.authors) > 3:
            authors += " et al."
        year = paper.publication_year or "n.d."
        venue = paper.venue or "unknown venue"
        paragraphs.append(f"**{paper.title}** by {authors} ({year}, {venue}).")

    return ReportSection(
        id="representative",
        title="3. 代表性论文 / Representative Papers",
        kind="facts",
        paragraphs=paragraphs,
        paper_ids=[p.paper_id for p in top5],
    )


def _section_methods(papers: list[Paper]) -> ReportSection:
    """Section 4: Method comparison."""
    method_papers = [p for p in papers if p.method.is_known]
    if not method_papers:
        return ReportSection(
            id="methods",
            title="4. 方法比较 / Method Comparison",
            kind="facts",
            paragraphs=["No method information extracted from abstracts."],
            paper_ids=[],
        )

    # Group by method keywords (simple: first 5 words of method value)
    method_groups: dict[str, list[Paper]] = {}
    for paper in method_papers:
        method_text = paper.method.value or ""
        key = " ".join(method_text.split()[:5]) if method_text else "unknown"
        method_groups.setdefault(key, []).append(paper)

    paragraphs = []
    for method, group in sorted(method_groups.items(), key=lambda x: len(x[1]), reverse=True)[:5]:
        paragraphs.append(f"**{method}**: {len(group)} paper(s) {_format_citations([p.paper_id for p in group[:3]])}.")

    return ReportSection(
        id="methods",
        title="4. 方法比较 / Method Comparison",
        kind="facts",
        paragraphs=paragraphs,
        paper_ids=[p.paper_id for p in method_papers[:10]],
    )


def _section_conclusions(papers: list[Paper]) -> ReportSection:
    """Section 5: Existing conclusions from papers."""
    findings_papers = [p for p in papers if p.findings.is_known]
    if not findings_papers:
        return ReportSection(
            id="conclusions",
            title="5. 已有结论 / Existing Conclusions",
            kind="author_claims",
            paragraphs=["No findings extracted from abstracts."],
            paper_ids=[],
        )

    paragraphs = []
    for paper in findings_papers[:5]:
        findings_text = paper.findings.value or ""
        paragraphs.append(f"{paper.title} {_format_citations([paper.paper_id])}: {findings_text[:200]}...")

    return ReportSection(
        id="conclusions",
        title="5. 已有结论 / Existing Conclusions",
        kind="author_claims",
        paragraphs=paragraphs,
        paper_ids=[p.paper_id for p in findings_papers[:5]],
    )


def _section_limitations(papers: list[Paper]) -> ReportSection:
    """Section 6: Known limitations from papers."""
    limit_papers = [p for p in papers if p.limitations.is_known]
    if not limit_papers:
        return ReportSection(
            id="limitations",
            title="6. 已知局限 / Known Limitations",
            kind="author_claims",
            paragraphs=["No limitations extracted from abstracts."],
            paper_ids=[],
        )

    paragraphs = []
    for paper in limit_papers[:5]:
        limit_text = paper.limitations.value or ""
        paragraphs.append(f"{paper.title} {_format_citations([paper.paper_id])}: {limit_text[:200]}...")

    return ReportSection(
        id="limitations",
        title="6. 已知局限 / Known Limitations",
        kind="author_claims",
        paragraphs=paragraphs,
        paper_ids=[p.paper_id for p in limit_papers[:5]],
    )


def _section_open_questions(papers: list[Paper]) -> ReportSection:
    """Section 7: Open questions (system inference with uncertainty)."""
    future_papers = [p for p in papers if p.future_work.is_known]
    if not future_papers:
        return ReportSection(
            id="open_questions",
            title="7. 尚待验证问题 / Open Questions",
            kind="system_inference",
            paragraphs=["No future work extracted. This section requires manual review."],
            paper_ids=[],
        )

    paragraphs = [
        "The following open questions are inferred from future work sections. **These are system deductions, not verified conclusions.**",
    ]
    for paper in future_papers[:5]:
        future_text = paper.future_work.value or ""
        paragraphs.append(f"{paper.title} {_format_citations([paper.paper_id])}: {future_text[:200]}...")

    return ReportSection(
        id="open_questions",
        title="7. 尚待验证问题 / Open Questions",
        kind="system_inference",
        paragraphs=paragraphs,
        paper_ids=[p.paper_id for p in future_papers[:5]],
    )


def generate_report(papers: list[Paper], topic: str) -> ReportResponse:
    """Generate a 7-section literature research report.

    Each section is tagged with its content kind (facts/author_claims/system_inference).
    """
    sections = [
        _section_overview(papers, topic),
        _section_categories(papers),
        _section_representative(papers),
        _section_methods(papers),
        _section_conclusions(papers),
        _section_limitations(papers),
        _section_open_questions(papers),
    ]

    # Build markdown
    md_lines = [f"# Literature Research Report: {topic}\n"]
    md_lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}\n")
    md_lines.append(f"Paper count: {len(papers)}\n")
    md_lines.append("---\n")

    for section in sections:
        md_lines.append(f"## {section.title}\n")
        md_lines.append(f"**Content type: {section.kind}**\n")
        for para in section.paragraphs:
            md_lines.append(f"{para}\n")
        md_lines.append("\n")

    markdown = "\n".join(md_lines)

    # Caveats
    caveats = [
        "Phase 1 extracts from metadata and abstracts only. No full text was read.",
        "Fields marked 'unknown' were not found in retrieved material.",
        "System inferences (Section 7) are deductions, not verified conclusions.",
        "Author claims (Sections 5-6) are quoted from abstracts, not independently verified.",
    ]

    return ReportResponse(
        report_id=f"report_{int(time.time() * 1000)}",
        topic=topic,
        generated_at=datetime.now(timezone.utc).isoformat(),
        paper_count=len(papers),
        sections=sections,
        markdown=markdown,
        caveats=caveats,
    )
