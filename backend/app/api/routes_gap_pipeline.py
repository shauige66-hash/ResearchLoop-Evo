"""Multi-agent gap pipeline API, plus the LLM status and audit endpoints.

Every response carries real records: the plan, the evidence cards, the candidate
gaps, the critic scores, the counter-evidence outcome and the Python gate. The
LLM endpoints expose hashes and counts only — never a prompt body, never a key.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..models.gap_pipeline import (
    PROMPT_VERSION,
    PipelineAdvanceRequest,
    PipelineListResponse,
    PipelineResponse,
    PipelineStartRequest,
)
from ..models.llm import LLMCallRecord, LLMUsageSummary
from ..services import gap_pipeline as service
from ..services.llm import LLMProvider
from ..storage.store import get_store

router = APIRouter(prefix="/api/gap-pipeline", tags=["gap-pipeline"])
llm_router = APIRouter(prefix="/api/llm", tags=["llm"])


def _load(pipeline_id: str):
    pipeline = get_store().get_gap_pipeline(pipeline_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="gap pipeline not found")
    return pipeline


@router.post("/start", response_model=PipelineResponse)
async def start(
    request: PipelineStartRequest,
    max_stages: int = Query(7, ge=1, le=7),
) -> PipelineResponse:
    store = get_store()
    if not request.run_id and not request.paper_ids:
        raise HTTPException(status_code=400, detail="provide run_id or paper_ids")
    pipeline = service.create_pipeline(store, request)
    pipeline, executed = await service.advance(store, pipeline, max_stages=max_stages)
    return PipelineResponse(pipeline=pipeline, executed=executed)


@router.post("/{pipeline_id}/advance", response_model=PipelineResponse)
async def advance(pipeline_id: str, request: PipelineAdvanceRequest) -> PipelineResponse:
    store = get_store()
    pipeline = _load(pipeline_id)
    pipeline, executed = await service.advance(
        store,
        pipeline,
        max_stages=request.max_stages,
        from_stage=request.from_stage,
    )
    return PipelineResponse(pipeline=pipeline, executed=executed)


@router.get("", response_model=PipelineListResponse)
async def list_pipelines(workflow_id: str | None = None) -> PipelineListResponse:
    pipelines = get_store().list_gap_pipelines(workflow_id=workflow_id)
    return PipelineListResponse(pipelines=pipelines, total=len(pipelines))


@router.get("/{pipeline_id}")
async def get_pipeline(pipeline_id: str) -> dict:
    store = get_store()
    pipeline = _load(pipeline_id)
    cards = [
        card.model_dump()
        for card in (
            store.get_evidence_card(pid, PROMPT_VERSION)
            for pid in pipeline.selected_paper_ids
        )
        if card is not None
    ]
    gaps = [
        gap.model_dump()
        for gap in (store.get_gap(item.gap_id) for item in pipeline.gaps if item.gap_id)
        if gap is not None
    ]
    return {
        "pipeline": pipeline.model_dump(),
        "evidence_cards": cards,
        "gaps": gaps,
        "llm_calls": [r.model_dump() for r in store.list_llm_calls(pipeline_id=pipeline_id)],
        "llm_usage": LLMProvider(store).usage_summary().model_dump(),
    }


@llm_router.get("/status", response_model=LLMUsageSummary)
async def llm_status() -> LLMUsageSummary:
    return LLMProvider(get_store()).usage_summary()


@llm_router.get("/calls", response_model=list[LLMCallRecord])
async def llm_calls(
    pipeline_id: str | None = None,
    agent_role: str | None = None,
    limit: int = Query(200, ge=1, le=1000),
) -> list[LLMCallRecord]:
    records = get_store().list_llm_calls(pipeline_id=pipeline_id, agent_role=agent_role)
    return records[-limit:]