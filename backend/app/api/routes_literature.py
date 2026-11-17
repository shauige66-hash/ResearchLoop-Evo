"""Literature Discovery API routes.

Endpoints:
- POST /api/literature/search — run a search pipeline
- GET /api/literature/runs — list runs
- GET /api/literature/papers — list papers with filters
- GET /api/literature/papers/{paper_id} — get paper detail
- PATCH /api/literature/papers/{paper_id}/fields/{field} — manual field edit
- POST /api/literature/matrix — generate comparison matrix
- GET /api/literature/matrix/export — export matrix as CSV/JSON
- POST /api/literature/report — generate research report
- GET /api/health — health check
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ..models.paper import FieldEvidence
from ..models.schemas import (
    FieldPatch,
    MatrixRequest,
    PaperListResponse,
    ReportRequest,
    SearchResponse,
    TopicInput,
)
from ..services.export import export_matrix
from ..services.pipeline import search_pipeline
from ..services.report import generate_report
from ..storage.store import get_store

router = APIRouter(prefix="/api/literature", tags=["literature"])


@router.post("/search", response_model=SearchResponse)
async def search(topic: TopicInput) -> SearchResponse:
    """Run a literature search for the given topic."""
    try:
        response = await search_pipeline(topic)
        # Save to database
        store = get_store()
        store.save_project(response.project_id, response.topic)
        store.save_run(
            response.run_id,
            response.project_id,
            response.topic,
            response.meta,
            response.source_errors,
            len(response.papers),
        )
        for paper in response.papers:
            store.save_paper(paper, response.project_id)
        return response
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"search failed: {exc}")


@router.get("/runs", response_model=list[dict[str, Any]])
async def list_runs(project_id: str | None = None) -> list[dict[str, Any]]:
    """List all search runs."""
    store = get_store()
    return store.list_runs(project_id)


@router.get("/papers", response_model=PaperListResponse)
async def list_papers(
    project_id: str | None = None,
    run_id: str | None = None,
    year: int | None = None,
    source: str | None = None,
    is_review: bool | None = None,
    evidence_status: str | None = None,
    query: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> PaperListResponse:
    """List papers with filters and pagination."""
    store = get_store()
    papers, total = store.list_papers(
        project_id=project_id,
        run_id=run_id,
        year=year,
        source=source,
        is_review=is_review,
        evidence_status=evidence_status,
        query=query,
        page=page,
        page_size=page_size,
    )
    return PaperListResponse(
        papers=papers,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/papers/{paper_id}")
async def get_paper(paper_id: str):
    """Get a single paper by ID."""
    store = get_store()
    paper = store.get_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")
    return paper


@router.patch("/papers/{paper_id}/fields/{field}")
async def update_paper_field(paper_id: str, field: str, patch: FieldPatch):
    """Manually update a paper field (e.g., after human review)."""
    from ..models.paper import EXTRACTED_FIELDS

    if field not in EXTRACTED_FIELDS:
        raise HTTPException(status_code=400, detail=f"invalid field: {field}")

    evidence = FieldEvidence(
        value=patch.value,
        evidence_source=patch.evidence_source,
        evidence_span=patch.evidence_span,
        confidence="high" if patch.evidence_source == "manual" else "medium",
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

    store = get_store()
    paper = store.update_paper_field(paper_id, field, evidence, patch.note)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")
    return paper


@router.post("/matrix")
async def generate_matrix(request: MatrixRequest):
    """Generate a comparison matrix for selected papers."""
    store = get_store()
    papers = []
    for pid in request.paper_ids:
        paper = store.get_paper(pid)
        if paper:
            papers.append(paper)

    if not papers:
        raise HTTPException(status_code=404, detail="no papers found")

    # Build matrix rows
    from ..models.schemas import MatrixCell, MatrixColumn, MatrixResponse, MatrixRow

    columns = [
        MatrixColumn(key="paper_id", label="Paper ID"),
        MatrixColumn(key="title", label="Title"),
        MatrixColumn(key="research_problem", label="Research Problem"),
        MatrixColumn(key="method", label="Method"),
        MatrixColumn(key="dataset", label="Dataset"),
        MatrixColumn(key="evaluation_metrics", label="Evaluation Metrics"),
        MatrixColumn(key="findings", label="Findings"),
        MatrixColumn(key="limitations", label="Limitations"),
    ]

    rows = []
    for paper in papers:
        cells = {}
        for col in columns:
            if col.key in ("paper_id", "title"):
                value = getattr(paper, col.key)
                cells[col.key] = MatrixCell(
                    paper_id=paper.paper_id,
                    column=col.key,
                    evidence=FieldEvidence(value=value, evidence_source="abstract", confidence="high"),
                )
            else:
                evidence = getattr(paper, col.key)
                cells[col.key] = MatrixCell(
                    paper_id=paper.paper_id,
                    column=col.key,
                    evidence=evidence,
                )
        rows.append(MatrixRow(paper=paper, cells=cells))

    return MatrixResponse(
        columns=columns,
        rows=rows,
        generated_at=datetime.now(timezone.utc).isoformat(),
        notice="Matrix generated from extracted fields. Click cells to view evidence.",
    )


@router.get("/matrix/export")
async def export_matrix_endpoint(
    format: str = Query("csv", pattern="^(csv|json)$"),
    paper_ids: str | None = Query(None, description="comma-separated paper IDs"),
):
    """Export matrix as CSV or JSON."""
    if not paper_ids:
        raise HTTPException(status_code=400, detail="paper_ids required")

    ids = [pid.strip() for pid in paper_ids.split(",") if pid.strip()]
    store = get_store()
    papers = []
    for pid in ids:
        paper = store.get_paper(pid)
        if paper:
            papers.append(paper)

    if not papers:
        raise HTTPException(status_code=404, detail="no papers found")

    content, content_type = export_matrix(papers, format)  # type: ignore
    filename = f"literature_matrix.{format}"
    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/report")
async def generate_report_endpoint(request: ReportRequest):
    """Generate a literature research report."""
    store = get_store()

    # Collect papers
    papers = []
    if request.run_id:
        # Get all papers from this run
        all_papers, _ = store.list_papers(run_id=request.run_id, page=1, page_size=1000)
        papers = all_papers
    elif request.paper_ids:
        for pid in request.paper_ids:
            paper = store.get_paper(pid)
            if paper:
                papers.append(paper)

    if not papers:
        raise HTTPException(status_code=404, detail="no papers found")

    topic = papers[0].title.split(":")[0] if papers else "Literature Review"
    return generate_report(papers, topic)


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
    }
