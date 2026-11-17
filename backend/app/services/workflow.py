"""The 18-step orchestrator.

Each step reads real records, calls the service that already owns that capability,
and writes the resulting ids and numbers into the workflow state. The state is
saved after every transition, so a failure or a restart resumes at the exact step
that was pending instead of replaying the whole pipeline.

Nothing here fabricates a result. When the evidence a step needs does not exist
(no accepted gap, no confirmed reference set, no development trial) the step says
so and the downstream gate stays closed.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..models.evolution import MAX_CANDIDATES_PER_ROUND
from ..models.experiment import (
    HYPOTHESIS,
    TEMPLATE_ID,
    BenchmarkCase,
    BenchmarkReference,
    ExperimentSpec,
)
from ..models.gap import ResearchGap
from ..models.paper import EXTRACTED_FIELDS, EXTRACTION_MODE, Paper
from ..models.schemas import TopicInput
from ..models.skill import SKILL_ID, SkillVersion, plan_queries
from ..models.workflow import (
    HUMAN_STEPS,
    STEP_CONTEXT_KEYS,
    STEP_SEQUENCE,
    WorkflowRun,
    WorkflowStep,
    new_steps,
)
from ..services.benchmark import assign_splits, verify_doi
from ..services.evaluator import (
    dataset_fingerprint,
    evaluate,
    promotion_blockers,
)
from ..services.evolution import (
    affordable_budget,
    collect_experiences,
    diagnose,
    run_evolution_round,
    salient_terms,
)
from ..services.experiment import compare_case, ensure_seed_skill, run_spec
from ..services.gap import ResearchGapAnalyzer
from ..services.http import HttpFailure
from ..services.pipeline import _expand_keywords, search_pipeline
from ..services.promotion import PromotionRefused, promote, rollback
from ..services.report import generate_report
from ..storage.store import Store

logger = logging.getLogger(__name__)

# Splits the workflow is allowed to search. Holdout is a locked one-shot check and
# stays a deliberate human action in the Experiment Lab, never an automatic step.
SEARCHABLE_SPLITS: tuple[str, ...] = ("development", "validation")

REFERENCE_PROVENANCE_NOTE = (
    "References were drawn from this workflow's own retrieval, so the baseline may "
    "already cover them. They are a seed for human review, not an independent gold "
    "set: a reviewer must confirm or replace them before any coverage number means "
    "anything."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_workflow(
    store: Store,
    *,
    topic: str,
    query: str | None,
    sources: list[str],
    top_k: int,
    year_from: int | None,
    year_to: int | None,
    prefer_reviews: bool,
) -> WorkflowRun:
    ensure_seed_skill(store)
    workflow = WorkflowRun(
        workflow_id=f"wf_{uuid.uuid4().hex[:12]}",
        topic=topic.strip(),
        query=(query or topic).strip(),
        sources=sources,  # type: ignore[arg-type]
        top_k=top_k,
        year_from=year_from,
        year_to=year_to,
        prefer_reviews=prefer_reviews,
        steps=new_steps(),
        created_at=_now(),
        updated_at=_now(),
    )
    store.save_workflow(workflow)
    return workflow


def _papers_of(store: Store, run_id: str) -> list[Paper]:
    papers, _ = store.list_papers(run_id=run_id, page=1, page_size=200)
    return papers


def _topic_input(workflow: WorkflowRun) -> TopicInput:
    return TopicInput(
        topic=workflow.topic,
        keywords=[workflow.query] if workflow.query != workflow.topic else [],
        sources=workflow.sources,
        top_k=workflow.top_k,
        year_from=workflow.year_from,
        year_to=workflow.year_to,
        prefer_reviews=workflow.prefer_reviews,
        expand_keywords=True,
        refresh=False,
    )


def _require(context: dict[str, Any], key: str) -> Any:
    value = context.get(key)
    if not value:
        raise ValueError(f"this step needs {key!r} from an earlier step, which is missing")
    return value


def _gate(store: Store, spec: ExperimentSpec) -> dict:
    cases = [c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids]
    runs = store.list_experiment_runs(spec_id=spec.spec_id)
    reasons = promotion_blockers(spec=spec, cases=cases, runs=runs)
    return {"allowed": not reasons, "reasons": reasons}


def _comparisons(store: Store, spec: ExperimentSpec) -> list[dict]:
    runs = store.list_experiment_runs(spec_id=spec.spec_id)
    cases = [c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids]
    out = []
    for case in cases:
        case_runs = [r for r in runs if r.case_id == case.case_id]
        if case_runs:
            out.append(compare_case(spec, case, case_runs).model_dump())
    return out


# --------------------------------------------------------------------- steps 1-5
async def _step_research_topic(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    project_id = f"proj_{uuid.uuid4().hex[:12]}"
    store.save_project(project_id, wf.topic)
    wf.context["project_id"] = project_id
    step.inputs = {"topic": wf.topic, "query": wf.query}
    step.outputs = {
        "project_id": project_id,
        "topic": wf.topic,
        "query": wf.query,
        "sources": wf.sources,
        "top_k": wf.top_k,
        "year_window": [wf.year_from, wf.year_to],
    }
    step.notice = "主题与检索边界已记录；后续每一步都引用这个 project_id。"


async def _step_search_planning(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    topic = _topic_input(wf)
    keywords = _expand_keywords(topic)
    step.inputs = {"topic": wf.topic, "query": wf.query, "sources": wf.sources}
    step.outputs = {
        "keywords_used": [k.model_dump() for k in keywords],
        "keyword_count": len(keywords),
        "planned_api_requests": len(keywords) * len(wf.sources),
        "sources": wf.sources,
        "top_k": wf.top_k,
    }
    step.notice = (
        "关键词由确定性扩展规则生成，未调用 LLM；planned_api_requests 是检索前的上限估计。"
    )


async def _step_literature_discovery(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    topic = _topic_input(wf)
    step.inputs = {"topic": topic.model_dump()}
    response = await search_pipeline(topic)
    project_id = wf.context.get("project_id") or response.project_id
    store.save_project(project_id, response.topic)
    store.save_run(
        response.run_id,
        project_id,
        response.topic,
        response.meta,
        response.source_errors,
        len(response.papers),
    )
    for paper in response.papers:
        store.save_paper(paper, project_id)
    if not response.papers:
        raise ValueError(
            "the three sources returned no paper for this topic; there is nothing to "
            "extract, compare or evolve. Widen the topic or the year window and retry."
        )
    wf.context["literature_run_id"] = response.run_id
    wf.context["paper_ids"] = [p.paper_id for p in response.papers]
    step.outputs = {
        "run_id": response.run_id,
        "paper_count": len(response.papers),
        "paper_ids": wf.context["paper_ids"],
        "requests_made": response.meta.get("requests_made", 0),
        "cache_hits": response.meta.get("cache_hits", 0),
        "duration_ms": response.meta.get("duration_ms", 0),
        "sources_requested": response.meta.get("sources_requested", []),
        "sources_failed": response.meta.get("sources_failed", []),
        "source_errors": [e.model_dump() for e in response.source_errors],
        "keywords_used": response.meta.get("keywords_used", []),
    }
    failed = response.meta.get("sources_failed", [])
    step.notice = (
        f"真实检索完成，保留 {len(response.papers)} 篇。失败来源：{', '.join(failed)}。"
        if failed
        else f"真实检索完成，保留 {len(response.papers)} 篇，三个来源均无错误。"
    )


async def _step_paper_extraction(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    run_id = _require(wf.context, "literature_run_id")
    papers = _papers_of(store, run_id)
    if not papers:
        raise ValueError(f"no stored paper for run {run_id}; extraction has nothing to audit")
    per_field = {}
    for field in EXTRACTED_FIELDS:
        grounded = [p for p in papers if getattr(p, field).evidence_status == "grounded"]
        per_field[field] = {
            "grounded": len(grounded),
            "unknown": len(papers) - len(grounded),
            "example_span": next(
                (getattr(p, field).evidence_span for p in grounded if getattr(p, field).evidence_span),
                None,
            ),
            "example_paper_id": grounded[0].paper_id if grounded else None,
        }
    step.inputs = {"run_id": run_id, "paper_count": len(papers)}
    step.outputs = {
        "extraction_mode": EXTRACTION_MODE,
        "fields_audited": len(EXTRACTED_FIELDS),
        "per_field": per_field,
        "papers_with_abstract": sum(1 for p in papers if p.abstract),
        "grounded_cells": sum(v["grounded"] for v in per_field.values()),
        "unknown_cells": sum(v["unknown"] for v in per_field.values()),
    }
    step.notice = (
        "Heuristic Mode：字段只来自检索到的摘要，未阅读任何全文。"
        "没有证据的字段保持 unknown，不猜测。"
    )


async def _step_literature_matrix(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    run_id = _require(wf.context, "literature_run_id")
    papers = _papers_of(store, run_id)
    if len(papers) < 2:
        raise ValueError("a comparison matrix needs at least two retrieved papers")
    methods = Counter(p.method_class or "unclassified" for p in papers)
    years = [p.publication_year for p in papers if p.publication_year]
    datasets = sorted({(p.dataset.value or "").strip() for p in papers if p.dataset.is_known})
    metrics = sorted(
        {(p.evaluation_metrics.value or "").strip() for p in papers if p.evaluation_metrics.is_known}
    )
    step.inputs = {"run_id": run_id, "paper_ids": [p.paper_id for p in papers]}
    step.outputs = {
        "row_count": len(papers),
        "columns": list(EXTRACTED_FIELDS),
        "method_distribution": dict(methods),
        "year_range": [min(years) if years else None, max(years) if years else None],
        "available_filters": {
            "method_class": sorted(methods),
            "dataset": datasets,
            "metric": metrics,
        },
        "matrix_endpoint": "/api/literature/matrix",
        "export_endpoint": "/api/literature/matrix/export",
    }
    step.notice = "矩阵行来自真实检索结果；完整单元格与导出走 /api/literature/matrix。"


# --------------------------------------------------------------------- steps 6-9
async def _step_gap_discovery(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    run_id = _require(wf.context, "literature_run_id")
    papers = _papers_of(store, run_id)
    analyzer = ResearchGapAnalyzer(papers, wf.topic, run_id)
    gaps = analyzer.analyze()
    for gap in gaps:
        store.save_gap(gap)
    wf.context["gap_ids"] = [g.gap_id for g in gaps]
    step.inputs = {"run_id": run_id, "papers_compared": len(papers)}
    step.outputs = {
        "gap_count": len(gaps),
        "gaps": [
            {
                "gap_id": g.gap_id,
                "title": g.title,
                "gap_type": g.gap_type,
                "confidence_label": g.confidence_label,
                "supporting_papers": g.supporting_papers,
                "status": g.status,
                "experimentability": g.experimentability,
            }
            for g in gaps
        ],
    }
    step.notice = (
        "每个候选都由至少两篇论文的方法/实验范围比较得出，默认 needs_human_review。"
        if gaps
        else "当前检索结果不足以支撑任何跨论文空白；不编造候选。"
    )


async def _step_counter_evidence_search(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    gap_ids = wf.context.get("gap_ids") or []
    if not gap_ids:
        step.outputs = {"gaps_searched": 0, "counter_evidence_found": 0}
        step.notice = "没有候选空白，反证检索无事可做。"
        return
    gaps = [g for g in (store.get_gap(gid) for gid in gap_ids) if g]
    run_id = _require(wf.context, "literature_run_id")
    analyzer = ResearchGapAnalyzer(_papers_of(store, run_id), wf.topic, run_id)
    updated = await analyzer.add_counter_evidence(gaps, top_k=10)
    for gap in updated:
        store.save_gap(gap)
    step.inputs = {"gap_ids": gap_ids, "sources": ["openalex", "crossref", "arxiv"], "top_k": 10}
    step.outputs = {
        "gaps_searched": len(updated),
        "counter_evidence_found": sum(len(g.counter_evidence) for g in updated),
        "per_gap": [
            {
                "gap_id": g.gap_id,
                "query": g.counter_search_queries[0] if g.counter_search_queries else "",
                "counter_count": len(g.counter_evidence),
                "confidence_label": g.confidence_label,
                "confidence_rationale": g.confidence_rationale,
                "scope": g.counter_search_scope,
                "errors": g.counter_search_errors,
            }
            for g in updated
        ],
    }
    step.notice = (
        "反证只表示当前检索范围内的发现；没有找到不等于问题不存在。"
    )


async def _step_human_approval(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    gap_ids = wf.context.get("gap_ids") or []
    gaps = [g for g in (store.get_gap(gid) for gid in gap_ids) if g]
    step.inputs = {
        "candidates": [
            {"gap_id": g.gap_id, "title": g.title, "status": g.status} for g in gaps
        ]
    }
    accepted = wf.context.get("accepted_gap_id")
    if not accepted:
        step.status = "awaiting_human"
        step.notice = (
            "等待人工在 Research Gap 页或此处接受/拒绝一个候选。"
            "未经确认的空白不会进入实验设计。"
        )
        return
    gap = store.get_gap(accepted)
    step.outputs = {
        "accepted_gap_id": accepted,
        "title": gap.title if gap else "",
        "decided_by": wf.context.get("approval_decided_by", ""),
        "human_note": wf.context.get("approval_note", ""),
        "rejected_gap_ids": wf.context.get("rejected_gap_ids", []),
    }
    step.notice = "人工确认已记录，只有被接受的空白进入下一步。"


async def _step_hypothesis(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    gap_id = _require(wf.context, "accepted_gap_id")
    gap = store.get_gap(gap_id)
    if gap is None:
        raise ValueError(f"accepted gap {gap_id} is no longer stored")
    if gap.status != "accepted":
        raise ValueError(f"gap {gap_id} is '{gap.status}', not 'accepted'")
    hypothesis = (
        f"{HYPOTHESIS} Target of this run: {gap.unresolved_question}"
    )
    wf.context["hypothesis"] = hypothesis
    step.inputs = {"gap_id": gap_id, "template_id": TEMPLATE_ID, "gap_type": gap.gap_type}
    step.outputs = {
        "hypothesis": hypothesis,
        "hypothesis_status": "under_test",
        "template_id": TEMPLATE_ID,
        "gap_id": gap_id,
        "unresolved_question": gap.unresolved_question,
        "experimentability": gap.experimentability,
    }
    step.notice = "这是待验证假设，不是已经成立的结论；证伪同样是有价值的输出。"


# -------------------------------------------------------------------- step 10
def _subtopic_groups(papers: list[Paper]) -> list[tuple[str, list[Paper]]]:
    groups: dict[str, list[Paper]] = {}
    for paper in papers:
        label = (paper.method_class or "").strip()
        if not label or label == "unclassified":
            continue
        if not paper.doi:
            continue
        groups.setdefault(label, []).append(paper)
    return sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:3]


async def _verify_subset(dois: list[str]) -> tuple[list[BenchmarkReference], list[dict]]:
    refs: list[BenchmarkReference] = []
    errors: list[dict] = []
    for doi in dois:
        try:
            refs.append(await verify_doi(doi))
        except (HttpFailure, ValueError) as exc:
            detail = exc.detail if isinstance(exc, HttpFailure) else str(exc)
            errors.append({"doi": doi, "detail": detail})
    return refs, errors


def _gap_seed_candidate(
    store: Store,
    parent: SkillVersion,
    spec: ExperimentSpec,
    gap: ResearchGap,
    papers: list[Paper],
    case: BenchmarkCase,
) -> tuple[SkillVersion, dict]:
    """A first candidate grounded in the accepted gap's own evidence vocabulary.

    The evolution round later reads executed trials; this seed exists so the spec
    has two genuinely different arms before any trial has run. It uses the same
    budget derivation and the same single-template substitution as the proposer.
    """
    by_id = {p.paper_id: p for p in papers}
    titles = [by_id[pid].title for pid in gap.supporting_papers if pid in by_id]
    counts: Counter[str] = Counter()
    for title in titles:
        for term in salient_terms(title):
            counts[term] += 1
    already = set(salient_terms(gap.unresolved_question)) | set(
        salient_terms(f"{case.topic} {case.query}")
    )
    additions = [t for t, _ in counts.most_common() if t not in already][:1]
    requests, queries = affordable_budget(0, len(spec.sources), spec.max_api_requests)
    strategy = parent.strategy.model_copy(deep=True)
    before = list(strategy.query_templates)
    if additions:
        strategy.query_templates = [f"{{query}} {additions[0]}"]
        grounding = (
            f"term {additions[0]!r} is the most frequent salient term in the titles of the "
            f"{len(titles)} papers supporting the accepted gap that is absent from both the "
            "gap's unresolved question and this case's topic/query wording"
        )
    else:
        strategy.query_templates = ["{query} {topic}"]
        grounding = (
            "the gap's supporting titles add no term absent from its unresolved question or "
            "this case's wording, so the template falls back to covering the topic wording "
            "and may retrieve the same papers as the baseline"
        )
    strategy.retrieval_budget.max_keywords = queries
    strategy.retrieval_budget.top_k = spec.top_k
    strategy.retrieval_budget.max_api_requests = spec.max_api_requests
    version = SkillVersion(
        version_id=spec.candidate_version_id,
        skill_id=SKILL_ID,
        version_number=store.next_version_number(SKILL_ID),
        parent_version=parent.version_id,
        strategy=strategy,
        mutation_description=(
            f"Seed candidate for the accepted gap '{gap.title}'. {grounding}. "
            f"The budget affords {queries} query/queries ({requests} requests), so the term "
            "is substituted into the single template instead of adding a second search."
        ),
        source_trials=[gap.run_id] if gap.run_id else [],
        created_at=_now(),
        status="candidate",
        created_by="proposer",
    )
    store.save_skill_version(version)
    store.add_skill_event(
        version.version_id,
        "proposed",
        {
            "parent_version": parent.version_id,
            "gap_id": gap.gap_id,
            "grounding": grounding,
            "before_templates": before,
            "after_templates": list(strategy.query_templates),
            "workflow_seed": True,
        },
    )
    return version, {
        "grounding": grounding,
        "before_templates": before,
        "after_templates": list(strategy.query_templates),
        "affordable_api_requests": requests,
        "affordable_query_count": queries,
        "preview_case_id": case.case_id,
        "planned_queries": plan_queries(strategy, case.topic, case.query),
    }


async def _step_experiment_spec(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    run_id = _require(wf.context, "literature_run_id")
    gap_id = _require(wf.context, "accepted_gap_id")
    gap = store.get_gap(gap_id)
    if gap is None or gap.status != "accepted":
        raise ValueError("experiment design requires a stored, human-accepted gap")
    papers = _papers_of(store, run_id)
    groups = _subtopic_groups(papers)
    if not groups:
        raise ValueError(
            "no method-class group with a DOI-bearing paper was retrieved, so no benchmark "
            "case can be derived without inventing one"
        )

    existing = {c.topic.strip().lower(): c for c in store.list_benchmark_cases()}
    cases: list[BenchmarkCase] = []
    fresh: list[BenchmarkCase] = []
    verification_errors: list[dict] = []
    for label, group in groups:
        subtopic = f"{wf.topic} {label}"
        cached = existing.get(subtopic.strip().lower())
        if cached is not None:
            cases.append(cached)
            continue
        dois = [p.doi for p in group if p.doi][:3]
        refs, errors = await _verify_subset(dois)
        verification_errors.extend(errors)
        if not refs:
            continue
        case = BenchmarkCase(
            case_id=f"case_{uuid.uuid4().hex[:12]}",
            topic=subtopic,
            query=subtopic,
            reference_dois=[r.doi for r in refs],
            split="development",
            source="derived_from_run",
            verified_by="crossref/openalex",
            created_at=_now(),
            notes=REFERENCE_PROVENANCE_NOTE,
            references=refs,
        )
        fresh.append(case)
        cases.append(case)
    if not cases:
        raise ValueError(
            "none of the derived reference DOIs could be verified by Crossref or OpenAlex; "
            "refusing to build a benchmark on unverified identifiers"
        )
    if fresh:
        assign_splits(fresh)
        for case in fresh:
            store.save_benchmark_case(case)

    active = store.list_skill_versions(skill_id=SKILL_ID, status="active")
    if not active:
        raise ValueError("no active skill version to serve as the baseline arm")
    parent = active[0]
    candidate_id = f"skillv_{uuid.uuid4().hex[:12]}"
    spec = ExperimentSpec(
        spec_id=f"spec_{uuid.uuid4().hex[:12]}",
        gap_id=gap_id,
        case_ids=[c.case_id for c in cases],
        sources=wf.sources,
        year_from=wf.year_from,
        year_to=wf.year_to,
        top_k=wf.top_k,
        max_api_requests=max(len(wf.sources) * 2, 6),
        use_cache=True,
        baseline_version_id=parent.version_id,
        candidate_version_id=candidate_id,
        created_at=_now(),
        created_by="workflow",
    )
    candidate, seed_info = _gap_seed_candidate(store, parent, spec, gap, papers, cases[0])
    store.save_spec(spec)
    wf.context["spec_id"] = spec.spec_id
    wf.context["case_ids"] = spec.case_ids
    wf.context["candidate_version_id"] = candidate.version_id
    step.inputs = {
        "gap_id": gap_id,
        "literature_run_id": run_id,
        "method_groups": {label: len(group) for label, group in groups},
        "baseline_version_id": parent.version_id,
    }
    step.outputs = {
        "spec_id": spec.spec_id,
        "case_ids": spec.case_ids,
        "cases": [
            {
                "case_id": c.case_id,
                "topic": c.topic,
                "split": c.split,
                "reference_count": len(c.references),
                "confirmed_count": len(c.confirmed_dois),
                "reference_status": c.reference_status,
            }
            for c in cases
        ],
        "split_counts": dict(Counter(c.split for c in cases)),
        "verification_errors": verification_errors,
        "baseline_version_id": parent.version_id,
        "candidate_version_id": candidate.version_id,
        "candidate_version_number": candidate.version_number,
        "mutation_description": candidate.mutation_description,
        "seed": seed_info,
        "max_api_requests": spec.max_api_requests,
        "top_k": spec.top_k,
        "reference_provenance": REFERENCE_PROVENANCE_NOTE,
    }
    unconfirmed = [c.case_id for c in cases if not c.confirmed_dois]
    step.notice = (
        f"协议已冻结。{len(unconfirmed)} 个 case 的参考 DOI 已通过元数据核验但尚未人工确认，"
        "因此覆盖率为 null、晋升门禁关闭。参考集合来自本流程自身检索，需人工复核或替换。"
    )


# ------------------------------------------------------------------ steps 11-13
async def _run_splits(
    store: Store, spec: ExperimentSpec, arms: tuple[str, ...]
) -> tuple[list[dict], list[str]]:
    executed: list[dict] = []
    skipped: list[str] = []
    for split in SEARCHABLE_SPLITS:
        cases = [
            c
            for c in store.list_benchmark_cases()
            if c.case_id in spec.case_ids and c.split == split
        ]
        if not cases:
            skipped.append(f"{split}: no case in this split")
            continue
        runs = await run_spec(spec, store, split=split, arms=arms)  # type: ignore[arg-type]
        executed.extend(
            {
                "run_id": r.run_id,
                "case_id": r.case_id,
                "split": split,
                "arm": r.arm,
                "status": r.status,
                "queries_used": r.queries_used,
                "api_request_count": r.api_request_count,
                "cache_hits": r.cache_hits,
                "total_api_queries": r.total_api_queries,
                "unique_paper_count": r.unique_paper_count,
                "execution_time_ms": r.execution_time_ms,
                "source_errors": r.source_errors,
                "error": r.error,
            }
            for r in runs
        )
    return executed, skipped


async def _step_baseline_execution(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    spec = store.get_spec(_require(wf.context, "spec_id"))
    if spec is None:
        raise ValueError("the frozen spec is no longer stored")
    step.inputs = {
        "spec_id": spec.spec_id,
        "baseline_version_id": spec.baseline_version_id,
        "splits": list(SEARCHABLE_SPLITS),
    }
    executed, skipped = await _run_splits(store, spec, ("baseline",))
    wf.context["baseline_run_ids"] = [r["run_id"] for r in executed]
    step.outputs = {"runs": executed, "run_count": len(executed), "skipped_splits": skipped}
    step.notice = "基线使用 Active 版本的冻结策略；holdout 不在此自动打开。"


async def _step_candidate_execution(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    spec = store.get_spec(_require(wf.context, "spec_id"))
    if spec is None:
        raise ValueError("the frozen spec is no longer stored")
    step.inputs = {
        "spec_id": spec.spec_id,
        "candidate_version_id": spec.candidate_version_id,
        "splits": list(SEARCHABLE_SPLITS),
    }
    executed, skipped = await _run_splits(store, spec, ("candidate",))
    wf.context["candidate_run_ids"] = [r["run_id"] for r in executed]
    step.outputs = {"runs": executed, "run_count": len(executed), "skipped_splits": skipped}
    step.notice = "候选与基线共用同一 API 集合、时间窗、Top-K 与请求上限。"


async def _step_independent_evaluation(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    spec = store.get_spec(_require(wf.context, "spec_id"))
    if spec is None:
        raise ValueError("the frozen spec is no longer stored")
    cases = {c.case_id: c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids}
    spec_cases = list(cases.values())
    fp = dataset_fingerprint(
        [{"case_id": c.case_id, "topic": c.topic, "query": c.query, "split": c.split} for c in spec_cases]
    )
    runs = store.list_experiment_runs(spec_id=spec.spec_id)
    scored: list[dict] = []
    missing_snapshots: list[str] = []
    for run in runs:
        case = cases.get(run.case_id)
        if case is None:
            continue
        snapshot = Path(run.raw_snapshot_path) if run.raw_snapshot_path else None
        if snapshot and snapshot.exists():
            payload = json.loads(snapshot.read_text(encoding="utf-8"))
            response = payload.get("response", {})
            papers = response.get("papers", [])
            meta = response.get("meta", {})
            report = evaluate(
                retrieved_dois=[p.get("doi") for p in papers if p.get("doi")],
                confirmed_dois=case.confirmed_dois,
                api_query_count=int(meta.get("requests_made", 0)),
                cache_hits=int(meta.get("cache_hits", 0)),
                unique_paper_count=len(papers),
                execution_time_ms=int(meta.get("duration_ms", 0)),
                dataset_fp=fp,
            )
            recomputed_from = str(snapshot)
        else:
            missing_snapshots.append(run.run_id)
            report = evaluate(
                retrieved_dois=run.retrieved_dois,
                confirmed_dois=case.confirmed_dois,
                api_query_count=run.api_request_count,
                cache_hits=run.cache_hits,
                unique_paper_count=run.unique_paper_count,
                execution_time_ms=run.execution_time_ms,
                dataset_fp=fp,
            )
            recomputed_from = "stored run record (raw snapshot missing)"
        run.evaluation = report
        run.status = "awaiting_reference_set" if report.status == "awaiting_reference_set" else "completed"
        store.save_experiment_run(run, case.split)
        scored.append(
            {
                "run_id": run.run_id,
                "case_id": run.case_id,
                "arm": run.arm,
                "split": case.split,
                "status": report.status,
                "coverage_at_k": report.coverage_at_k,
                "hit_references": report.hit_references,
                "missed_references": report.missed_references,
                "api_query_count": report.api_query_count,
                "cache_hits": report.cache_hits,
                "unique_paper_count": report.unique_paper_count,
                "execution_time_ms": report.execution_time_ms,
                "reference_set_size": report.reference_set_size,
                "reference_fingerprint": report.reference_fingerprint,
                "recomputed_from": recomputed_from,
            }
        )
    gate = _gate(store, spec)
    wf.context["promotion_gate"] = gate
    step.inputs = {"spec_id": spec.spec_id, "runs_scored": len(runs), "evaluator": "independent"}
    step.outputs = {
        "evaluations": scored,
        "comparisons": _comparisons(store, spec),
        "promotion_gate": gate,
        "runs_without_snapshot": missing_snapshots,
    }
    step.notice = (
        "覆盖率由独立 Evaluator 从原始快照重算，不读取 Agent 自我评价。"
        "没有人工确认参考集合时覆盖率为 null，而不是 0。"
    )


# ------------------------------------------------------------------ steps 14-16
async def _step_failure_diagnosis(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    spec = store.get_spec(_require(wf.context, "spec_id"))
    if spec is None:
        raise ValueError("the frozen spec is no longer stored")
    experiences = collect_experiences(store, spec)
    diagnoses = [d for exp in experiences for d in diagnose(exp)]
    wf.context["diagnosis_count"] = len(diagnoses)
    step.inputs = {"spec_id": spec.spec_id, "experiences": len(experiences)}
    step.outputs = {
        "experience_count": len(experiences),
        "diagnosis_count": len(diagnoses),
        "diagnoses": [d.model_dump() for d in diagnoses],
        "failure_type_counts": dict(Counter(d.failure_type for d in diagnoses)),
        "source_tallies": [
            {"run_id": e.run_id, "arm": e.arm, "tallies": [t.model_dump() for t in e.source_tallies]}
            for e in experiences
        ],
    }
    step.notice = (
        "诊断只使用 development 试验的真实数字；六类失败分别归因，不全部推给 prompt。"
    )


async def _step_skill_mutation(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    spec = store.get_spec(_require(wf.context, "spec_id"))
    if spec is None:
        raise ValueError("the frozen spec is no longer stored")
    step.inputs = {
        "spec_id": spec.spec_id,
        "parent_version_id": spec.candidate_version_id,
        "max_candidates": MAX_CANDIDATES_PER_ROUND,
        "use_llm": False,
    }
    record = await run_evolution_round(store, spec, max_candidates=MAX_CANDIDATES_PER_ROUND)
    wf.context["round_id"] = record.round_id
    wf.context["proposed_version_ids"] = [p.version_id for p in record.proposals]
    step.outputs = {
        "round_id": record.round_id,
        "proposer_mode": record.proposer_mode,
        "llm_skip_reason": record.llm_skip_reason,
        "baseline_api_requests": record.baseline_api_requests,
        "affordable_api_requests": record.affordable_api_requests,
        "affordable_query_count": record.affordable_query_count,
        "proposals": [p.model_dump() for p in record.proposals],
        "skipped_mutations": record.skipped_mutations,
    }
    step.notice = (
        f"本轮真实生成 {len(record.proposals)} 个候选（上限 {MAX_CANDIDATES_PER_ROUND}）。"
        "Evaluator 与 Benchmark 未被修改。"
    )


async def _step_replay_evaluation(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    base_spec = store.get_spec(_require(wf.context, "spec_id"))
    if base_spec is None:
        raise ValueError("the frozen spec is no longer stored")
    version_ids = wf.context.get("proposed_version_ids") or []
    if not version_ids:
        step.outputs = {"replays": [], "replay_count": 0}
        step.notice = "本轮没有候选被提出，因此没有可回放的版本；不伪造回放结果。"
        return
    replays: list[dict] = []
    for version_id in version_ids:
        replay_spec = ExperimentSpec(
            spec_id=f"spec_{uuid.uuid4().hex[:12]}",
            gap_id=base_spec.gap_id,
            case_ids=list(base_spec.case_ids),
            sources=list(base_spec.sources),
            year_from=base_spec.year_from,
            year_to=base_spec.year_to,
            top_k=base_spec.top_k,
            max_api_requests=base_spec.max_api_requests,
            use_cache=base_spec.use_cache,
            baseline_version_id=base_spec.baseline_version_id,
            candidate_version_id=version_id,
            created_at=_now(),
            created_by="workflow-replay",
        )
        store.save_spec(replay_spec)
        executed, skipped = await _run_splits(store, replay_spec, ("baseline", "candidate"))
        cases = {
            c.case_id: c for c in store.list_benchmark_cases() if c.case_id in replay_spec.case_ids
        }
        fp = dataset_fingerprint(
            [
                {"case_id": c.case_id, "topic": c.topic, "query": c.query, "split": c.split}
                for c in cases.values()
            ]
        )
        for run in store.list_experiment_runs(spec_id=replay_spec.spec_id):
            case = cases.get(run.case_id)
            if case is None:
                continue
            run.evaluation = evaluate(
                retrieved_dois=run.retrieved_dois,
                confirmed_dois=case.confirmed_dois,
                api_query_count=run.api_request_count,
                cache_hits=run.cache_hits,
                unique_paper_count=run.unique_paper_count,
                execution_time_ms=run.execution_time_ms,
                dataset_fp=fp,
            )
            run.status = (
                "awaiting_reference_set"
                if run.evaluation.status == "awaiting_reference_set"
                else "completed"
            )
            store.save_experiment_run(run, case.split)
        gate = _gate(store, replay_spec)
        replays.append(
            {
                "spec_id": replay_spec.spec_id,
                "candidate_version_id": version_id,
                "runs": executed,
                "skipped_splits": skipped,
                "comparisons": _comparisons(store, replay_spec),
                "promotion_gate": gate,
            }
        )
    wf.context["replay_spec_ids"] = [r["spec_id"] for r in replays]
    step.inputs = {"candidate_version_ids": version_ids, "splits": list(SEARCHABLE_SPLITS)}
    step.outputs = {"replays": replays, "replay_count": len(replays)}
    step.notice = (
        "每个新候选都在一份新的冻结协议下重放 development/validation，"
        "基线、参考集合与评分公式完全不变。holdout 仍保持锁定。"
    )


# ------------------------------------------------------------------ steps 17-18
async def _step_promotion_decision(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    spec_id = _require(wf.context, "spec_id")
    spec = store.get_spec(spec_id)
    if spec is None:
        raise ValueError("the frozen spec is no longer stored")
    gate = _gate(store, spec)
    active = store.list_skill_versions(skill_id=SKILL_ID, status="active")
    decision = wf.context.get("promotion_decision")
    step.inputs = {
        "spec_id": spec_id,
        "candidate_version_id": spec.candidate_version_id,
        "promotion_gate": gate,
        "active_version_id": active[0].version_id if active else None,
    }
    if not decision:
        step.status = "awaiting_human"
        step.outputs = {"promotion_gate": gate, "outcome": "awaiting_human"}
        step.notice = (
            "门禁已计算完毕，等待人工决定晋升 / 回滚 / 保持现状。"
            "门禁不通过时晋升会被拒绝，Active 版本保持不变。"
        )
        return
    kind = decision["decision"]
    decided_by = decision["decided_by"]
    outcome: dict[str, Any] = {"decision": kind, "decided_by": decided_by}
    if kind == "promote":
        target = decision.get("version_id") or spec.candidate_version_id
        try:
            version = promote(store, spec_id, target, decided_by)
        except PromotionRefused as exc:
            outcome.update({"outcome": "refused", "reasons": exc.reasons, "version_id": target})
        except ValueError as exc:
            outcome.update({"outcome": "invalid", "reasons": [str(exc)], "version_id": target})
        else:
            outcome.update(
                {"outcome": "promoted", "version_id": version.version_id,
                 "version_number": version.version_number}
            )
    elif kind == "rollback":
        target = decision.get("version_id")
        if not target:
            raise ValueError("rollback needs an explicit target version_id")
        try:
            version = rollback(store, target, decided_by, decision.get("reason", ""))
        except ValueError as exc:
            outcome.update({"outcome": "invalid", "reasons": [str(exc)], "version_id": target})
        else:
            outcome.update(
                {"outcome": "rolled_back", "version_id": version.version_id,
                 "version_number": version.version_number}
            )
    else:
        outcome.update({"outcome": "kept", "reason": decision.get("reason", "")})
    now_active = store.list_skill_versions(skill_id=SKILL_ID, status="active")
    outcome["active_version_id"] = now_active[0].version_id if now_active else None
    outcome["active_version_number"] = now_active[0].version_number if now_active else None
    outcome["promotion_gate"] = gate
    wf.context["promotion_outcome"] = outcome
    step.outputs = outcome
    step.notice = {
        "promoted": "候选已通过全部门禁并成为新的 Active 版本。",
        "refused": "晋升被独立门禁拒绝，Active 版本保持不变；拒绝原因已完整记录。",
        "rolled_back": "已回滚到历史版本；回滚绕过门禁但不声称任何性能提升。",
        "kept": "人工选择保持当前 Active 版本。",
        "invalid": "该决定无法执行，原因已记录。",
    }[outcome["outcome"]]


async def _step_research_dossier(store: Store, wf: WorkflowRun, step: WorkflowStep) -> None:
    run_id = _require(wf.context, "literature_run_id")
    papers = _papers_of(store, run_id)
    report = generate_report(papers, wf.topic)
    gap_ids = wf.context.get("gap_ids") or []
    gaps = [g for g in (store.get_gap(gid) for gid in gap_ids) if g]
    spec_id = wf.context.get("spec_id")
    spec = store.get_spec(spec_id) if spec_id else None
    runs = store.list_experiment_runs(spec_id=spec_id) if spec_id else []
    round_id = wf.context.get("round_id")
    record = store.get_evolution_round(round_id) if round_id else None
    versions = store.list_skill_versions(skill_id=SKILL_ID)
    active = next((v for v in versions if v.status == "active"), None)
    confirmed_cases = [
        c
        for c in store.list_benchmark_cases()
        if spec and c.case_id in spec.case_ids and c.confirmed_dois
    ]
    dossier = {
        "topic": wf.topic,
        "workflow_id": wf.workflow_id,
        "generated_at": _now(),
        "literature": {
            "run_id": run_id,
            "paper_count": len(papers),
            "extraction_mode": EXTRACTION_MODE,
            "report_id": report.report_id,
            "report_sections": [
                {
                    "id": s.id,
                    "title": s.title,
                    "kind": s.kind,
                    "paragraphs": len(s.paragraphs),
                    "paper_ids": s.paper_ids,
                }
                for s in report.sections
            ],
            "section_kind_counts": dict(Counter(s.kind for s in report.sections)),
            "caveats": report.caveats,
            "report_endpoint": "/api/literature/report",
        },
        "gaps": [
            {
                "gap_id": g.gap_id,
                "title": g.title,
                "gap_type": g.gap_type,
                "status": g.status,
                "confidence_label": g.confidence_label,
                "supporting_papers": len(g.supporting_papers),
                "counter_evidence": len(g.counter_evidence),
            }
            for g in gaps
        ],
        "accepted_gap_id": wf.context.get("accepted_gap_id"),
        "hypothesis": wf.context.get("hypothesis"),
        "hypothesis_status": "under_test",
        "experiment": {
            "spec_id": spec_id,
            "run_count": len(runs),
            "confirmed_reference_cases": len(confirmed_cases),
            "promotion_gate": wf.context.get("promotion_gate"),
            "comparisons": _comparisons(store, spec) if spec else [],
        },
        "evolution": {
            "round_id": round_id,
            "proposals": len(record.proposals) if record else 0,
            "skipped_mutations": record.skipped_mutations if record else [],
            "replay_spec_ids": wf.context.get("replay_spec_ids", []),
        },
        "skill": {
            "active_version_id": active.version_id if active else None,
            "active_version_number": active.version_number if active else None,
            "total_versions": len(versions),
            "promotion_outcome": wf.context.get("promotion_outcome"),
        },
        "acceptance_status": (
            "self_evolution_accepted"
            if wf.context.get("promotion_outcome", {}).get("outcome") == "promoted"
            else "awaiting_reference_set"
            if not confirmed_cases
            else "evolution_not_accepted"
        ),
    }
    wf.context["dossier"] = dossier
    step.inputs = {
        "literature_run_id": run_id,
        "spec_id": spec_id,
        "round_id": round_id,
        "gap_ids": gap_ids,
    }
    step.outputs = dossier
    step.notice = (
        "档案汇总的全部数字都来自已存储的真实记录；未通过的验收状态原样写出。"
    )


HANDLERS: dict[str, Callable[[Store, WorkflowRun, WorkflowStep], Awaitable[None]]] = {
    "research_topic": _step_research_topic,
    "search_planning": _step_search_planning,
    "literature_discovery": _step_literature_discovery,
    "paper_extraction": _step_paper_extraction,
    "literature_matrix": _step_literature_matrix,
    "gap_discovery": _step_gap_discovery,
    "counter_evidence_search": _step_counter_evidence_search,
    "human_approval": _step_human_approval,
    "hypothesis": _step_hypothesis,
    "experiment_spec": _step_experiment_spec,
    "baseline_execution": _step_baseline_execution,
    "candidate_execution": _step_candidate_execution,
    "independent_evaluation": _step_independent_evaluation,
    "failure_diagnosis": _step_failure_diagnosis,
    "skill_mutation": _step_skill_mutation,
    "replay_evaluation": _step_replay_evaluation,
    "promotion_decision": _step_promotion_decision,
    "research_dossier": _step_research_dossier,
}


def _rewind(wf: WorkflowRun, from_step: str) -> None:
    index = STEP_SEQUENCE.index(from_step)  # type: ignore[arg-type]
    for step in wf.steps[index:]:
        step.status = "pending"
        step.outputs = {}
        step.error = None
        step.notice = ""
        step.started_at = None
        step.finished_at = None
        for key in STEP_CONTEXT_KEYS.get(step.step_id, ()):
            wf.context.pop(key, None)
    wf.current_step = from_step  # type: ignore[assignment]
    wf.status = "running"


async def advance(
    store: Store, wf: WorkflowRun, max_steps: int = 1, from_step: str | None = None
) -> tuple[WorkflowRun, list[str]]:
    """Execute at most `max_steps` steps, stopping at a human gate or a failure."""
    if from_step:
        if from_step not in STEP_SEQUENCE:
            raise ValueError(f"unknown step {from_step!r}")
        spec_ids = [wf.context.get("spec_id"), *wf.context.get("replay_spec_ids", [])]
        holdout_used = [
            sid
            for sid in spec_ids
            if sid and store.list_experiment_runs(spec_id=sid, split="holdout")
        ]
        if holdout_used:
            raise ValueError(
                "this workflow already opened the one-shot holdout check for "
                f"{holdout_used}; rewinding would search it again"
            )
        _rewind(wf, from_step)

    executed: list[str] = []
    for _ in range(max_steps):
        pending = next((s for s in wf.steps if not s.is_terminal), None)
        if pending is None:
            wf.status = "completed"
            break
        wf.current_step = pending.step_id
        pending.status = "running"
        pending.attempts += 1
        pending.started_at = _now()
        pending.error = None
        store.save_workflow(wf)
        try:
            await HANDLERS[pending.step_id](store, wf, pending)
        except Exception as exc:
            logger.exception("workflow %s step %s failed", wf.workflow_id, pending.step_id)
            pending.status = "failed"
            pending.error = f"{type(exc).__name__}: {exc}"
            pending.finished_at = _now()
            wf.status = "failed"
            wf.updated_at = _now()
            store.save_workflow(wf)
            executed.append(pending.step_id)
            break
        if pending.status == "running":
            pending.status = "completed"
        pending.finished_at = _now()
        wf.updated_at = _now()
        executed.append(pending.step_id)
        if pending.status == "awaiting_human":
            wf.status = "awaiting_human"
            store.save_workflow(wf)
            break
        store.save_workflow(wf)
    else:
        wf.status = "running"

    if all(s.is_terminal for s in wf.steps):
        wf.status = "completed"
    wf.updated_at = _now()
    store.save_workflow(wf)
    return wf, executed


def record_approval(
    store: Store, wf: WorkflowRun, *, gap_id: str, decision: str, decided_by: str, human_note: str
) -> WorkflowRun:
    gap = store.get_gap(gap_id)
    if gap is None:
        raise ValueError(f"gap {gap_id} not found")
    if gap_id not in (wf.context.get("gap_ids") or []):
        raise ValueError(f"gap {gap_id} was not produced by this workflow")
    reviewed = store.review_gap(gap_id, decision, human_note)
    if reviewed is None:
        raise ValueError(f"gap {gap_id} could not be reviewed")
    if decision == "accepted":
        wf.context["accepted_gap_id"] = gap_id
        wf.context["approval_decided_by"] = decided_by
        wf.context["approval_note"] = human_note
    else:
        rejected = list(wf.context.get("rejected_gap_ids") or [])
        rejected.append(gap_id)
        wf.context["rejected_gap_ids"] = rejected
        if wf.context.get("accepted_gap_id") == gap_id:
            wf.context.pop("accepted_gap_id", None)
    step = wf.step("human_approval")
    step.inputs = {
        **(step.inputs or {}),
        "last_decision": {"gap_id": gap_id, "decision": decision, "decided_by": decided_by},
    }
    wf.updated_at = _now()
    store.save_workflow(wf)
    return wf


def record_decision(
    store: Store, wf: WorkflowRun, *, decision: str, decided_by: str, version_id: str | None, reason: str
) -> WorkflowRun:
    wf.context["promotion_decision"] = {
        "decision": decision,
        "decided_by": decided_by,
        "version_id": version_id,
        "reason": reason,
        "recorded_at": _now(),
    }
    step = wf.step("promotion_decision")
    if step.status == "awaiting_human":
        step.status = "pending"
    wf.status = "running"
    wf.updated_at = _now()
    store.save_workflow(wf)
    return wf