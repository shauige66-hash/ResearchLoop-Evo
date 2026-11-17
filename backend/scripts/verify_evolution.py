"""Live P3 verification: real trials -> diagnoses -> candidates -> gated promotion.

Writes real responses to backend/var/live_verification/ as evidence. Makes no new
retrieval calls: it evolves from the runs P2 already executed against the real APIs.
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


print("=== 1. registry before evolution ===")
status, registry = call("GET", "/api/skills/versions")
print("HTTP", status, "| versions:", registry.get("total"))
for v in registry.get("versions", []):
    print(f"  v{v['version_number']} {v['version_id']} [{v['status']}] parent={v['parent_version']}")
active_before = registry["versions"][0]
for v in registry["versions"]:
    if v["status"] == "active":
        active_before = v
save("p3_registry_before.json", registry)

status, specs = call("GET", "/api/experiments/specs")
spec = specs["specs"][0]
spec_id = spec["spec_id"]
print(f"\nspec {spec_id} | candidate={spec['candidate_version_id']} | locked={spec['candidate_locked_at']}")

status, cases = call("GET", "/api/experiments/benchmark/cases")
split_of = {c["case_id"]: c["split"] for c in cases["cases"]}
status, runs = call("GET", f"/api/experiments/runs?spec_id={spec_id}")
print("existing real runs:", runs["total"],
      dict(Counter(split_of.get(r["case_id"], "?") for r in runs["runs"])))

print("\n=== 2. failure taxonomy ===")
status, taxonomy = call("GET", "/api/evolve/failure-types")
print("HTTP", status, "| types:", [t["key"] for t in taxonomy["failure_types"]])
assert len(taxonomy["failure_types"]) == 6

print("\n=== 3. evolution round from real development trials ===")
status, round_body = call("POST", "/api/evolve/skills", {"spec_id": spec_id})
print("HTTP", status)
if status != 200:
    print(json.dumps(round_body, ensure_ascii=False)[:1500])
    raise SystemExit(1)
save("p3_round.json", round_body)
print("proposer_mode:", round_body["proposer_mode"], "| llm:", round_body["llm_skip_reason"])
print("experiences:", len(round_body["experiences"]),
      dict(Counter(e["split"] for e in round_body["experiences"])))
print("measured baseline requests:", round_body["baseline_api_requests"],
      "| affordable requests:", round_body["affordable_api_requests"],
      "| affordable queries:", round_body["affordable_query_count"])

print("\ndiagnoses:", len(round_body["diagnoses"]),
      dict(Counter(d["failure_type"] for d in round_body["diagnoses"])))
for d in round_body["diagnoses"]:
    print(f"  [{d['failure_type']}] {d['split']} run={d['run_id']}")
    print(f"    rationale: {d['rationale']}")
    print(f"    evidence keys: {sorted(d['evidence'])}")
    print(f"    suggested component: {d['suggested_component']}")

print("\nskipped mutations (honest refusals):")
for s in round_body["skipped_mutations"]:
    print(f"  {s['mutation']}: {s['reason']}")

print("\nproposals:", len(round_body["proposals"]))
assert len(round_body["proposals"]) <= 3, "candidate cap breached"
for p in round_body["proposals"]:
    print(f"\n  v{p['version_number']} {p['version_id']} parent={p['parent_version']}")
    print(f"    {p['mutation_description']}")
    print(f"    grounding: {p['grounding']}")
    print(f"    source_trials: {p['source_trials']}")
    print(f"    addressed failures: {p['addressed_failures']}")
    print(f"    changed components: {[c['component'] for c in p['changes']]}")
    print(f"    projected queries={p['projected_query_count']} "
          f"requests={p['projected_api_requests']} ratio={p['projected_request_ratio']}")
    assert p["projected_request_ratio"] is None or p["projected_request_ratio"] <= 1.5

print("\n=== 4. deterministic query preview of each proposal (no network) ===")
dev_case = next(c for c in cases["cases"] if c["split"] == "development")
for p in round_body["proposals"]:
    status, preview = call("POST", "/api/skills/preview", {
        "version_id": p["version_id"], "topic": dev_case["topic"], "query": dev_case["query"],
    })
    print(f"  v{p['version_number']} -> HTTP {status} | {preview['queries']}")
    save(f"p3_preview_v{p['version_number']}.json", preview)

print("\n=== 5. new versions never activated ===")
status, after = call("GET", "/api/skills/versions")
save("p3_registry_after.json", after)
status, active = call("GET", "/api/skills/active")
print("active version still:", active["version"]["version_id"],
      f"v{active['version']['version_number']}")
assert active["version"]["version_id"] == active_before["version_id"], "a candidate auto-activated"
for p in round_body["proposals"]:
    stored = next(v for v in after["versions"] if v["version_id"] == p["version_id"])
    assert stored["status"] == "candidate", stored["status"]
    assert stored["created_by"] == "proposer"
print("all proposals remain candidates: OK")

print("\n=== 6. promotion attempt on an unconfirmed benchmark ===")
target = round_body["proposals"][0]["version_id"] if round_body["proposals"] else spec["candidate_version_id"]
status, refused = call("POST", "/api/skills/promote", {
    "spec_id": spec_id, "version_id": spec["candidate_version_id"], "decided_by": "live-verification-script",
})
print("HTTP", status)
save("p3_promotion_refused.json", refused)
if status == 409:
    print("refused:", refused["detail"]["message"])
    for r in refused["detail"]["reasons"]:
        print("  -", r)
else:
    print(json.dumps(refused, ensure_ascii=False)[:800])
    raise SystemExit("promotion must not succeed without a confirmed reference set")

status, active = call("GET", "/api/skills/active")
assert active["version"]["version_id"] == active_before["version_id"]
print("active version unchanged after refusal: OK")

print("\n=== 7. rollback guard ===")
status, guard = call("POST", "/api/skills/rollback", {
    "version_id": spec["candidate_version_id"], "decided_by": "live-verification-script",
    "reason": "probe: this version was never active",
})
print("HTTP", status, "|", guard.get("detail"))
assert status == 400 and "never activated" in str(guard.get("detail"))
save("p3_rollback_guard.json", guard)

print("\n=== 8. round history ===")
status, listing = call("GET", f"/api/evolve/rounds?spec_id={spec_id}")
print("HTTP", status, "| rounds:", listing["total"])
for r in listing["rounds"]:
    print(f"  {r['round_id']} mode={r['proposer_mode']} "
          f"exp={r['experience_count']} diag={r['diagnosis_count']} prop={r['proposal_count']}")
save("p3_rounds.json", listing)

status, history = call("GET", "/api/skills/history")
print("\nskill events:", history["total"], dict(Counter(e["event"] for e in history["events"])))
save("p3_skill_history.json", history)

print(f"\nEvidence written to {OUT}")
print("STATUS: evolution loop runs on real trials. No version was promoted —")
print("        the benchmark reference set is still awaiting human confirmation.")