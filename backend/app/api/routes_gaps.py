"""Research Gap API: discovery, counter-evidence search and human review.

Candidates always start at `needs_human_review`. Nothing here promotes a gap into
an experiment on its own.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..models.gap import (
    GapDiscoveryRequest,
    GapListResponse,
    GapReviewRequest,
    ResearchGap,
)
from ..models.paper import Paper
from ..services.gap import ResearchGapAnalyzer
from ..storage.store import get_store

router = APIRouter(prefix="/api/gaps", tags=["gaps"])

MIN_PAPERS = 2


def _resolve_papers(request: GapDiscoveryRequest) -> tuple[list[Paper], str, str]:
    store = get_store()
    papers: list[Paper] = []
    run_id = request.run_id or ""
    topic = request.topic

    if request.paper_ids:
        for pid in request.paper_ids:
            paper = store.get_paper(pid)
            if paper:
                papers.append(paper)
        if papers and not run_id:
            run_id = papers[0].run_id or "adhoc"
    elif run_id:
        papers, _ = store.list_papers(run_id=run_id, page=1, page_size=200)
    else:
        raise HTTPException(status_code=400, detail="provide run_id or paper_ids")

    if not topic and run_id:
        for run in store.list_runs():
            if run["id"] == run_id:
                topic = run["topic"]
                break

    if len(papers) < MIN_PAPERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"gap discovery needs at least {MIN_PAPERS} retrieved papers to compare; "
                f"got {len(papers)}. A single paper's future work is not sufficient."
            ),
        )
    return papers, run_id, topic


@router.post("/discover", response_model=GapListResponse)
async def discover(request: GapDiscoveryRequest) -> GapListResponse:
    papers, run_id, topic = _resolve_papers(request)
    analyzer = ResearchGapAnalyzer(papers, topic, run_id)
    gaps = analyzer.analyze()
    if not gaps:
        return GapListResponse(gaps=[], total=0)
    if request.run_counter_search:
        gaps = await analyzer.add_counter_evidence(gaps, top_k=request.counter_top_k)
    store = get_store()
    for gap in gaps:
        store.save_gap(gap)
    return GapListResponse(gaps=gaps, total=len(gaps))


@router.get("", response_model=GapListResponse)
async def list_gaps(
    run_id: str | None = None,
    status: str | None = None,
    gap_type: str | None = None,
) -> GapListResponse:
    gaps = get_store().list_gaps(run_id=run_id, status=status, gap_type=gap_type)
    return GapListResponse(gaps=gaps, total=len(gaps))


@router.get("/{gap_id}")
async def get_gap(gap_id: str) -> dict:
    store = get_store()
    gap = store.get_gap(gap_id)
    if not gap:
        raise HTTPException(status_code=404, detail="gap not found")
    return {"gap": gap.model_dump(), "reviews": store.list_gap_reviews(gap_id)}


@router.patch("/{gap_id}", response_model=ResearchGap)
async def review_gap(gap_id: str, request: GapReviewRequest) -> ResearchGap:
    edits = {
        key: value
        for key, value in {
            "title": request.title,
            "description": request.description,
            "unresolved_question": request.unresolved_question,
        }.items()
        if value is not None
    }
    gap = get_store().review_gap(gap_id, request.status, request.human_note, edits)
    if not gap:
        raise HTTPException(status_code=404, detail="gap not found")
    return gap


@router.post("/{gap_id}/counter-search", response_model=ResearchGap)
async def rerun_counter_search(
    gap_id: str,
    top_k: int = Query(10, ge=1, le=20),
) -> ResearchGap:
    store = get_store()
    gap = store.get_gap(gap_id)
    if not gap:
        raise HTTPException(status_code=404, detail="gap not found")
    papers = [p for p in (store.get_paper(pid) for pid in gap.supporting_papers) if p]
    analyzer = ResearchGapAnalyzer(papers, gap.topic, gap.run_id)
    updated = await analyzer.add_counter_evidence([gap], top_k=top_k)
    store.save_gap(updated[0])
    return updated[0]