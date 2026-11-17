"""Live endpoint verification: each source separately, then jointly.

Writes real responses to backend/var/live_verification/ as evidence.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent.parent / "var" / "live_verification"
OUT.mkdir(parents=True, exist_ok=True)

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def post(path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with OPENER.open(req, timeout=180) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def summarize(label: str, body: dict) -> dict:
    papers = body.get("papers", [])
    errors = body.get("source_errors", [])
    per_source: dict[str, int] = {}
    with_abstract = 0
    with_doi = 0
    for p in papers:
        per_source[p.get("source", "?")] = per_source.get(p.get("source", "?"), 0) + 1
        if p.get("abstract"):
            with_abstract += 1
        if p.get("doi"):
            with_doi += 1
    row = {
        "label": label,
        "run_id": body.get("run_id"),
        "paper_count": len(papers),
        "per_source": per_source,
        "with_abstract": with_abstract,
        "with_doi": with_doi,
        "requests_made": body.get("meta", {}).get("requests_made"),
        "cache_hits": body.get("meta", {}).get("cache_hits"),
        "duration_ms": body.get("meta", {}).get("duration_ms"),
        "sources_failed": body.get("meta", {}).get("sources_failed"),
        "errors": [
            {"source": e.get("source"), "status": e.get("status"), "detail": e.get("detail")}
            for e in errors
        ],
        "sample_titles": [p.get("title") for p in papers[:3]],
    }
    print(json.dumps(row, ensure_ascii=False, indent=2))
    return row


TOPIC = "memory mechanisms for LLM agents"
COMMON = {
    "topic": TOPIC,
    "keywords": ["LLM agent memory"],
    "year_from": 2023,
    "year_to": 2026,
    "top_k": 15,
    "expand_keywords": False,
    "refresh": True,
}

results = []
for source in ("openalex", "crossref", "arxiv"):
    payload = dict(COMMON, sources=[source])
    started = time.time()
    status, body = post("/api/literature/search", payload)
    print(f"\n=== {source} HTTP {status} ({time.time() - started:.1f}s) ===")
    if status != 200:
        print(json.dumps(body, ensure_ascii=False)[:1500])
        results.append({"label": source, "http_status": status, "error": body})
        continue
    (OUT / f"{source}.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    results.append(summarize(source, body))
    time.sleep(4)  # be polite to arXiv between rounds

print(f"\n=== joint (all three) ===")
status, body = post("/api/literature/search", dict(COMMON, sources=["openalex", "crossref", "arxiv"]))
print(f"HTTP {status}")
if status == 200:
    (OUT / "joint.json").write_text(
        json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    results.append(summarize("joint", body))
else:
    print(json.dumps(body, ensure_ascii=False)[:1500])
    results.append({"label": "joint", "http_status": status, "error": body})

(OUT / "summary.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"\nEvidence written to {OUT}")