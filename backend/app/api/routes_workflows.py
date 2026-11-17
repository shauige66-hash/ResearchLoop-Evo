"""Workflow API: start, inspect, advance, and record the two human decisions.

Execution is always bounded by `max_steps`; there is no endpoint that loops until
the heat death of the universe. A failed step keeps its real error text and can be
retried in place, or the workflow can be rewound to any earlier step.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..models.workflow import (
    HUMAN_STEPS,
    STEP_SEQUENCE,
    STEP_TITLES,
    WorkflowAdvanceRequest,
    WorkflowApprovalRequest,
    WorkflowDecisionRequest,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowRun,
    WorkflowStartRequest,
)
from ..services.workflow import advance, create_workflow, record_approval, record_decision
from ..storage.store import get_store

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _require(workflow_id: str) -> WorkflowRun:
    workflow = get_store().get_workflow(workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail=f"workflow {workflow_id} not found")
    return workflow


@router.get("/steps")
async def step_catalog() -> dict:
    return {
        "steps": [
            {
                "step_id": step_id,
                "index": index,
                "title": STEP_TITLES[step_id][0],
                "title_zh": STEP_TITLES[step_id][1],
                "requires_human": step_id in HUMAN_STEPS,
            }
            for index, step_id in enumerate(STEP_SEQUENCE, start=1)
        ],
        "total": len(STEP_SEQUENCE),
        "notice": (
            "Holdout is never opened automatically: it stays a locked one-shot check "
            "in the Experiment Lab."
        ),
    }


@router.post("", response_model=WorkflowResponse)
async def start(request: WorkflowStartRequest) -> WorkflowResponse:
    workflow = create_workflow(
        get_store(),
        topic=request.topic,
        query=request.query,
        sources=request.sources,
        top_k=request.top_k,
        year_from=request.year_from,
        year_to=request.year_to,
        prefer_reviews=request.prefer_reviews,
    )
    return WorkflowResponse(workflow=workflow, executed=[])


@router.get("", response_model=WorkflowListResponse)
async def listing() -> WorkflowListResponse:
    workflows = get_store().list_workflows()
    return WorkflowListResponse(workflows=workflows, total=len(workflows))


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def detail(workflow_id: str) -> WorkflowResponse:
    return WorkflowResponse(workflow=_require(workflow_id))


@router.post("/{workflow_id}/advance", response_model=WorkflowResponse)
async def advance_workflow(workflow_id: str, request: WorkflowAdvanceRequest) -> WorkflowResponse:
    store = get_store()
    workflow = _require(workflow_id)
    try:
        workflow, executed = await advance(
            store, workflow, max_steps=request.max_steps, from_step=request.from_step
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WorkflowResponse(workflow=workflow, executed=executed)


@router.post("/{workflow_id}/approval", response_model=WorkflowResponse)
async def approval(workflow_id: str, request: WorkflowApprovalRequest) -> WorkflowResponse:
    store = get_store()
    workflow = _require(workflow_id)
    try:
        workflow = record_approval(
            store,
            workflow,
            gap_id=request.gap_id,
            decision=request.decision,
            decided_by=request.decided_by,
            human_note=request.human_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WorkflowResponse(workflow=workflow)


@router.post("/{workflow_id}/decision", response_model=WorkflowResponse)
async def decision(workflow_id: str, request: WorkflowDecisionRequest) -> WorkflowResponse:
    store = get_store()
    workflow = _require(workflow_id)
    workflow = record_decision(
        store,
        workflow,
        decision=request.decision,
        decided_by=request.decided_by,
        version_id=request.version_id,
        reason=request.reason,
    )
    return WorkflowResponse(workflow=workflow)


@router.get("/{workflow_id}/dossier")
async def dossier(workflow_id: str) -> dict:
    workflow = _require(workflow_id)
    data = workflow.context.get("dossier")
    if not data:
        raise HTTPException(
            status_code=409,
            detail="the research dossier step has not produced a dossier for this workflow yet",
        )
    return {"workflow_id": workflow_id, "dossier": data}