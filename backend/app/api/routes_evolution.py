"""Evolution API: turn executed trials into diagnoses and candidate proposals.

Nothing here activates a version. A round produces at most three candidates and
the evaluator decides whether any of them may be promoted.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..models.evolution import (
    FAILURE_LABELS,
    MAX_CANDIDATES_PER_ROUND,
    EvolveRequest,
    EvolutionRound,
)
from ..services.evolution import run_evolution_round
from ..storage.store import get_store

router = APIRouter(prefix="/api/evolve", tags=["evolution"])


@router.get("/failure-types")
async def failure_types() -> dict:
    return {
        "failure_types": [
            {"key": key, "label": label} for key, label in FAILURE_LABELS.items()
        ],
        "max_candidates_per_round": MAX_CANDIDATES_PER_ROUND,
        "notice": (
            "Diagnoses are computed from executed runs and their stored snapshots. A failure "
            "that needs the frozen protocol changed is reported without a candidate."
        ),
    }


@router.post("/skills", response_model=EvolutionRound)
async def evolve_skills(request: EvolveRequest) -> EvolutionRound:
    store = get_store()
    spec = store.get_spec(request.spec_id)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"spec {request.spec_id} not found")
    try:
        return await run_evolution_round(
            store, spec, max_candidates=request.max_candidates, use_llm=request.use_llm
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/rounds")
async def list_rounds(spec_id: str | None = Query(default=None)) -> dict:
    rounds = get_store().list_evolution_rounds(spec_id)
    return {
        "rounds": [
            {
                "round_id": r.round_id,
                "spec_id": r.spec_id,
                "parent_version_id": r.parent_version_id,
                "proposer_mode": r.proposer_mode,
                "experience_count": len(r.experiences),
                "diagnosis_count": len(r.diagnoses),
                "proposal_count": len(r.proposals),
                "affordable_query_count": r.affordable_query_count,
                "created_at": r.created_at,
            }
            for r in rounds
        ],
        "total": len(rounds),
    }


@router.get("/rounds/{round_id}")
async def get_round(round_id: str) -> dict:
    record = get_store().get_evolution_round(round_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"evolution round {round_id} not found")
    return {"round": record.model_dump()}