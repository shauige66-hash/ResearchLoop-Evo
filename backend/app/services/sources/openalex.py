"""OpenAlex source adapter.

OpenAlex is the primary source: it returns metadata, abstracts (as inverted
indexes), citation counts, and relevance scores in one call.
"""

from __future__ import annotations

from typing import Any

from ...models.schemas import TopicInput
from ..http import HttpFailure, get_client
from .base import RawWorkRecord

BASE_URL = "https://api.openalex.org/works"


def _reconstruct_abstract(inverted_index: dict[str, list[int]]) -> str | None:
    """Reconstruct abstract from OpenAlex's inverted index format."""
    if not inverted_index:
        return None
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(word for _, word in word_positions)


def _build_filters(topic: TopicInput) -> str:
    """Build OpenAlex filter string from topic constraints."""
    filters: list[str] = []
    if topic.year_from and topic.year_to:
        filters.append(f"publication_year:{topic.year_from}-{topic.year_to}")
    elif topic.year_from:
        filters.append(f"publication_year:>{topic.year_from - 1}")
    elif topic.year_to:
        filters.append(f"publication_year:<{topic.year_to + 1}")
    if topic.document_types:
        type_map = {
            "article": "article",
            "review": "review",
            "conference-paper": "conference-paper",
            "book-chapter": "book-chapter",
            "preprint": "preprint",
            "dissertation": "dissertation",
            "report": "report",
        }
        types = [type_map.get(dt, dt) for dt in topic.document_types]
        filters.append("type:" + "|".join(types))
    return ",".join(filters)


async def search_openalex(
    topic: TopicInput, keyword: str, refresh: bool = False
) -> list[RawWorkRecord]:
    """Search OpenAlex for papers matching the keyword and topic constraints."""
    client = get_client()
    params: dict[str, Any] = {
        "search": keyword,
        "per-page": topic.top_k,
    }
    if client.settings.mailto:
        params["mailto"] = client.settings.mailto
    filters = _build_filters(topic)
    if filters:
        params["filter"] = filters

    try:
        outcome = await client.fetch_json(
            BASE_URL,
            params=params,
            source="openalex",
            timeout=client.settings.request_timeout,
            refresh=refresh,
            cache_ttl=None,
        )
    except HttpFailure as exc:
        raise

    data = outcome.payload
    results = data.get("results", [])
    records: list[RawWorkRecord] = []

    for item in results:
        doi = item.get("doi")
        if doi and doi.startswith("https://doi.org/"):
            doi = doi[len("https://doi.org/") :]
        elif doi and doi.startswith("http://doi.org/"):
            doi = doi[len("http://doi.org/") :]

        authors = []
        for authorship in item.get("authorships", []):
            name = authorship.get("author", {}).get("display_name")
            if name:
                authors.append(name)

        venue = None
        primary_loc = item.get("primary_location") or {}
        source_info = primary_loc.get("source") or {}
        venue = source_info.get("display_name")

        abstract = _reconstruct_abstract(item.get("abstract_inverted_index") or {})

        doc_type = item.get("type")
        is_review = doc_type == "review"
        review_evidence = "type=review" if is_review else None

        cited_by = item.get("cited_by_count")

        source_url = item.get("ids", {}).get("openalex") or ""
        oa_url = item.get("open_access", {}).get("oa_url")

        relevance = item.get("relevance_score")
        try:
            relevance = float(relevance)
        except (TypeError, ValueError):
            relevance = 0.0

        records.append(
            RawWorkRecord(
                source="openalex",
                raw_id=item.get("id") or "",
                title=item.get("display_name") or "",
                authors=authors,
                year=item.get("publication_year"),
                venue=venue,
                doi=doi,
                abstract=abstract,
                document_type=doc_type,
                is_review=is_review,
                review_evidence=review_evidence,
                citation_count=cited_by,
                language=item.get("language"),
                relevance_score=relevance,
                source_url=source_url,
                oa_url=oa_url,
                raw=item,
            )
        )

    return records
