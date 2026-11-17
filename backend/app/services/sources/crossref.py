"""Crossref source adapter.

Crossref is a secondary source: it provides DOI metadata and sometimes abstracts.
We use it to fill gaps and verify DOIs from OpenAlex.
"""

from __future__ import annotations

from typing import Any

from ...models.schemas import TopicInput
from ..http import HttpFailure, get_client
from .base import RawWorkRecord

BASE_URL = "https://api.crossref.org/works"


def _extract_author_name(author: dict[str, Any]) -> str:
    given = author.get("given", "")
    family = author.get("family", "")
    if given and family:
        return f"{given} {family}"
    return family or given or ""


def _extract_year(issued: dict[str, Any]) -> int | None:
    date_parts = issued.get("date-parts", [[]])
    if date_parts and date_parts[0] and len(date_parts[0]) > 0:
        try:
            return int(date_parts[0][0])
        except (TypeError, ValueError):
            return None
    return None


async def search_crossref(
    topic: TopicInput, keyword: str, refresh: bool = False
) -> list[RawWorkRecord]:
    """Search Crossref for papers matching the keyword and topic constraints."""
    client = get_client()
    params: dict[str, Any] = {
        "query.bibliographic": keyword,
        "rows": topic.top_k,
    }
    if client.settings.mailto:
        params["mailto"] = client.settings.mailto

    # Crossref select fields to reduce payload. "language" is not a valid select
    # on /works and makes the whole query fail with HTTP 400.
    select_fields = [
        "DOI",
        "title",
        "author",
        "issued",
        "container-title",
        "type",
        "URL",
        "abstract",
        "is-referenced-by-count",
    ]
    params["select"] = ",".join(select_fields)

    # Filters
    filters: list[str] = []
    if topic.year_from:
        filters.append(f"from-pub-date:{topic.year_from}")
    if topic.year_to:
        filters.append(f"until-pub-date:{topic.year_to}")
    if topic.document_types:
        type_map = {
            "article": "journal-article",
            "review": "journal-article",  # Crossref doesn't distinguish review well
            "conference-paper": "proceedings-article",
            "book-chapter": "book-chapter",
            "dissertation": "dissertation",
            "report": "report",
        }
        cr_types = [type_map.get(dt, dt) for dt in topic.document_types]
        filters.append("type:" + ",".join(cr_types))

    if filters:
        params["filter"] = ",".join(filters)

    try:
        outcome = await client.fetch_json(
            BASE_URL,
            params=params,
            source="crossref",
            timeout=client.settings.request_timeout,
            refresh=refresh,
            cache_ttl=None,
        )
    except HttpFailure as exc:
        raise

    data = outcome.payload
    message = data.get("message", {})
    items = message.get("items", [])
    records: list[RawWorkRecord] = []

    for item in items:
        doi = item.get("DOI", "")
        title_list = item.get("title", [])
        title = title_list[0] if title_list else ""

        authors = [_extract_author_name(a) for a in item.get("author", [])]
        authors = [a for a in authors if a]

        year = _extract_year(item.get("issued", {}))

        venue_list = item.get("container-title", [])
        venue = venue_list[0] if venue_list else None

        abstract = item.get("abstract")
        doc_type = item.get("type")

        # Crossref doesn't have a clear "review" type; we'll mark as False
        is_review = False
        review_evidence = None

        cited_by = item.get("is-referenced-by-count")

        source_url = item.get("URL", "")
        oa_url = None  # Crossref doesn't provide OA URL directly

        # Crossref does not report a relevance score for /works queries.
        relevance = None

        language = item.get("language")

        records.append(
            RawWorkRecord(
                source="crossref",
                raw_id=doi,
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                doi=doi,
                abstract=abstract,
                document_type=doc_type,
                is_review=is_review,
                review_evidence=review_evidence,
                citation_count=cited_by,
                language=language,
                relevance_score=relevance,
                source_url=source_url,
                oa_url=oa_url,
                raw=item,
            )
        )

    return records
