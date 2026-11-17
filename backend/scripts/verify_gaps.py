"""Live P1 verification: search -> matrix -> gap discovery -> counter-evidence -> review.

Writes real responses to backend/var/live_verification/ as evidence.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent.parent / "var" / "live_verification"
OUT.mkdir(parents=True, exist_ok=True)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with OPENER.open(req, timeout=300) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def save(name: str, body) -> None:
    (OUT / name).write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


print("=== 1. real search (all three sources) ===")
status, search = call("POST", "/api/literature/search", {
    "topic": "memory mechanisms for LLM agents",
    "keywords": ["LLM agent memory"],
    "year_from": 2023, "year_to": 2026,
    "sources": ["openalex", "crossref", "arxiv"],
    "top_k": 20, "expand_keywords": False, "refresh": False,
})
print("HTTP", status, "| papers:", len(search.get("papers", [])),
      "| errors:", len(search.get("source_errors", [])))
if status != 200:
    print(json.dumps(search, ensure_ascii=False)[:1200])
    raise SystemExit(1)
save("p1_search.json", search)
run_id = search["run_id"]
ids = [p["paper_id"] for p in search["papers"]]
from collections import Counter
print("method_class:", dict(Counter(p.get("method_class") for p in search["papers"])))
print("new fields grounded:", {
    f: sum(1 for p in search["papers"] if p[f]["evidence_source"] != "none")
    for f in ("agent_architecture", "memory_strategy", "skill_strategy")
})

print("\n=== 2. matrix with new columns + filter ===")
status, matrix = call("POST", "/api/literature/matrix", {"paper_ids": ids[:12]})
print("HTTP", status, "| columns:", len(matrix.get("columns", [])),
      "| rows:", len(matrix.get("rows", [])))
print("column keys:", [c["key"] for c in matrix.get("columns", [])])
print("available_filters:", matrix.get("available_filters"))
save("p1_matrix.json", matrix)

if matrix.get("available_filters", {}).get("method_class"):
    chosen = matrix["available_filters"]["method_class"][0]
    status, filtered = call("POST", "/api/literature/matrix",
                            {"paper_ids": ids[:12], "method_class": chosen})
    print(f"filter method_class={chosen!r} -> HTTP {status}, rows {len(filtered.get('rows', []))}")
    save("p1_matrix_filtered.json", filtered)

print("\n=== 3. gap discovery with real counter-evidence search ===")
started = time.time()
status, gaps = call("POST", "/api/gaps/discover", {
    "run_id": run_id, "run_counter_search": True, "counter_top_k": 10,
})
print(f"HTTP {status} ({time.time() - started:.1f}s) | gaps: {gaps.get('total')}")
if status != 200:
    print(json.dumps(gaps, ensure_ascii=False)[:1500])
    raise SystemExit(1)
save("p1_gaps.json", gaps)

gap_ids = [g["gap_id"] for g in gaps["gaps"]]
assert len(gap_ids) == len(set(gap_ids)), f"gap_id collision: {gap_ids}"
print("unique gap_ids:", len(set(gap_ids)))

for g in gaps["gaps"]:
    print(f"\n  [{g['gap_type']}] {g['confidence_label']} | status={g['status']}")
    print(f"    {g['title']}")
    print(f"    detection_key: {g['detection_key']!r}")
    print(f"    supporting papers: {len(g['supporting_papers'])} | evidence spans: {len(g['supporting_evidence'])}")
    print(f"    counter-evidence: {len(g['counter_evidence'])} | query: {g['counter_search_queries'][0]}")
    for c in g["counter_evidence"]:
        print(f"      - {c['title'][:70]} | cue={c['matched_cue']!r} | {c['source']}")
    print(f"    scope: {g['counter_search_scope']}")
    if g["counter_search_errors"]:
        print(f"    counter-search errors: {g['counter_search_errors']}")
    print(f"    rationale: {g['confidence_rationale']}")
    print(f"    testable_minimally: {g['experimentability']['testable_minimally']}")

print("\n=== 4. human review: accept one, reject one ===")
if gaps["gaps"]:
    gid = gaps["gaps"][0]["gap_id"]
    status, accepted = call("PATCH", f"/api/gaps/{gid}",
                            {"status": "accepted", "human_note": "Reviewed: worth a minimal experiment."})
    print("accept ->", status, accepted.get("status"))
    save("p1_gap_accepted.json", accepted)
if len(gaps["gaps"]) > 1:
    gid2 = gaps["gaps"][1]["gap_id"]
    status, rejected = call("PATCH", f"/api/gaps/{gid2}",
                            {"status": "rejected", "human_note": "Absence-only evidence, too weak."})
    print("reject ->", status, rejected.get("status"))

status, listing = call("GET", "/api/gaps?run_id=" + run_id)
print("\nfinal statuses:", dict(Counter(g["status"] for g in listing.get("gaps", []))))
save("p1_gaps_final.json", listing)
print(f"\nEvidence written to {OUT}")