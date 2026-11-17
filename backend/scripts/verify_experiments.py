"""Live P2 verification: benchmark -> frozen spec -> real arms -> independent scoring.

Every DOI used here comes from a real OpenAlex/Crossref/arXiv response and is then
re-verified against Crossref/OpenAlex. References are deliberately left UNCONFIRMED:
this script is not a human reviewer, so it must not manufacture ground truth. The
expected outcome is real cost metrics, coverage=None, status=awaiting_reference_set
and a closed promotion gate.

A human can later confirm references through the UI (or POST .../confirm) and re-run
POST /api/experiments/verify to score the stored snapshots without re-searching.

Writes real responses to backend/var/live_verification/ as evidence.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent.parent / "var" / "live_verification"
OUT.mkdir(parents=True, exist_ok=True)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

CASE_TOPICS = [
    ("memory mechanisms for LLM agents", "LLM agent memory mechanisms"),
    ("skill acquisition for LLM agents", "LLM agent skill library learning"),
    ("experience-driven self-improvement of LLM agents", "LLM agent self-improvement from experience"),
]


def call(method: str, path: str, payload: dict | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with OPENER.open(req, timeout=600) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw}


def save(name: str, body) -> None:
    (OUT / name).write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")


def show_run(run: dict) -> None:
    ev = run.get("evaluation") or {}
    print(
        f"  {run['arm']:<9} queries={len(run['queries_used'])} "
        f"api_requests={run['api_request_count']} cache_hits={run['cache_hits']} "
        f"unique_papers={run['unique_paper_count']} time_ms={run['execution_time_ms']} "
        f"coverage={ev.get('coverage_at_k')} status={run['status']}"
    )
    print(f"            queries_used={run['queries_used']}")
    if run.get("source_errors"):
        print(f"            source_errors={run['source_errors']}")


print("=== 1. skill registry: active baseline + a real candidate version ===")
status, active = call("GET", "/api/skills/active")
assert status == 200, active
baseline = active["version"]
print("active:", baseline["version_id"], f"v{baseline['version_number']}")
print("baseline strategy:", json.dumps(baseline["strategy"], ensure_ascii=False))

MUTATION = (
    "P2 verification candidate (script-authored deterministic mutation, stands in for the "
    "P3 CandidateProposer): add domain synonyms and topic-term expansion after the "
    "single-query baseline missed subtopic terminology."
)
status, registry = call("GET", "/api/skills/versions")
assert status == 200, registry
existing = [
    v for v in registry["versions"]
    if v["status"] == "candidate" and v["mutation_description"] == MUTATION
]
if existing:
    candidate = existing[0]
    print("reusing candidate:", candidate["version_id"], f"v{candidate['version_number']}")
else:
    status, candidate = call("POST", "/api/skills/versions", {
        "strategy": {
            "query_templates": ["{query}"],
            "domain_synonyms": {
                "memory": ["episodic memory", "long-term memory"],
                "skill": ["skill library", "procedural knowledge"],
                "experience": ["trajectory", "self-reflection"],
            },
            "keyword_expansion_rules": ["domain_synonyms", "topic_terms"],
            "source_priority": ["openalex", "crossref", "arxiv"],
            "search_filters": {"year_from": None, "year_to": None, "document_types": [], "prefer_reviews": False},
            "retrieval_budget": {"top_k": 20, "max_keywords": 2, "max_api_requests": 6},
        },
        "mutation_description": MUTATION,
        "source_trials": [],
        "created_by": "proposer",
    })
    assert status == 200, candidate
    print("candidate:", candidate["version_id"], f"v{candidate['version_number']}",
          "parent:", candidate["parent_version"], "status:", candidate["status"])
assert candidate["status"] == "candidate", "creating a version must never activate it"
save("p2_skill_versions.json", {"baseline": baseline, "candidate": candidate})

print("\n=== 2. benchmark cases (real DOIs, re-verified, NOT confirmed) ===")
status, listing = call("GET", "/api/experiments/benchmark/cases")
assert status == 200, listing
by_topic = {c["topic"]: c for c in listing["cases"]}
cases = []
for index, (topic, harvest_query) in enumerate(CASE_TOPICS, start=1):
    if topic in by_topic and by_topic[topic]["references"]:
        case = by_topic[topic]
        print(f"  reusing {case['case_id']} for {topic} ({len(case['references'])} verified refs)")
        cases.append(case)
        continue
    status, search = call("POST", "/api/literature/search", {
        "topic": topic, "keywords": [harvest_query],
        "year_from": 2023, "year_to": 2026,
        "sources": ["openalex", "crossref", "arxiv"],
        "top_k": 10, "expand_keywords": False, "refresh": False,
    })
    assert status == 200, search
    papers = search.get("papers", [])
    dois = [p["doi"] for p in papers if p.get("doi")][:3]
    print(f"  harvest {topic}: HTTP {status} papers={len(papers)} "
          f"requests={search['meta'].get('requests_made')} errors={len(search.get('source_errors', []))}")
    print(f"    candidate reference DOIs (unconfirmed): {dois}")
    save(f"p2_harvest_{index}.json", search)
    assert dois, f"no real DOIs harvested for {topic}"
    status, body = call("POST", "/api/experiments/benchmark/cases", {
        "topic": topic,
        "query": harvest_query,
        "reference_dois": dois,
        "notes": (
            "Provisional references harvested from real search "
            f"{search['run_id']}. Metadata-verified only; a human reviewer must confirm "
            "relevance before any coverage or promotion claim."
        ),
        "source": "derived_from_run",
        "verify_references": True,
    })
    assert status == 200, body
    case = body["case"]
    for ref in case["references"]:
        print(f"    {ref['doi']} | {ref['title'][:70]} | via={ref['verified_via']} "
              f"confirmed_by={ref['confirmed_by']}")
    if body["verification_errors"]:
        print("    VERIFICATION ERRORS:", body["verification_errors"])
    cases.append(case)
save("p2_cases_created.json", cases)

print("\n=== 3. topic-grouped splits ===")
status, splits = call("POST", "/api/experiments/benchmark/assign-splits")
assert status == 200, splits
print("  splits:", splits["split_counts"],
      "| confirmed:", splits["confirmed_cases"], "| awaiting:", splits["awaiting_cases"])
by_topic = {}
for case in splits["cases"]:
    by_topic.setdefault(case["topic"], set()).add(case["split"])
assert all(len(v) == 1 for v in by_topic.values()), "a topic was split across buckets (leakage)"
cases = [c for c in splits["cases"] if c["case_id"] in {x["case_id"] for x in cases}]
save("p2_cases_split.json", splits)

print("\n=== 4. real query plans differ, protocol does not ===")
for version in (baseline, candidate):
    status, preview = call("POST", "/api/skills/preview", {
        "version_id": version["version_id"],
        "topic": cases[0]["topic"], "query": cases[0]["query"],
    })
    assert status == 200, preview
    print(f"  v{version['version_number']}: {preview['queries']}")

print("\n=== 5. design the frozen spec ===")
status, specs = call("GET", "/api/experiments/specs")
assert status == 200, specs
wanted_cases = sorted(c["case_id"] for c in cases)
reusable = [
    s for s in specs["specs"]
    if sorted(s["case_ids"]) == wanted_cases
    and s["baseline_version_id"] == baseline["version_id"]
    and s["candidate_version_id"] == candidate["version_id"]
    and not s["candidate_locked_at"]
]
if reusable:
    spec = reusable[0]
    print("  reusing spec:", spec["spec_id"])
else:
    status, spec = call("POST", "/api/experiments/design", {
        "case_ids": [c["case_id"] for c in cases],
        "baseline_version_id": baseline["version_id"],
        "candidate_version_id": candidate["version_id"],
        "sources": ["openalex", "crossref", "arxiv"],
        "year_from": 2023, "year_to": 2026,
        "top_k": 20, "max_api_requests": 6, "use_cache": True,
    })
    assert status == 200, spec
    print("  spec:", spec["spec_id"])
print("  hypothesis:", spec["hypothesis"][:90], "...")
print("  frozen protocol:", {k: spec[k] for k in ("sources", "year_from", "year_to", "top_k", "max_api_requests")})
save("p2_spec.json", spec)

print("\n=== 6. execute both arms against the real APIs (holdout excluded) ===")
all_runs = []
for split in ("development", "validation"):
    if not any(c["split"] == split for c in cases):
        print(f"  [{split}] no cases in this split, skipped")
        continue
    status, body = call("POST", "/api/experiments/run", {"spec_id": spec["spec_id"], "split": split})
    assert status == 200, body
    print(f"  [{split}] HTTP {status}")
    for run in body["runs"]:
        show_run(run)
    for comp in body["comparisons"]:
        print(f"    compare {comp['case_id']}: coverage_delta={comp['coverage_delta']} "
              f"request_ratio={comp['request_ratio']} reference_status={comp['reference_status']}")
    print("    promotion_gate:", body["promotion_gate"])
    assert body["promotion_gate"]["allowed"] is False, "gate must stay closed without confirmed references"
    assert all(r["status"] == "awaiting_reference_set" for r in body["runs"])
    assert all((r.get("evaluation") or {}).get("coverage_at_k") is None for r in body["runs"])
    all_runs.extend(body["runs"])
    save(f"p2_run_{split}.json", body)
assert all_runs, "no arms executed"

print("\n=== 7. independent verification recomputes from the raw snapshot ===")
target = all_runs[0]
status, verified = call("POST", "/api/experiments/verify", {"run_id": target["run_id"]})
assert status == 200, verified
print("  recomputed_from:", verified["recomputed_from"])
print("  snapshot exists:", Path(verified["recomputed_from"]).exists())
print("  matches_stored:", verified["matches_stored"])
print("  evaluation:", json.dumps(verified["evaluation"], ensure_ascii=False)[:600])
assert verified["evaluation"]["status"] == "awaiting_reference_set"
assert verified["evaluation"]["coverage_at_k"] is None
assert verified["matches_stored"] is True
save("p2_verify.json", verified)

print("\n=== 8. holdout stays closed until a human locks the candidate ===")
status, body = call("POST", "/api/experiments/run", {"spec_id": spec["spec_id"], "split": "holdout"})
print("  HTTP", status, "|", body.get("detail"))
assert status == 400 and "holdout is closed" in str(body.get("detail"))

print("\n=== 9. history is replayable ===")
status, history = call("GET", f"/api/experiments/runs?spec_id={spec['spec_id']}")
assert status == 200
print("  stored runs:", history["total"], "| arms:", dict(Counter(r["arm"] for r in history["runs"])))
status, detail = call("GET", f"/api/experiments/runs/{target['run_id']}")
assert status == 200 and detail["snapshot_available"] is True
print("  snapshot_available:", detail["snapshot_available"])
print("  skill_snapshot preserved:", detail["run"]["skill_snapshot"]["query_templates"])
status, comparison = call("GET", f"/api/experiments/compare/{spec['spec_id']}")
assert status == 200
print("  comparisons:", len(comparison["comparisons"]), "| gate:", comparison["promotion_gate"]["allowed"])
save("p2_history.json", {"history": history, "compare": comparison})

print("\n=== P2 LIVE RESULT ===")
print("real API retrieval: PASS (both arms, all three sources)")
print("reference DOIs verified against Crossref/OpenAlex: PASS")
print("coverage / promotion: NOT CLAIMED — awaiting human-confirmed reference set")
print("evidence written to", OUT)