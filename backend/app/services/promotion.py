"""Version activation: a gated promotion forward, and an always-available rollback.

Promotion is the only path that makes a candidate active, and it is refused unless
every independent gate passes. Rollback deliberately bypasses the gate — returning
to a previously active version is a safety operation, not a claim of improvement —
and records who did it and why.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models.skill import SKILL_ID, SkillVersion
from ..storage.store import Store
from .evaluator import promotion_blockers


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PromotionRefused(Exception):
    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def promote(store: Store, spec_id: str, version_id: str, decided_by: str) -> SkillVersion:
    spec = store.get_spec(spec_id)
    if spec is None:
        raise ValueError(f"spec {spec_id} not found")
    version = store.get_skill_version(version_id)
    if version is None:
        raise ValueError(f"skill version {version_id} not found")
    if version_id != spec.candidate_version_id:
        raise ValueError(
            "only the candidate version of this spec may be promoted; run an experiment "
            "that pairs it against the baseline first"
        )
    if version.status != "candidate":
        raise ValueError(f"version {version_id} is {version.status}, not a candidate")

    cases = [c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids]
    runs = store.list_experiment_runs(spec_id=spec_id)
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    if reasons:
        raise PromotionRefused(reasons)

    previous = store.list_skill_versions(skill_id=SKILL_ID, status="active")
    for old in previous:
        store.set_skill_status(old.version_id, "archived")
        store.add_skill_event(
            old.version_id,
            "archived",
            {"reason": "superseded by promotion", "successor": version_id, "decided_by": decided_by},
        )
    activated = store.set_skill_status(version_id, "active")
    store.add_skill_event(
        version_id,
        "promoted",
        {
            "spec_id": spec_id,
            "decided_by": decided_by,
            "previous_active": [v.version_id for v in previous],
            "gate": "all promotion rules passed",
            "run_ids": [r.run_id for r in runs],
        },
    )
    return activated  # type: ignore[return-value]


def rollback(store: Store, version_id: str, decided_by: str, reason: str) -> SkillVersion:
    version = store.get_skill_version(version_id)
    if version is None:
        raise ValueError(f"skill version {version_id} not found")
    if version.status == "active":
        raise ValueError(f"version {version_id} is already active")
    history = store.list_skill_events(version_id)
    if not any(e["event"] in ("promoted", "seeded") for e in history):
        raise ValueError(
            "rollback may only return to a version that was active before; this version "
            "was never activated"
        )

    previous = store.list_skill_versions(skill_id=SKILL_ID, status="active")
    for old in previous:
        store.set_skill_status(old.version_id, "archived")
        store.add_skill_event(
            old.version_id,
            "archived",
            {"reason": "rolled back", "successor": version_id, "decided_by": decided_by},
        )
    restored = store.set_skill_status(version_id, "active")
    store.add_skill_event(
        version_id,
        "rolled_back",
        {
            "decided_by": decided_by,
            "reason": reason or "no reason given",
            "previous_active": [v.version_id for v in previous],
            "note": "rollback bypasses the promotion gate by design; it restores a known state "
            "and claims no improvement",
            "at": _now(),
        },
    )
    return restored  # type: ignore[return-value]