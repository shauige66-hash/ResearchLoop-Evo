"""Execute the two arms of the minimal experiment against the real retrieval APIs.

The protocol (sources, year range, top-k, request ceiling) comes from the frozen
ExperimentSpec and is identical for both arms. Only the query plan differs, and it
is produced by the skill version's strategy. A candidate therefore cannot widen the
budget, change the sources or touch the reference set.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from ..models.experiment import (
    Arm,
    BenchmarkCase,
    ExperimentComparison,
    ExperimentRun,
    ExperimentSpec,
)
from ..models.schemas import TopicInput
from ..models.skill import (
    SKILL_ID,
    SearchStrategy,
    SkillVersion,
    baseline_strategy,
    plan_queries,
)
from ..storage.store import Store
from .evaluator import coverage_delta, dataset_fingerprint, evaluate_run, request_ratio
from .pipeline import search_pipeline

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_seed_skill(store: Store) -> SkillVersion:
    """Create the immutable v1 baseline strategy once."""
    active = store.list_skill_versions(skill_id=SKILL_ID, status="active")
    if active:
        return active[0]
    existing = store.list_skill_versions(skill_id=SKILL_ID)
    if existing:
        return existing[0]
    version = SkillVersion(
        version_id=f"skillv_{uuid.uuid4().hex[:12]}",
        version_number=store.next_version_number(SKILL_ID),
        parent_version=None,
        strategy=baseline_strategy(),
        mutation_description="seed: original question, single query, no expansion",
        created_at=_now(),
        status="active",
        created_by="seed",
    )
    store.save_skill_version(version)
    store.add_skill_event(version.version_id, "seeded", {"reason": "initial active strategy"})
    return version


def _allowed_queries(spec: ExperimentSpec, queries: list[str]) -> tuple[list[str], bool]:
    """Clamp the query plan to the spec's request ceiling. Returns (queries, truncated)."""
    per_query = max(1, len(spec.sources))
    limit = max(1, spec.max_api_requests // per_query)
    if len(queries) <= limit:
        return queries, False
    return queries[:limit], True


def order_sources(priority: list[str], frozen: list[str]) -> list[str]:
    """Permute the frozen source set by strategy priority — never add or drop one.

    All sources are still queried. Priority changes the order papers enter the
    pipeline, which decides ties in the stable relevance sort and therefore which
    papers survive the top-k cut.
    """
    rank = {name: i for i, name in enumerate(priority)}
    return sorted(frozen, key=lambda name: rank.get(name, len(rank)))


def effective_years(
    spec: ExperimentSpec, strategy: SearchStrategy
) -> tuple[int | None, int | None]:
    """A strategy may narrow the frozen year window, never widen it."""
    lower = [y for y in (spec.year_from, strategy.search_filters.year_from) if y is not None]
    upper = [y for y in (spec.year_to, strategy.search_filters.year_to) if y is not None]
    return (max(lower) if lower else None, min(upper) if upper else None)


async def execute_arm(
    spec: ExperimentSpec,
    case: BenchmarkCase,
    arm: Arm,
    version: SkillVersion,
    store: Store,
) -> ExperimentRun:
    run_id = f"exprun_{uuid.uuid4().hex[:12]}"
    queries, truncated = _allowed_queries(spec, plan_queries(version.strategy, case.topic, case.query))
    run = ExperimentRun(
        run_id=run_id,
        spec_id=spec.spec_id,
        case_id=case.case_id,
        arm=arm,
        skill_version_id=version.version_id,
        skill_snapshot=version.strategy.model_copy(deep=True),
        queries_used=queries,
        status="running",
        started_at=_now(),
    )
    store.save_experiment_run(run, case.split)

    year_from, year_to = effective_years(spec, version.strategy)
    topic = TopicInput(
        topic=case.topic,
        keywords=queries,
        sources=order_sources(version.strategy.source_priority, list(spec.sources)),
        top_k=spec.top_k,
        year_from=year_from,
        year_to=year_to,
        expand_keywords=False,
        refresh=not spec.use_cache,
    )

    try:
        response = await search_pipeline(topic)
    except Exception as exc:
        logger.exception("experiment arm %s failed for case %s", arm, case.case_id)
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = _now()
        store.save_experiment_run(run, case.split)
        return run

    run.literature_run_id = response.run_id
    run.retrieved_paper_ids = [p.paper_id for p in response.papers]
    run.retrieved_dois = [p.doi for p in response.papers if p.doi]
    run.unique_paper_count = len(response.papers)
    run.api_request_count = int(response.meta.get("requests_made", 0))
    run.cache_hits = int(response.meta.get("cache_hits", 0))
    run.execution_time_ms = int(response.meta.get("duration_ms", 0))
    run.source_errors = [e.model_dump() for e in response.source_errors]
    if truncated:
        run.source_errors.append(
            {
                "source": "budget",
                "keyword": None,
                "status": None,
                "detail": (
                    f"query plan truncated to {len(queries)} queries by the spec ceiling "
                    f"of {spec.max_api_requests} API requests"
                ),
            }
        )

    snapshot_dir = store.db_path.parent / "experiments"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"{run_id}.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "spec": spec.model_dump(),
                "case": case.model_dump(),
                "arm": arm,
                "skill_version": version.model_dump(),
                "queries_used": queries,
                "response": response.model_dump(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    run.raw_snapshot_path = str(snapshot_path)

    dataset_fp = dataset_fingerprint(
        [
            {"case_id": c.case_id, "topic": c.topic, "query": c.query, "split": c.split}
            for c in store.list_benchmark_cases()
            if c.case_id in spec.case_ids
        ]
    )
    run.evaluation = evaluate_run(run, case.confirmed_dois, dataset_fp)
    run.status = (
        "awaiting_reference_set"
        if run.evaluation.status == "awaiting_reference_set"
        else "completed"
    )
    run.finished_at = _now()
    store.save_experiment_run(run, case.split)
    return run


def compare_case(
    spec: ExperimentSpec, case: BenchmarkCase, runs: list[ExperimentRun]
) -> ExperimentComparison:
    baseline = next((r for r in runs if r.arm == "baseline"), None)
    candidate = next((r for r in runs if r.arm == "candidate"), None)
    return ExperimentComparison(
        spec_id=spec.spec_id,
        case_id=case.case_id,
        split=case.split,
        baseline=baseline,
        candidate=candidate,
        coverage_delta=coverage_delta(baseline, candidate) if baseline and candidate else None,
        request_ratio=request_ratio(baseline, candidate) if baseline and candidate else None,
        reference_status=case.reference_status,
    )


async def run_spec(
    spec: ExperimentSpec,
    store: Store,
    split: str | None = None,
    arms: tuple[Arm, ...] = ("baseline", "candidate"),
) -> list[ExperimentRun]:
    """Run the requested arms over the cases in one split.

    Holdout stays closed until the candidate is locked, and it is a one-shot check:
    once a holdout run exists for this spec it is never searched again.
    """
    cases = [c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids]
    if split:
        cases = [c for c in cases if c.split == split]
    if not cases:
        raise ValueError(f"no benchmark cases in split {split!r} for this spec")

    if any(c.split == "holdout" for c in cases):
        if not spec.candidate_locked_at:
            raise ValueError(
                "holdout is closed: lock the candidate version before the final holdout check"
            )
        if store.list_experiment_runs(spec_id=spec.spec_id, split="holdout"):
            raise ValueError(
                "holdout was already used for this spec; it is a one-shot final check, "
                "not a repeatedly searchable split"
            )

    baseline = store.get_skill_version(spec.baseline_version_id)
    candidate = store.get_skill_version(spec.candidate_version_id)
    if not baseline or not candidate:
        raise ValueError("both skill versions must exist before running the experiment")

    results: list[ExperimentRun] = []
    for case in cases:
        for arm in arms:
            version = baseline if arm == "baseline" else candidate
            results.append(await execute_arm(spec, case, arm, version, store))
    return results