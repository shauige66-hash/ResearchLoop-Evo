"""Benchmark construction: real DOI verification and leakage-free topic splits.

A reference DOI is only usable after two separate steps:
1. metadata verification against Crossref or OpenAlex (the paper exists);
2. human confirmation that it belongs to this case's reference set.

Step 1 alone never produces ground truth. Splits are assigned per topic, so every
case about the same topic lands in the same split and a candidate cannot be tuned
on validation material and then scored on it as if it were unseen.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from ..models.experiment import BenchmarkCase, BenchmarkReference, Split
from ..services.http import HttpFailure, get_client
from .evaluator import normalize_doi

CROSSREF_WORK = "https://api.crossref.org/works/"
OPENALEX_WORK = "https://api.openalex.org/works/doi:"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def verify_doi(doi: str) -> BenchmarkReference:
    """Check that a DOI resolves to a real work. Raises HttpFailure if neither knows it."""
    clean = normalize_doi(doi)
    if not clean:
        raise ValueError("empty DOI")
    client = get_client()
    errors: list[str] = []

    try:
        outcome = await client.fetch_json(
            CROSSREF_WORK + clean, source="crossref", cache_ttl=None
        )
        message = outcome.payload.get("message", {})
        titles = message.get("title") or []
        return BenchmarkReference(
            doi=clean,
            title=titles[0] if titles else "",
            source_url=message.get("URL") or f"https://doi.org/{clean}",
            verified_via="crossref",
            verified_at=_now(),
        )
    except HttpFailure as exc:
        errors.append(f"crossref: {exc.status} {exc.detail}")
    except Exception as exc:
        errors.append(f"crossref: {type(exc).__name__}: {exc}")

    try:
        outcome = await client.fetch_json(
            OPENALEX_WORK + clean, source="openalex", cache_ttl=None
        )
        payload = outcome.payload
        return BenchmarkReference(
            doi=clean,
            title=payload.get("title") or "",
            source_url=payload.get("id") or f"https://doi.org/{clean}",
            verified_via="openalex",
            verified_at=_now(),
        )
    except HttpFailure as exc:
        errors.append(f"openalex: {exc.status} {exc.detail}")
    except Exception as exc:
        errors.append(f"openalex: {type(exc).__name__}: {exc}")

    raise HttpFailure(
        status=None,
        detail="DOI could not be verified by Crossref or OpenAlex — " + "; ".join(errors),
        source="benchmark",
    )


def _bucket_sizes(n: int) -> dict[str, int]:
    """Target a 50/30/20 topic split, guaranteeing all three buckets when n >= 3."""
    if n < 3:
        return {"development": n, "validation": 0, "holdout": 0}
    development = max(1, round(n * 0.5))
    validation = max(1, round(n * 0.3))
    holdout = max(1, n - development - validation)
    development += n - (development + validation + holdout)
    return {"development": development, "validation": validation, "holdout": holdout}


def assign_splits(cases: list[BenchmarkCase]) -> list[BenchmarkCase]:
    """Group by topic, then place whole topics into development/validation/holdout.

    Deterministic: topics are ordered by their own hash, so the same set of topics
    always lands in the same buckets and re-running cannot silently move validation
    material into development.
    """
    topics = sorted(
        {c.topic.strip().lower() for c in cases},
        key=lambda t: hashlib.sha256(t.encode("utf-8")).hexdigest(),
    )
    sizes = _bucket_sizes(len(topics))
    buckets: dict[str, Split] = {}
    cursor = 0
    for split, size in sizes.items():
        for topic in topics[cursor : cursor + size]:
            buckets[topic] = split  # type: ignore[assignment]
        cursor += size
    for case in cases:
        case.split = buckets[case.topic.strip().lower()]
    return cases


def case_payload(case: BenchmarkCase) -> dict:
    return {
        "case_id": case.case_id,
        "topic": case.topic,
        "query": case.query,
        "split": case.split,
    }