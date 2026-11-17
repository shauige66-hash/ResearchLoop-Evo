"""arXiv source adapter.

arXiv is an optional source: it returns Atom XML and is heavily rate-limited.
We parse the XML, extract metadata, and gracefully degrade on 429 errors.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from ...models.schemas import TopicInput
from ..http import HttpFailure, get_client
from .base import RawWorkRecord

BASE_URL = "https://export.arxiv.org/api/query"

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"


def _parse_year_from_date(date_str: str) -> int | None:
    """Extract year from ISO date string like '2024-03-15T12:00:00Z'."""
    if not date_str:
        return None
    try:
        return int(date_str[:4])
    except (ValueError, IndexError):
        return None


def _extract_doi_from_links(links: list[dict[str, str]]) -> str | None:
    """Extract DOI from arXiv link elements."""
    for link in links:
        if link.get("title") == "doi" and "href" in link:
            href = link["href"]
            if "doi.org/" in href:
                return href.split("doi.org/")[-1]
    return None


async def search_arxiv(
    topic: TopicInput, keyword: str, refresh: bool = False
) -> list[RawWorkRecord]:
    """Search arXiv for papers matching the keyword and topic constraints."""
    client = get_client()
    params: dict[str, Any] = {
        "search_query": f'all:"{keyword}"',
        "max_results": topic.top_k,
        "start": 0,
    }

    try:
        outcome = await client.fetch_json(
            BASE_URL,
            params=params,
            source="arxiv",
            timeout=client.settings.arxiv_timeout,
            accept="application/atom+xml",
            refresh=refresh,
            cache_ttl=None,
        )
    except HttpFailure as exc:
        raise

    xml_text = outcome.payload
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise HttpFailure("arxiv", f"failed to parse Atom XML: {exc}", 200, BASE_URL)

    entries = root.findall(f"{{{ATOM_NS}}}entry")
    records: list[RawWorkRecord] = []

    for entry in entries:
        entry_id = entry.findtext(f"{{{ATOM_NS}}}id") or ""
        arxiv_id = entry_id.split("/abs/")[-1] if "/abs/" in entry_id else entry_id

        title = entry.findtext(f"{{{ATOM_NS}}}title") or ""
        title = " ".join(title.split())  # normalize whitespace

        summary = entry.findtext(f"{{{ATOM_NS}}}summary") or ""
        summary = " ".join(summary.split())

        authors = []
        for author in entry.findall(f"{{{ATOM_NS}}}author"):
            name = author.findtext(f"{{{ATOM_NS}}}name")
            if name:
                authors.append(name)

        published = entry.findtext(f"{{{ATOM_NS}}}published") or ""
        year = _parse_year_from_date(published)

        venue = "arXiv"

        # Extract DOI from links
        links = []
        for link in entry.findall(f"{{{ATOM_NS}}}link"):
            links.append(
                {
                    "href": link.get("href", ""),
                    "rel": link.get("rel", ""),
                    "title": link.get("title", ""),
                }
            )
        doi = _extract_doi_from_links(links)

        # arXiv doesn't have document types or review flags
        doc_type = "preprint"
        is_review = False
        review_evidence = None

        # arXiv doesn't provide citation counts
        cited_by = None

        source_url = entry_id
        oa_url = entry_id  # arXiv papers are open access by definition

        # arXiv doesn't provide relevance scores
        relevance = 0.0

        # arXiv doesn't provide language field; assume English
        language = "en"

        records.append(
            RawWorkRecord(
                source="arxiv",
                raw_id=arxiv_id,
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                doi=doi,
                abstract=summary,
                document_type=doc_type,
                is_review=is_review,
                review_evidence=review_evidence,
                citation_count=cited_by,
                language=language,
                relevance_score=relevance,
                source_url=source_url,
                oa_url=oa_url,
                raw={"entry_id": entry_id, "links": links, "published": published},
            )
        )

    return records
