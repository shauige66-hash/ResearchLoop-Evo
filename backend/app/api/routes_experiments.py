"""Minimal Experiment Lab API: benchmark, frozen protocol, real arms, independent scoring.

Nothing here invents ground truth. A case without human-confirmed reference DOIs
still runs both arms and reports real cost metrics, but its coverage stays None and
the promotion gate stays closed.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..models.experiment import (
    COVERAGE_NOTICE,
    EVALUATOR_VERSION,
    HYPOTHESIS,
    TEMPLATE_ID,
    Arm,
    BenchmarkCase,
    BenchmarkCaseCreate,
    BenchmarkCaseResponse,
    BenchmarkListResponse,
    BenchmarkReference,
    ExperimentComparison,
    ExperimentRun,
    ExperimentSpec,
    PromotionGate,
    ReferenceAddRequest,
    ReferenceConfirmRequest,
    RunRequest,
    RunResponse,
    SpecCreateRequest,
    Split,
    VerifyRequest,
    VerifyResponse,
)
from ..services.benchmark import assign_splits, verify_doi
from ..services.evaluator import (
    dataset_fingerprint,
    evaluate,
    promotion_blockers,
)
from ..services.experiment import compare_case, ensure_seed_skill, run_spec
from ..services.http import HttpFailure
from ..storage.store import get_store

router = APIRouter(prefix="/api/experiments", tags=["experiments"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_case(case_id: str) -> BenchmarkCase:
    case = get_store().get_benchmark_case(case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"benchmark case {case_id} not found")
    return case


def _require_spec(spec_id: str) -> ExperimentSpec:
    spec = get_store().get_spec(spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail=f"experiment spec {spec_id} not found")
    return spec


async def _verify_dois(dois: list[str]) -> tuple[list[BenchmarkReference], list[dict]]:
    """Verify each DOI against Crossref/OpenAlex. Failures are reported, never hidden."""
    refs: list[BenchmarkReference] = []
    errors: list[dict] = []
    seen: set[str] = set()
    for raw in dois:
        try:
            ref = await verify_doi(raw)
        except (HttpFailure, ValueError) as exc:
            detail = exc.detail if isinstance(exc, HttpFailure) else str(exc)
            errors.append({"doi": raw, "detail": detail})
            continue
        if ref.doi in seen:
            continue
        seen.add(ref.doi)
        refs.append(ref)
    return refs, errors


@router.get("/templates")
async def list_templates() -> dict:
    """The single agent-evolution template this build actually implements."""
    return {
        "templates": [
            {
                "template_id": TEMPLATE_ID,
                "name": "Agent-Evolution Retrieval Coverage",
                "hypothesis": HYPOTHESIS,
                "hypothesis_status": "under_test",
                "arms": [
                    {
                        "arm": "baseline",
                        "description": "original question, fixed strategy, same APIs / time range / top-k",
                    },
                    {
                        "arm": "candidate",
                        "description": (
                            "queries from an evolved literature-search skill version; "
                            "identical APIs, time range, top-k and request ceiling"
                        ),
                    },
                ],
                "metrics": [
                    {"key": "coverage_at_k", "label": "Reference Coverage@K", "needs_references": True},
                    {"key": "missed_references", "label": "Missed References", "needs_references": True},
                    {"key": "api_query_count", "label": "API Query Count", "needs_references": False},
                    {"key": "unique_paper_count", "label": "Unique Paper Count", "needs_references": False},
                    {"key": "execution_time_ms", "label": "Execution Time (ms)", "needs_references": False},
                ],
                "evaluator_version": EVALUATOR_VERSION,
                "notice": COVERAGE_NOTICE,
            }
        ],
        "total": 1,
    }


def _benchmark_listing(cases: list[BenchmarkCase]) -> BenchmarkListResponse:
    counts: dict[str, int] = {}
    for case in cases:
        counts[case.split] = counts.get(case.split, 0) + 1
    confirmed = sum(1 for c in cases if c.confirmed_dois)
    return BenchmarkListResponse(
        cases=cases,
        total=len(cases),
        confirmed_cases=confirmed,
        awaiting_cases=len(cases) - confirmed,
        split_counts=counts,
    )


@router.get("/benchmark/cases", response_model=BenchmarkListResponse)
async def list_cases(
    split: Split | None = Query(default=None),
    reference_status: str | None = Query(default=None),
) -> BenchmarkListResponse:
    cases = get_store().list_benchmark_cases(split=split, reference_status=reference_status)
    return _benchmark_listing(cases)


@router.post("/benchmark/cases", response_model=BenchmarkCaseResponse)
async def create_case(request: BenchmarkCaseCreate) -> BenchmarkCaseResponse:
    store = get_store()
    refs, errors = ([], [])
    if request.reference_dois:
        if request.verify_references:
            refs, errors = await _verify_dois(request.reference_dois)
        else:
            refs = [BenchmarkReference(doi=d.strip().lower()) for d in request.reference_dois if d.strip()]

    split = request.split
    if split is None:
        same_topic = [
            c for c in store.list_benchmark_cases() if c.topic.strip().lower() == request.topic.strip().lower()
        ]
        split = same_topic[0].split if same_topic else "development"

    case = BenchmarkCase(
        case_id=f"case_{uuid.uuid4().hex[:12]}",
        topic=request.topic.strip(),
        query=request.query.strip(),
        reference_dois=[r.doi for r in refs],
        split=split,
        source=request.source,
        verified_by="crossref/openalex" if refs and request.verify_references else None,
        created_at=_now(),
        notes=request.notes,
        references=refs,
    )
    store.save_benchmark_case(case)
    return BenchmarkCaseResponse(case=case, verification_errors=errors)


@router.get("/benchmark/cases/{case_id}", response_model=BenchmarkCaseResponse)
async def get_case(case_id: str) -> BenchmarkCaseResponse:
    return BenchmarkCaseResponse(case=_require_case(case_id))


@router.post("/benchmark/cases/{case_id}/references", response_model=BenchmarkCaseResponse)
async def add_references(case_id: str, request: ReferenceAddRequest) -> BenchmarkCaseResponse:
    store = get_store()
    case = _require_case(case_id)
    refs, errors = await _verify_dois(request.dois)
    existing = {r.doi: r for r in case.references}
    for ref in refs:
        # Re-verification must not erase an existing human confirmation.
        previous = existing.get(ref.doi)
        if previous and previous.is_confirmed:
            ref.confirmed_by = previous.confirmed_by
            ref.confirmed_at = previous.confirmed_at
        existing[ref.doi] = ref
    case.references = list(existing.values())
    case.reference_dois = [r.doi for r in case.references]
    case.verified_by = "crossref/openalex"
    store.save_benchmark_case(case)
    return BenchmarkCaseResponse(case=case, verification_errors=errors)


@router.post("/benchmark/cases/{case_id}/confirm", response_model=BenchmarkCaseResponse)
async def confirm_references(case_id: str, request: ReferenceConfirmRequest) -> BenchmarkCaseResponse:
    """Human confirmation is the only thing that turns a DOI into ground truth."""
    store = get_store()
    case = _require_case(case_id)
    if not case.references:
        raise HTTPException(
            status_code=400,
            detail="this case has no verified reference DOIs to confirm; add references first",
        )
    wanted = {d.strip().lower() for d in request.dois} if request.dois else None
    unverified: list[str] = []
    confirmed = 0
    for ref in case.references:
        if wanted is not None and ref.doi not in wanted:
            continue
        if ref.verified_via == "manual":
            unverified.append(ref.doi)
            continue
        ref.confirmed_by = request.confirmed_by
        ref.confirmed_at = _now()
        confirmed += 1
    if wanted:
        missing = wanted - {r.doi for r in case.references}
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"these DOIs are not verified references of this case: {sorted(missing)}",
            )
    if unverified:
        raise HTTPException(
            status_code=400,
            detail=f"cannot confirm unverified DOIs: {unverified}",
        )
    if confirmed == 0:
        raise HTTPException(status_code=400, detail="no references matched the confirmation request")
    store.save_benchmark_case(case)
    return BenchmarkCaseResponse(case=case)


@router.post("/benchmark/assign-splits", response_model=BenchmarkListResponse)
async def assign_case_splits() -> BenchmarkListResponse:
    """Topic-grouped splits. Cases that already have runs are never moved."""
    store = get_store()
    cases = store.list_benchmark_cases()
    if not cases:
        raise HTTPException(status_code=400, detail="no benchmark cases to split")
    before = {c.case_id: c.split for c in cases}
    assign_splits(cases)
    moved = [c for c in cases if before[c.case_id] != c.split]
    frozen = [
        c.case_id
        for c in moved
        if store.list_experiment_runs(case_id=c.case_id)
    ]
    if frozen:
        raise HTTPException(
            status_code=409,
            detail=(
                "these cases already have experiment runs and cannot change split: "
                + ", ".join(sorted(frozen))
            ),
        )
    for case in cases:
        store.save_benchmark_case(case)
    return _benchmark_listing(store.list_benchmark_cases())


@router.post("/design", response_model=ExperimentSpec)
async def design_experiment(request: SpecCreateRequest) -> ExperimentSpec:
    store = get_store()
    ensure_seed_skill(store)

    cases = []
    for case_id in request.case_ids:
        cases.append(_require_case(case_id))

    topics: dict[str, set[str]] = {}
    for case in cases:
        topics.setdefault(case.topic.strip().lower(), set()).add(case.split)
    leaked = {t: sorted(s) for t, s in topics.items() if len(s) > 1}
    if leaked:
        raise HTTPException(
            status_code=400,
            detail=(
                "these topics span multiple splits, which would leak validation material: "
                f"{leaked}. Run POST /api/experiments/benchmark/assign-splits first."
            ),
        )

    if request.gap_id:
        gap = store.get_gap(request.gap_id)
        if not gap:
            raise HTTPException(status_code=404, detail=f"gap {request.gap_id} not found")
        if gap.status != "accepted":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"gap {request.gap_id} is '{gap.status}'. Only a human-accepted gap "
                    "may enter experiment design."
                ),
            )

    for version_id in (request.baseline_version_id, request.candidate_version_id):
        if not store.get_skill_version(version_id):
            raise HTTPException(status_code=404, detail=f"skill version {version_id} not found")

    spec = ExperimentSpec(
        spec_id=f"spec_{uuid.uuid4().hex[:12]}",
        gap_id=request.gap_id,
        case_ids=request.case_ids,
        sources=request.sources,
        year_from=request.year_from,
        year_to=request.year_to,
        top_k=request.top_k,
        max_api_requests=request.max_api_requests,
        use_cache=request.use_cache,
        baseline_version_id=request.baseline_version_id,
        candidate_version_id=request.candidate_version_id,
        created_at=_now(),
        created_by="human",
    )
    store.save_spec(spec)
    return spec


@router.get("/specs")
async def list_specs() -> dict:
    specs = get_store().list_specs()
    return {"specs": [s.model_dump() for s in specs], "total": len(specs)}


@router.get("/specs/{spec_id}")
async def get_spec(spec_id: str) -> dict:
    spec = _require_spec(spec_id)
    store = get_store()
    cases = [c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids]
    runs = store.list_experiment_runs(spec_id=spec_id)
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    return {
        "spec": spec.model_dump(),
        "cases": [c.model_dump() for c in cases],
        "run_count": len(runs),
        "promotion_gate": PromotionGate(allowed=not reasons, reasons=reasons).model_dump(),
    }


@router.post("/specs/{spec_id}/lock", response_model=ExperimentSpec)
async def lock_candidate(spec_id: str) -> ExperimentSpec:
    """One-way lock: after this the candidate is frozen and holdout may be opened once."""
    store = get_store()
    spec = _require_spec(spec_id)
    if spec.candidate_locked_at:
        raise HTTPException(status_code=409, detail="candidate is already locked")
    spec.candidate_locked_at = _now()
    store.save_spec(spec)
    store.add_skill_event(
        spec.candidate_version_id,
        "locked",
        {"spec_id": spec_id, "reason": "frozen for the final holdout check"},
    )
    return spec


def _comparisons(spec: ExperimentSpec, runs: list[ExperimentRun]) -> list[ExperimentComparison]:
    store = get_store()
    cases = [c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids]
    out = []
    for case in cases:
        case_runs = [r for r in runs if r.case_id == case.case_id]
        if case_runs:
            out.append(compare_case(spec, case, case_runs))
    return out


@router.post("/run", response_model=RunResponse)
async def run_experiment(request: RunRequest) -> RunResponse:
    store = get_store()
    spec = _require_spec(request.spec_id)
    arms: tuple[Arm, ...] = tuple(dict.fromkeys(request.arms)) or ("baseline", "candidate")
    try:
        runs = await run_spec(spec, store, split=request.split, arms=arms)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    all_runs = store.list_experiment_runs(spec_id=spec.spec_id)
    cases = [c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids]
    reasons = promotion_blockers(spec=spec, cases=cases, runs=all_runs)
    return RunResponse(
        spec_id=spec.spec_id,
        runs=runs,
        comparisons=_comparisons(spec, all_runs),
        promotion_gate=PromotionGate(allowed=not reasons, reasons=reasons),
    )


@router.get("/runs")
async def list_runs(
    spec_id: str | None = Query(default=None),
    case_id: str | None = Query(default=None),
    arm: Arm | None = Query(default=None),
    split: Split | None = Query(default=None),
) -> dict:
    runs = get_store().list_experiment_runs(
        spec_id=spec_id, case_id=case_id, arm=arm, split=split
    )
    return {"runs": [r.model_dump() for r in runs], "total": len(runs)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    store = get_store()
    run = store.get_experiment_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"experiment run {run_id} not found")
    snapshot = Path(run.raw_snapshot_path) if run.raw_snapshot_path else None
    case = store.get_benchmark_case(run.case_id)
    return {
        "run": run.model_dump(),
        "snapshot_available": bool(snapshot and snapshot.exists()),
        "case": case.model_dump() if case else None,
    }


@router.post("/verify", response_model=VerifyResponse)
async def verify_experiment(request: VerifyRequest) -> VerifyResponse:
    """Recompute the metrics from the raw snapshot with the independent evaluator.

    This is also how a run that executed before reference confirmation gets scored:
    the retrieval record is replayed against the now-confirmed reference set.
    """
    store = get_store()
    run = store.get_experiment_run(request.run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"experiment run {request.run_id} not found")
    if not run.raw_snapshot_path or not Path(run.raw_snapshot_path).exists():
        raise HTTPException(
            status_code=409,
            detail="the raw retrieval snapshot for this run is missing; it cannot be independently verified",
        )

    snapshot = json.loads(Path(run.raw_snapshot_path).read_text(encoding="utf-8"))
    response = snapshot.get("response", {})
    papers = response.get("papers", [])
    meta = response.get("meta", {})
    case = _require_case(run.case_id)
    spec = _require_spec(run.spec_id)
    spec_cases = [c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids]

    report = evaluate(
        retrieved_dois=[p.get("doi") for p in papers if p.get("doi")],
        confirmed_dois=case.confirmed_dois,
        api_query_count=int(meta.get("requests_made", 0)),
        cache_hits=int(meta.get("cache_hits", 0)),
        unique_paper_count=len(papers),
        execution_time_ms=int(meta.get("duration_ms", 0)),
        dataset_fp=dataset_fingerprint(
            [
                {"case_id": c.case_id, "topic": c.topic, "query": c.query, "split": c.split}
                for c in spec_cases
            ]
        ),
    )
    stored = run.evaluation
    matches = bool(
        stored
        and stored.coverage_at_k == report.coverage_at_k
        and stored.api_query_count == report.api_query_count
        and stored.cache_hits == report.cache_hits
        and stored.unique_paper_count == report.unique_paper_count
        and stored.reference_fingerprint == report.reference_fingerprint
    )
    run.evaluation = report
    run.status = "awaiting_reference_set" if report.status == "awaiting_reference_set" else "completed"
    store.save_experiment_run(run, case.split)
    return VerifyResponse(
        run_id=run.run_id,
        evaluation=report,
        stored_evaluation=stored,
        recomputed_from=run.raw_snapshot_path,
        matches_stored=matches,
    )


@router.get("/compare/{spec_id}")
async def compare_spec(spec_id: str) -> dict:
    store = get_store()
    spec = _require_spec(spec_id)
    runs = store.list_experiment_runs(spec_id=spec_id)
    cases = [c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids]
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    return {
        "spec": spec.model_dump(),
        "comparisons": [c.model_dump() for c in _comparisons(spec, runs)],
        "promotion_gate": PromotionGate(allowed=not reasons, reasons=reasons).model_dump(),
        "notice": COVERAGE_NOTICE,
    }