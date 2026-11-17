"""Skill Registry API: immutable versions, the active strategy, and query previews.

Creating a version never activates it. Activation is a promotion decision and is
gated by the independent evaluator, not by this router.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..models.evolution import EvaluateRequest, PromoteRequest, RollbackRequest
from ..models.experiment import COVERAGE_NOTICE
from ..models.skill import SKILL_ID, SkillVersion, SkillVersionCreate, plan_queries
from ..services.evaluator import promotion_blockers
from ..services.experiment import compare_case, ensure_seed_skill, run_spec
from ..services.promotion import PromotionRefused, promote, rollback
from ..storage.store import get_store

router = APIRouter(prefix="/api/skills", tags=["skills"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PreviewRequest(BaseModel):
    version_id: str
    topic: str = Field(min_length=1, max_length=400)
    query: str = Field(min_length=1, max_length=400)


@router.get("/versions")
async def list_versions(
    skill_id: str = Query(default=SKILL_ID),
    status: str | None = Query(default=None),
) -> dict:
    store = get_store()
    ensure_seed_skill(store)
    versions = store.list_skill_versions(skill_id=skill_id, status=status)
    return {
        "skill_id": skill_id,
        "versions": [v.model_dump() for v in versions],
        "total": len(versions),
        "evolvable_components": [
            "query_templates",
            "domain_synonyms",
            "keyword_expansion_rules",
            "source_priority",
            "search_filters",
            "retrieval_budget",
        ],
        "immutable_components": [
            "benchmark reference DOIs",
            "dataset splits",
            "evaluator code and formulas",
            "API source set",
            "spec budget ceilings",
        ],
    }


@router.get("/active")
async def active_version(skill_id: str = Query(default=SKILL_ID)) -> dict:
    store = get_store()
    ensure_seed_skill(store)
    active = store.list_skill_versions(skill_id=skill_id, status="active")
    if not active:
        raise HTTPException(status_code=404, detail=f"no active version for {skill_id}")
    return {"version": active[0].model_dump()}


@router.post("/versions", response_model=SkillVersion)
async def create_version(request: SkillVersionCreate) -> SkillVersion:
    store = get_store()
    ensure_seed_skill(store)
    parent = request.parent_version
    if parent is None:
        active = store.list_skill_versions(skill_id=SKILL_ID, status="active")
        parent = active[0].version_id if active else None
    elif not store.get_skill_version(parent):
        raise HTTPException(status_code=404, detail=f"parent version {parent} not found")

    version = SkillVersion(
        version_id=f"skillv_{uuid.uuid4().hex[:12]}",
        skill_id=SKILL_ID,
        version_number=store.next_version_number(SKILL_ID),
        parent_version=parent,
        strategy=request.strategy,
        mutation_description=request.mutation_description,
        source_trials=request.source_trials,
        created_at=_now(),
        status="candidate",
        created_by=request.created_by,
    )
    store.save_skill_version(version)
    store.add_skill_event(
        version.version_id,
        "created",
        {
            "parent_version": parent,
            "mutation_description": request.mutation_description,
            "source_trials": request.source_trials,
        },
    )
    return version


@router.get("/versions/{version_id}")
async def get_version(version_id: str) -> dict:
    store = get_store()
    version = store.get_skill_version(version_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"skill version {version_id} not found")
    return {
        "version": version.model_dump(),
        "events": store.list_skill_events(version_id),
        "runs_using_version": sum(
            1 for r in store.list_experiment_runs() if r.skill_version_id == version_id
        ),
    }


@router.post("/preview")
async def preview_queries(request: PreviewRequest) -> dict:
    """Deterministic query plan for a version — no network, no side effects."""
    version = get_store().get_skill_version(request.version_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"skill version {request.version_id} not found")
    queries = plan_queries(version.strategy, request.topic, request.query)
    return {
        "version_id": version.version_id,
        "queries": queries,
        "query_count": len(queries),
        "max_keywords": version.strategy.retrieval_budget.max_keywords,
    }


@router.get("/events")
async def list_events(version_id: str | None = Query(default=None)) -> dict:
    events = get_store().list_skill_events(version_id)
    return {"events": events, "total": len(events)}


@router.post("/evaluate")
async def evaluate_version(request: EvaluateRequest) -> dict:
    """Execute the spec's arms and score them with the independent evaluator.

    Development produces feedback, validation produces the baseline-vs-candidate
    comparison, and holdout stays a locked one-shot check.
    """
    store = get_store()
    spec = store.get_spec(request.spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {request.spec_id} not found")
    try:
        runs = await run_spec(spec, store, split=request.split)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cases = [c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids]
    all_runs = store.list_experiment_runs(spec_id=spec.spec_id)
    by_case: dict[str, list] = {}
    for run in all_runs:
        by_case.setdefault(run.case_id, []).append(run)
    comparisons = [compare_case(spec, c, by_case.get(c.case_id, [])) for c in cases]
    gate = promotion_blockers(spec=spec, cases=cases, runs=all_runs)
    return {
        "spec_id": spec.spec_id,
        "split": request.split,
        "runs": [r.model_dump() for r in runs],
        "comparisons": [c.model_dump() for c in comparisons],
        "promotion_gate": {"allowed": not gate, "reasons": gate},
        "notice": COVERAGE_NOTICE,
    }


@router.post("/promote")
async def promote_version(request: PromoteRequest) -> dict:
    store = get_store()
    try:
        version = promote(store, request.spec_id, request.version_id, request.decided_by)
    except PromotionRefused as exc:
        raise HTTPException(
            status_code=409,
            detail={"message": "promotion refused by the independent gate", "reasons": exc.reasons},
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "version": version.model_dump(),
        "events": store.list_skill_events(version.version_id),
        "notice": "New runs read this active version; historical runs keep their own snapshot.",
    }


@router.post("/rollback")
async def rollback_version(request: RollbackRequest) -> dict:
    store = get_store()
    try:
        version = rollback(store, request.version_id, request.decided_by, request.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "version": version.model_dump(),
        "events": store.list_skill_events(version.version_id),
        "notice": (
            "Rollback restores a previously active version and bypasses the promotion gate by "
            "design. It claims no improvement."
        ),
    }


@router.get("/history")
async def promotion_history(skill_id: str = Query(default=SKILL_ID)) -> dict:
    """The full mutation and activation trail, oldest first."""
    store = get_store()
    versions = {v.version_id: v for v in store.list_skill_versions(skill_id=skill_id)}
    events = [e for e in store.list_skill_events() if e["version_id"] in versions]
    return {
        "skill_id": skill_id,
        "events": [
            {
                **e,
                "version_number": versions[e["version_id"]].version_number,
                "mutation_description": versions[e["version_id"]].mutation_description,
            }
            for e in events
        ],
        "total": len(events),
    }