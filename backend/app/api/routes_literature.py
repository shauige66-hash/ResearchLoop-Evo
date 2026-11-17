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
    MatrixCell,
    MatrixColumn,
    MatrixRequest,
    MatrixResponse,
    MatrixRow,
    PaperListResponse,
    ReportRequest,
    SearchResponse,
    TopicInput,
)
from ..services.classify import classify_method
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
        extraction_method="manual",
        updated_at=datetime.now(timezone.utc).isoformat(),
    )

    store = get_store()
    paper = store.update_paper_field(paper_id, field, evidence, patch.note)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")
    return paper


MATRIX_COLUMNS = [
    MatrixColumn(key="paper_id", label="Paper ID", kind="metadata"),
    MatrixColumn(key="title", label="Title", kind="metadata"),
    MatrixColumn(key="publication_year", label="Year", kind="metadata"),
    MatrixColumn(key="method_class", label="Method Class (system)", kind="system_label"),
    MatrixColumn(key="research_problem", label="Research Problem"),
    MatrixColumn(key="method", label="Method"),
    MatrixColumn(key="agent_architecture", label="Agent Architecture"),
    MatrixColumn(key="memory_strategy", label="Memory Strategy"),
    MatrixColumn(key="skill_strategy", label="Skill Strategy"),
    MatrixColumn(key="dataset", label="Dataset"),
    MatrixColumn(key="evaluation_metrics", label="Evaluation Metrics"),
    MatrixColumn(key="findings", label="Findings"),
    MatrixColumn(key="limitations", label="Limitations"),
    MatrixColumn(key="future_work", label="Future Work"),
]


def _apply_matrix_filters(papers: list, request: MatrixRequest) -> list:
    kept = []
    for paper in papers:
        if request.method_class and (paper.method_class or "") != request.method_class:
            continue
        if request.dataset:
            value = (paper.dataset.value or "").lower()
            if request.dataset.lower() not in value:
                continue
        if request.metric:
            value = (paper.evaluation_metrics.value or "").lower()
            if request.metric.lower() not in value:
                continue
        if request.year_from and (paper.publication_year or 0) < request.year_from:
            continue
        if request.year_to and (paper.publication_year or 9999) > request.year_to:
            continue
        kept.append(paper)
    return kept


@router.post("/matrix")
async def generate_matrix(request: MatrixRequest):
    """Generate a comparison matrix for selected papers, with optional filters."""
    store = get_store()
    papers = [p for p in (store.get_paper(pid) for pid in request.paper_ids) if p]
    if not papers:
        raise HTTPException(status_code=404, detail="no papers found")

    for paper in papers:
        if not paper.method_class:
            paper.method_class = classify_method(paper)

    available_filters = {
        "method_class": sorted({p.method_class for p in papers if p.method_class}),
        "year_range": [
            min((p.publication_year for p in papers if p.publication_year), default=None),
            max((p.publication_year for p in papers if p.publication_year), default=None),
        ],
    }
    filters_applied = {
        key: value
        for key, value in {
            "method_class": request.method_class,
            "dataset": request.dataset,
            "metric": request.metric,
            "year_from": request.year_from,
            "year_to": request.year_to,
        }.items()
        if value is not None
    }
    papers = _apply_matrix_filters(papers, request)
    if not papers:
        raise HTTPException(status_code=404, detail="no papers match the selected filters")

    rows = []
    for paper in papers:
        cells = {}
        for col in MATRIX_COLUMNS:
            if col.kind == "extracted":
                cells[col.key] = MatrixCell(
                    paper_id=paper.paper_id,
                    column=col.key,
                    evidence=getattr(paper, col.key),
                )
            else:
                value = getattr(paper, col.key)
                cells[col.key] = MatrixCell(
                    paper_id=paper.paper_id,
                    column=col.key,
                    text="" if value is None else str(value),
                )
        rows.append(MatrixRow(paper=paper, cells=cells))

    return MatrixResponse(
        columns=MATRIX_COLUMNS,
        rows=rows,
        generated_at=datetime.now(timezone.utc).isoformat(),
        notice=(
            "Extracted cells come from retrieved abstracts only (heuristic mode); no full "
            "text was read. 'Method Class (system)' is a system label, not an author claim. "
            "— means no evidence was found in the retrieved material."
        ),
        filters_applied=filters_applied,
        available_filters=available_filters,
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

    topic = "Literature Review"
    if request.run_id:
        for run in store.list_runs():
            if run["id"] == request.run_id:
                topic = run["topic"]
                break
    return generate_report(papers, topic)


@router.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
    }
