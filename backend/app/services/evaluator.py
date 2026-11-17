"""Independent evaluator: pure Python, no network, no agent self-assessment.

The evaluator only ever sees a run's retrieval record (the DOIs that came back,
the API request count, the unique paper count and the wall-clock duration) plus the
human-confirmed reference set. It never asks the agent how well it thinks it did,
and it cannot be reached from a candidate strategy.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models.experiment import (
    EVALUATOR_VERSION,
    BenchmarkCase,
    EvaluationReport,
    ExperimentRun,
    ExperimentSpec,
    fingerprint,
)


def normalize_doi(doi: str) -> str:
    text = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:", "doi.org/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.strip()


def reference_fingerprint(confirmed_dois: list[str]) -> str:
    return fingerprint(sorted({normalize_doi(d) for d in confirmed_dois}))


def dataset_fingerprint(cases: list[dict]) -> str:
    """Fingerprint over case ids, queries and splits — not over the references."""
    payload = [
        {
            "case_id": c["case_id"],
            "topic": c["topic"],
            "query": c["query"],
            "split": c["split"],
        }
        for c in sorted(cases, key=lambda x: x["case_id"])
    ]
    return fingerprint(payload)


def evaluate(
    *,
    retrieved_dois: list[str],
    confirmed_dois: list[str],
    api_query_count: int,
    unique_paper_count: int,
    execution_time_ms: int,
    dataset_fp: str,
    cache_hits: int = 0,
) -> EvaluationReport:
    """Compute the five metrics. Without confirmed references, coverage is None."""
    now = datetime.now(timezone.utc).isoformat()
    retrieved = {normalize_doi(d) for d in retrieved_dois if d}
    confirmed = sorted({normalize_doi(d) for d in confirmed_dois if d})

    if not confirmed:
        return EvaluationReport(
            status="awaiting_reference_set",
            coverage_at_k=None,
            hit_references=[],
            missed_references=[],
            api_query_count=api_query_count,
            cache_hits=cache_hits,
            unique_paper_count=unique_paper_count,
            execution_time_ms=execution_time_ms,
            reference_set_size=0,
            reference_fingerprint="",
            dataset_fingerprint=dataset_fp,
            evaluator_version=EVALUATOR_VERSION,
            computed_at=now,
            notice=(
                "No human-confirmed reference DOIs for this case. Retrieval ran and the "
                "cost metrics are real, but no coverage or accuracy is reported. "
                "Confirm references before any promotion decision."
            ),
        )

    hits = [d for d in confirmed if d in retrieved]
    missed = [d for d in confirmed if d not in retrieved]
    return EvaluationReport(
        status="computed",
        coverage_at_k=len(hits) / len(confirmed),
        hit_references=hits,
        missed_references=missed,
        api_query_count=api_query_count,
        cache_hits=cache_hits,
        unique_paper_count=unique_paper_count,
        execution_time_ms=execution_time_ms,
        reference_set_size=len(confirmed),
        reference_fingerprint=reference_fingerprint(confirmed),
        dataset_fingerprint=dataset_fp,
        evaluator_version=EVALUATOR_VERSION,
        computed_at=now,
    )


def evaluate_run(run: ExperimentRun, confirmed_dois: list[str], dataset_fp: str) -> EvaluationReport:
    return evaluate(
        retrieved_dois=run.retrieved_dois,
        confirmed_dois=confirmed_dois,
        api_query_count=run.api_request_count,
        cache_hits=run.cache_hits,
        unique_paper_count=run.unique_paper_count,
        execution_time_ms=run.execution_time_ms,
        dataset_fp=dataset_fp,
    )


def coverage_delta(baseline: ExperimentRun, candidate: ExperimentRun) -> float | None:
    b = baseline.evaluation
    c = candidate.evaluation
    if not b or not c or b.coverage_at_k is None or c.coverage_at_k is None:
        return None
    return c.coverage_at_k - b.coverage_at_k


def request_ratio(baseline: ExperimentRun, candidate: ExperimentRun) -> float | None:
    """Cost ratio over attempted queries, so a warm cache cannot mask extra searches."""
    if baseline.total_api_queries <= 0:
        return None
    return candidate.total_api_queries / baseline.total_api_queries


MAX_REQUEST_RATIO = 1.5


def promotion_blockers(
    *,
    spec: ExperimentSpec,
    cases: list[BenchmarkCase],
    runs: list[ExperimentRun],
) -> list[str]:
    """Reasons the candidate must keep the current Active Skill.

    Pure function over stored records: it never consults the agent's opinion of
    its own performance, and an empty list is the only thing that permits promotion.
    """
    reasons: list[str] = []
    by_case: dict[str, dict[str, ExperimentRun]] = {}
    for run in runs:
        by_case.setdefault(run.case_id, {})[run.arm] = run

    spec_cases = [c for c in cases if c.case_id in spec.case_ids]
    if not spec_cases:
        return ["the spec references no stored benchmark cases"]

    unconfirmed = [c.case_id for c in spec_cases if not c.confirmed_dois]
    if unconfirmed:
        reasons.append(
            "no human-confirmed reference set for: " + ", ".join(sorted(unconfirmed))
        )

    for case in spec_cases:
        arms = by_case.get(case.case_id, {})
        baseline, candidate = arms.get("baseline"), arms.get("candidate")
        if not baseline or not candidate:
            reasons.append(f"{case.case_id}: both arms must be executed before promotion")
            continue
        if candidate.unhandled_api_errors:
            reasons.append(f"{case.case_id}: candidate had unhandled API errors")
        if candidate.total_api_queries > spec.max_api_requests:
            reasons.append(
                f"{case.case_id}: candidate exceeded the frozen request ceiling "
                f"({candidate.total_api_queries} > {spec.max_api_requests})"
            )
        ratio = request_ratio(baseline, candidate)
        if ratio is not None and ratio > MAX_REQUEST_RATIO:
            reasons.append(
                f"{case.case_id}: candidate used {ratio:.2f}x the baseline API requests "
                f"(limit {MAX_REQUEST_RATIO}x)"
            )
        b_eval, c_eval = baseline.evaluation, candidate.evaluation
        if not b_eval or not c_eval:
            reasons.append(f"{case.case_id}: missing evaluation report")
            continue
        if b_eval.dataset_fingerprint != c_eval.dataset_fingerprint:
            reasons.append(f"{case.case_id}: dataset fingerprint differs between arms")
        if b_eval.reference_fingerprint != c_eval.reference_fingerprint:
            reasons.append(f"{case.case_id}: reference-set fingerprint differs between arms")
        if b_eval.evaluator_version != c_eval.evaluator_version:
            reasons.append(f"{case.case_id}: evaluator version differs between arms")
        if b_eval.coverage_at_k is None or c_eval.coverage_at_k is None:
            reasons.append(f"{case.case_id}: coverage is unavailable without confirmed references")
            continue
        if case.split == "validation" and c_eval.coverage_at_k <= b_eval.coverage_at_k:
            reasons.append(
                f"{case.case_id}: validation coverage did not improve "
                f"({b_eval.coverage_at_k:.3f} -> {c_eval.coverage_at_k:.3f})"
            )
        if case.split == "holdout" and c_eval.coverage_at_k < b_eval.coverage_at_k:
            reasons.append(
                f"{case.case_id}: holdout coverage regressed "
                f"({b_eval.coverage_at_k:.3f} -> {c_eval.coverage_at_k:.3f})"
            )

    if not any(c.split == "validation" for c in spec_cases):
        reasons.append("the spec contains no validation cases")
    if not any(c.split == "holdout" for c in spec_cases):
        reasons.append("the spec contains no holdout cases")
    elif not spec.candidate_locked_at:
        reasons.append("the candidate was never locked for the final holdout check")

    holdout_ids = {c.case_id for c in spec_cases if c.split == "holdout"}
    if holdout_ids and not any(r.case_id in holdout_ids for r in runs):
        reasons.append("the final holdout check has not been executed")

    return reasons