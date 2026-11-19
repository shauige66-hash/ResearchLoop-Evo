"""Deterministic orchestration of the seven gap-pipeline stages.

The LLM roles propose; this module decides what runs, in what order, and what is
persisted. Every stage writes its real outputs before the next one starts, so a
resume never re-pays for finished work:

- evidence cards are keyed by (paper_id, prompt_version) and reused verbatim;
- the provider's response cache makes an identical prompt free;
- a budget stop leaves the pipeline in `awaiting_budget` with the completed
  stages intact, and the next advance continues from the first unfinished item.

No stage is marked complete because someone asked for it. A stage completes only
after its service returned real records.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings
from ..models.gap import (
    GapEvidenceItem,
    ResearchGap,
)
from ..models.gap_pipeline import (
    CARD_FIELDS,
    PROMPT_VERSION,
    STAGE_SEQUENCE,
    CandidateGap,
    CounterSearchOutcome,
    EvidenceCard,
    GapPipelineRun,
    GapValidation,
    PipelineStage,
    PipelineStartRequest,
    StageId,
    ValidatedGap,
    new_stages,
)
from ..models.llm import LLM_NOT_CONFIGURED, NOT_CONFIGURED_REASON
from ..models.paper import Paper
from ..storage.store import Store
from .gap import (
    EXPERIMENTABILITY,
    METRIC_FAMILIES,
    SIGNAL_CUES,
    ResearchGapAnalyzer,
    _label,
    _LIMITATION_STOPWORDS,
)
from .gap_agents import GapAgents, find_verbatim_span
from .gap_validator import decide_gate, validate_gap
from .llm import LLMBudgetExhausted, LLMError, LLMNotConfigured, LLMProvider

logger = logging.getLogger(__name__)

MAX_STAGE_ATTEMPTS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_pipeline(store: Store, request: PipelineStartRequest) -> GapPipelineRun:
    settings = get_settings()
    pipeline = GapPipelineRun(
        pipeline_id=f"gpipe_{uuid.uuid4().hex[:12]}",
        topic=request.topic.strip(),
        run_id=request.run_id or "",
        workflow_id=request.workflow_id,
        paper_ids=list(request.paper_ids),
        max_papers=request.max_papers,
        max_gaps=request.max_gaps,
        run_counter_search=request.run_counter_search,
        stages=new_stages(),
        llm_budget=settings.llm_max_calls,
        provider=settings.llm_provider_label if settings.llm_configured else LLM_NOT_CONFIGURED,
        model=settings.llm_model,
        status="running" if settings.llm_configured else "not_configured",
        created_at=_now(),
        updated_at=_now(),
    )
    pipeline.notices.append(
        "LLM 负责跨论文理解与候选提出；Python 与真实检索负责验证。"
        if settings.llm_configured
        else NOT_CONFIGURED_REASON
    )
    if not settings.llm_configured:
        pipeline.stage("planner").error = NOT_CONFIGURED_REASON
        pipeline.stage("planner").status = "failed"
    store.save_gap_pipeline(pipeline)
    return pipeline


def get_pipeline(store: Store, pipeline_id: str) -> GapPipelineRun:
    pipeline = store.get_gap_pipeline(pipeline_id)
    if pipeline is None:
        raise KeyError(pipeline_id)
    return pipeline


# --------------------------------------------------------------------- selection
def select_papers(
    store: Store, pipeline: GapPipelineRun, max_papers: int
) -> tuple[list[Paper], dict[str, Any]]:
    """Deterministic selection: real abstracts only, one record per DOI.

    Ranking uses retrieval relevance, citations and recency. Nothing here asks a
    model which papers matter, and the first round is capped so the pipeline
    cannot silently expand its own scope.
    """
    if pipeline.paper_ids:
        candidates = [p for p in (store.get_paper(pid) for pid in pipeline.paper_ids) if p]
    elif pipeline.run_id:
        candidates, _ = store.list_papers(run_id=pipeline.run_id, page=1, page_size=200)
    else:
        candidates = []

    with_abstract = [p for p in candidates if (p.abstract or "").strip()]
    seen_doi: dict[str, Paper] = {}
    unique: list[Paper] = []
    dropped_no_abstract = len(candidates) - len(with_abstract)
    dropped_duplicate = 0
    for paper in with_abstract:
        doi = (paper.doi or "").strip().lower()
        if doi and doi in seen_doi:
            dropped_duplicate += 1
            continue
        if doi:
            seen_doi[doi] = paper
        unique.append(paper)

    unique.sort(
        key=lambda p: (
            -(p.relevance_score or 0.0),
            -(p.citation_count or 0),
            -(p.publication_year or 0),
            p.paper_id,
        )
    )
    selected = unique[:max_papers]
    detail = {
        "candidates": len(candidates),
        "with_abstract": len(with_abstract),
        "dropped_no_abstract": dropped_no_abstract,
        "dropped_duplicate_doi": dropped_duplicate,
        "selected": len(selected),
        "max_papers": max_papers,
        "rule": (
            "papers must have a retrieved abstract; one record per DOI; ranked by "
            "relevance, citations then year; capped at max_papers"
        ),
    }
    return selected, detail


def _detection_key(candidate: CandidateGap, papers: list[Paper]) -> str:
    """A specific retrieval key for counter-evidence, derived by Python.

    Counter-evidence must address the claim, not the topic, so the key is a term
    the claim actually turns on and that appears in the supporting abstracts.
    """
    gap_type = candidate.internal_gap_type
    text = " ".join((p.abstract or "") for p in papers).lower()
    if gap_type == "evaluation":
        families = sorted(
            fam for fam, cues in METRIC_FAMILIES.items() if any(c in text for c in cues)
        )
        if len(families) >= 2:
            return ",".join(families)
    if gap_type in SIGNAL_CUES:
        return gap_type
    words = [
        w
        for w in "".join(
            c if c.isalpha() else " "
            for c in f"{candidate.unresolved_boundary} {candidate.gap_claim}".lower()
        ).split()
        if len(w) >= 4 and w not in _LIMITATION_STOPWORDS
    ]
    counts = Counter(w for w in words if w in text)
    if not counts:
        return ""
    return max(counts.items(), key=lambda kv: (kv[1], len(kv[0])))[0]


def _to_research_gap(
    candidate: CandidateGap,
    cards: list[EvidenceCard],
    papers: list[Paper],
    *,
    gap_id: str,
    topic: str,
    run_id: str,
    pipeline_id: str,
    queries: list[str],
    detection_key: str,
) -> ResearchGap | None:
    """Project a candidate onto the existing gap record, keeping only real evidence."""
    by_id = {p.paper_id: p for p in papers}
    card_by_id = {c.paper_id: c for c in cards}
    supporting = [pid for pid in dict.fromkeys(candidate.supporting_papers) if pid in by_id]
    evidence: list[GapEvidenceItem] = []
    for ref in candidate.supporting_evidence:
        paper = by_id.get(ref.paper_id)
        if paper is None or ref.paper_id not in supporting:
            continue
        card = card_by_id.get(ref.paper_id)
        haystacks = [paper.abstract or ""]
        if card is not None and ref.field in CARD_FIELDS:
            haystacks.append(card.field(ref.field).evidence_span)
        located = next(
            (found for text in haystacks if (found := find_verbatim_span(text, ref.evidence_span))),
            None,
        )
        if located is None:
            continue
        evidence.append(
            GapEvidenceItem(
                paper_id=paper.paper_id,
                title=paper.title,
                doi=paper.doi,
                source_url=paper.source_url,
                field=ref.field,
                evidence_span=located,
                evidence_source=(
                    card.field(ref.field).evidence_source
                    if card is not None and ref.field in CARD_FIELDS
                    else "abstract"
                ),
                extraction_method="llm",
            )
        )
    if len(supporting) < 2 or not evidence:
        return None
    supported_papers = [by_id[pid] for pid in supporting]
    analyzer = ResearchGapAnalyzer(supported_papers, topic, run_id)
    gap_type = candidate.internal_gap_type
    label, rationale = _label(gap_type in ("method", "evaluation", "contradiction"), len(supporting), 0)
    description = " ".join(
        part
        for part in (
            candidate.problem_context,
            f"Already solved: {candidate.already_solved}" if candidate.already_solved else "",
            f"Unresolved boundary: {candidate.unresolved_boundary}"
            if candidate.unresolved_boundary
            else "",
            f"Why it matters: {candidate.why_it_matters}" if candidate.why_it_matters else "",
        )
        if part.strip()
    )
    return ResearchGap(
        gap_id=gap_id,
        title=candidate.gap_claim.strip()[:160],
        description=description or candidate.gap_claim.strip(),
        gap_type=gap_type,
        supporting_papers=supporting,
        supporting_evidence=evidence,
        closest_related_work=analyzer._closest(supported_papers),
        unresolved_question=candidate.candidate_research_question.strip() or candidate.gap_claim.strip(),
        experimentability=EXPERIMENTABILITY[gap_type],
        confidence_label=label,
        confidence_rationale=rationale,
        run_id=run_id,
        topic=topic,
        detection_key=detection_key,
        counter_search_queries=queries or [analyzer.counter_query(gap_type, detection_key)],
        discovery_mode="llm_pipeline",
        pipeline_id=pipeline_id,
        candidate=candidate.model_dump(),
        created_at=_now(),
    )


# ----------------------------------------------------------------- stage bodies
async def _stage_planner(
    store: Store, pipeline: GapPipelineRun, stage: PipelineStage, agents: GapAgents
) -> None:
    if pipeline.plan is not None:
        stage.outputs = {"plan": pipeline.plan.model_dump(), "reused": True}
        stage.notice = "复用已落盘的检索规划，未重复调用 LLM。"
        return
    known: list[str] = []
    if pipeline.run_id:
        run = next((r for r in store.list_runs() if r["id"] == pipeline.run_id), None)
        if run:
            meta = json.loads(run.get("meta") or "{}")
            known = [k.get("keyword", "") for k in meta.get("keywords_used", [])]
            known = [k for k in known if k] or [run.get("topic", "")]
    plan = await agents.plan(pipeline.topic, pipeline.pipeline_id, known)
    pipeline.plan = plan
    stage.outputs = {
        "plan": plan.model_dump(),
        "query_count": len(plan.all_queries()),
        "research_questions": plan.research_questions,
    }
    stage.notice = "规划由 LLM 提出；实际检索仍由 Python 执行并记录真实请求数。"


async def _stage_selection(
    store: Store, pipeline: GapPipelineRun, stage: PipelineStage, agents: GapAgents
) -> None:
    papers, detail = select_papers(store, pipeline, pipeline.max_papers)
    if not papers:
        raise ValueError(
            "no retrieved paper with an abstract is available for this run; the pipeline "
            "will not analyse papers it never retrieved"
        )
    pipeline.selected_paper_ids = [p.paper_id for p in papers]
    stage.outputs = detail
    stage.notice = (
        f"确定性筛选 {len(papers)} 篇（上限 {pipeline.max_papers}）；"
        "只有摘要可用，不声称阅读全文。"
    )


async def _stage_literature_analysis(
    store: Store, pipeline: GapPipelineRun, stage: PipelineStage, agents: GapAgents
) -> None:
    cards: list[EvidenceCard] = []
    grounded = 0
    rejected = 0
    for paper_id in pipeline.selected_paper_ids:
        paper = store.get_paper(paper_id)
        if paper is None:
            continue
        card = await agents.analyze_paper(paper, pipeline.pipeline_id)
        cards.append(card)
        grounded += len(card.grounded_fields)
        rejected += len(card.rejected_fields)
        # Checkpoint after every paper: a budget stop here must not lose the cards
        # that were already paid for.
        stage.outputs = {
            "cards": len(cards),
            "grounded_fields": grounded,
            "rejected_fields": rejected,
            "card_paper_ids": [c.paper_id for c in cards],
            "from_cache": sum(1 for c in cards if c.from_cache),
            "evidence_source": "abstract",
        }
        store.save_gap_pipeline(pipeline)
    if not cards:
        raise ValueError("no evidence card could be produced from the selected papers")
    stage.outputs = {
        "cards": len(cards),
        "grounded_fields": grounded,
        "rejected_fields": rejected,
        "card_paper_ids": [c.paper_id for c in cards],
        "from_cache": sum(1 for c in cards if c.from_cache),
        "evidence_source": "abstract",
        "notice": "每个 span 都由 Python 在真实摘要中逐字复核，找不到即丢弃。",
    }
    stage.notice = f"{len(cards)} 张证据卡，{grounded} 个字段通过逐字复核，{rejected} 个被拒绝。"


async def _stage_gap_analysis(
    store: Store, pipeline: GapPipelineRun, stage: PipelineStage, agents: GapAgents
) -> None:
    cards = _cards_of(store, pipeline)
    papers = _papers_of_selected(store, pipeline)
    output = await agents.synthesize(
        pipeline.topic, cards, pipeline.max_gaps, pipeline.pipeline_id
    )
    pipeline.synthesis = output.synthesis
    pipeline.gaps = [ValidatedGap(candidate=c) for c in output.candidates]
    analyzer = ResearchGapAnalyzer(papers, pipeline.topic, pipeline.run_id)
    persisted: list[str] = []
    unprojectable = 0
    for index, item in enumerate(pipeline.gaps):
        detection_key = _detection_key(item.candidate, papers)
        gap_type = item.candidate.internal_gap_type
        gap = _to_research_gap(
            item.candidate,
            cards,
            papers,
            gap_id=f"gap_{pipeline.pipeline_id[6:]}_{index}",
            topic=pipeline.topic,
            run_id=pipeline.run_id,
            pipeline_id=pipeline.pipeline_id,
            queries=[analyzer.counter_query(gap_type, detection_key)],
            detection_key=detection_key,
        )
        if gap is None:
            unprojectable += 1
            item.counter = CounterSearchOutcome(
                status="NOT_RUN",
                detection_key=detection_key,
                notice=(
                    "the candidate could not be projected onto a gap record: fewer than "
                    "two retrieved supporting papers or no verbatim evidence survived"
                ),
            )
        else:
            store.save_gap(gap)
            item.gap_id = gap.gap_id
            persisted.append(gap.gap_id)
        store.save_gap_pipeline(pipeline)
    stage.outputs = {
        "synthesis": output.synthesis.model_dump(),
        "candidate_count": len(output.candidates),
        "candidates": [c.model_dump() for c in output.candidates],
        "persisted_gap_ids": persisted,
        "unprojectable_candidates": unprojectable,
    }
    stage.notice = (
        f"LLM 提出 {len(output.candidates)} 个候选，其中 {len(persisted)} 个带有可复核证据并落盘；"
        "它们是假设，尚未通过 Python 验证。"
        if output.candidates
        else "LLM 未提出候选；不编造空白。"
    )


async def _stage_gap_critic(
    store: Store, pipeline: GapPipelineRun, stage: PipelineStage, agents: GapAgents
) -> None:
    cards = _cards_of(store, pipeline)
    reviewed = 0
    for index, item in enumerate(pipeline.gaps):
        if item.critique is not None:
            reviewed += 1
            continue
        item.critique = await agents.critique(
            item.candidate, cards, index, pipeline.pipeline_id
        )
        if item.gap_id:
            gap = store.get_gap(item.gap_id)
            if gap is not None:
                gap.critique = item.critique.model_dump()
                gap.updated_at = _now()
                store.save_gap(gap)
        reviewed += 1
        stage.outputs = {"reviewed": reviewed, "total": len(pipeline.gaps)}
        store.save_gap_pipeline(pipeline)
    stage.outputs = {
        "reviewed": reviewed,
        "total": len(pipeline.gaps),
        "withheld_from_critic": [
            "problem_context",
            "already_solved",
            "why_it_matters",
            "uncertainties",
            "proposer novelty_risk",
            "proposer novelty_rationale",
        ],
        "score_scale": "0..5 integers, never percentages",
    }
    stage.notice = "评审 Agent 只看到 claim 与引用证据，看不到提出者的内部推理。"


async def _stage_counter_evidence(
    store: Store, pipeline: GapPipelineRun, stage: PipelineStage, agents: GapAgents
) -> None:
    if not pipeline.run_counter_search:
        for item in pipeline.gaps:
            item.counter = CounterSearchOutcome(
                status="NOT_RUN", notice="counter-evidence search was disabled for this run"
            )
        stage.outputs = {"searched": 0, "disabled": True}
        stage.notice = "本次运行关闭了反证检索；门禁不会把'未检索'当成'无反证'。"
        return

    papers = _papers_of_selected(store, pipeline)
    analyzer = ResearchGapAnalyzer(papers, pipeline.topic, pipeline.run_id)
    searched = 0
    found_total = 0
    for item in pipeline.gaps:
        if item.counter.status != "NOT_RUN":
            searched += 1
            continue
        gap = store.get_gap(item.gap_id) if item.gap_id else None
        if gap is None:
            continue
        queries: list[str] = []
        query_source = "deterministic"
        try:
            queries = await agents.counter_queries(
                pipeline.topic, item.candidate, pipeline.pipeline_id
            )
            if queries:
                query_source = "llm"
                gap.counter_search_queries = queries
        except LLMNotConfigured:
            raise
        except LLMBudgetExhausted:
            raise
        except LLMError as exc:
            logger.warning("counter query generation failed: %s", exc)
        updated = await analyzer.add_counter_evidence([gap], top_k=10)
        gap = updated[0]
        scope = gap.counter_search_scope
        errors = gap.counter_search_errors
        prior_art = [
            {
                "paper_id": c.paper_id,
                "title": c.title,
                "doi": c.doi,
                "source": c.source,
                "source_url": c.source_url,
                "publication_year": c.publication_year,
                "matched_query": c.matched_query,
                "matched_cue": c.matched_cue,
                "evidence_span": c.evidence_span,
                "why_relevant": c.why_relevant,
            }
            for c in gap.counter_evidence
        ]
        if errors and not scope.get("papers_retrieved"):
            status = "COUNTER_SEARCH_FAILED"
        elif prior_art:
            status = "COUNTER_EVIDENCE_FOUND"
        else:
            status = "NO_COUNTER_EVIDENCE_FOUND"
        item.counter = CounterSearchOutcome(
            status=status,
            queries=gap.counter_search_queries,
            detection_key=gap.detection_key,
            sources=scope.get("sources", []),
            requests_made=scope.get("requests_made", 0),
            cache_hits=scope.get("cache_hits", 0),
            papers_retrieved=scope.get("papers_retrieved", 0),
            rejected_as_not_addressing_claim=scope.get("rejected_as_not_addressing_claim", 0),
            prior_art=prior_art,
            errors=errors,
            query_source=query_source,
            notice=(
                "搜索失败不等于没有反证。"
                if status == "COUNTER_SEARCH_FAILED"
                else "在当前检索范围内未找到针对该 claim 的反证；这不等于反证不存在。"
                if status == "NO_COUNTER_EVIDENCE_FOUND"
                else "检索到针对该 claim 的真实 prior art，novelty_risk 由 Python 上调。"
            ),
        )
        gap.counter_status = status
        gap.prior_art = prior_art
        store.save_gap(gap)
        searched += 1
        found_total += len(prior_art)
        stage.outputs = {"searched": searched, "prior_art_found": found_total}
        store.save_gap_pipeline(pipeline)
    stage.outputs = {
        "searched": searched,
        "total": len(pipeline.gaps),
        "prior_art_found": found_total,
        "statuses": [item.counter.status for item in pipeline.gaps],
    }
    stage.notice = "反证检索使用真实三源检索；只有针对 claim 的论文才计为 prior art。"


async def _stage_validation(
    store: Store, pipeline: GapPipelineRun, stage: PipelineStage, agents: GapAgents
) -> None:
    cards = _cards_of(store, pipeline)
    settings = get_settings()
    accepted = 0
    review = 0
    rejected = 0
    for index, item in enumerate(pipeline.gaps):
        item.validation = validate_gap(
            store,
            item.candidate,
            cards,
            item.critique,
            item.counter,
            gap_index=index,
            gate=settings.gap_gate,
        )
        item.gate = decide_gate(
            item.validation, item.critique, gap_index=index, gate=settings.gap_gate
        )
        if item.gap_id:
            gap = store.get_gap(item.gap_id)
            if gap is not None:
                gap.status = item.gate.status
                gap.critique = item.critique.model_dump() if item.critique else {}
                gap.validation = item.validation.model_dump()
                gap.gate = item.gate.model_dump()
                gap.novelty_risk = item.validation.novelty_risk
                gap.counter_status = item.counter.status
                gap.prior_art = item.counter.prior_art
                positive = gap.gap_type in ("method", "evaluation", "contradiction")
                label, rationale = _label(
                    positive,
                    item.validation.unique_supporting_papers,
                    len(item.counter.prior_art),
                )
                gap.confidence_label = label
                gap.confidence_rationale = rationale
                gap.updated_at = _now()
                store.save_gap(gap)
        if item.gate.status == "accepted":
            accepted += 1
        elif item.gate.status == "rejected":
            rejected += 1
        else:
            review += 1
        store.save_gap_pipeline(pipeline)
    stage.outputs = {
        "validated": len(pipeline.gaps),
        "accepted": accepted,
        "needs_human_review": review,
        "rejected": rejected,
        "gap_ids": [item.gap_id for item in pipeline.gaps if item.gap_id],
        "gate": settings.gap_gate,
    }
    stage.notice = (
        f"Python 独立验证 {len(pipeline.gaps)} 个候选：accepted {accepted} / "
        f"needs_human_review {review} / rejected {rejected}。通过门禁只代表达到当前检索范围内的证据阈值。"
    )


HANDLERS = {
    "planner": _stage_planner,
    "selection": _stage_selection,
    "literature_analysis": _stage_literature_analysis,
    "gap_analysis": _stage_gap_analysis,
    "gap_critic": _stage_gap_critic,
    "counter_evidence": _stage_counter_evidence,
    "validation": _stage_validation,
}


def _cards_of(store: Store, pipeline: GapPipelineRun) -> list[EvidenceCard]:
    cards = []
    for paper_id in pipeline.selected_paper_ids:
        card = store.get_evidence_card(paper_id, PROMPT_VERSION)
        if card is not None:
            cards.append(card)
    return cards


def _papers_of_selected(store: Store, pipeline: GapPipelineRun) -> list[Paper]:
    return [
        p
        for p in (store.get_paper(pid) for pid in pipeline.selected_paper_ids)
        if p is not None
    ]


def rewind(pipeline: GapPipelineRun, from_stage: StageId) -> None:
    """Reset a stage and everything after it, clearing the outputs it owns."""
    index = STAGE_SEQUENCE.index(from_stage)
    for stage in pipeline.stages[index:]:
        stage.status = "pending"
        stage.outputs = {}
        stage.error = None
        stage.notice = ""
        stage.started_at = None
        stage.finished_at = None
    if index <= STAGE_SEQUENCE.index("planner"):
        pipeline.plan = None
    if index <= STAGE_SEQUENCE.index("selection"):
        pipeline.selected_paper_ids = []
    if index <= STAGE_SEQUENCE.index("gap_analysis"):
        pipeline.synthesis = None
        pipeline.gaps = []
    elif index <= STAGE_SEQUENCE.index("gap_critic"):
        for item in pipeline.gaps:
            item.critique = None
            item.counter = CounterSearchOutcome()
            item.validation = GapValidation()
            item.gap_id = None
    elif index <= STAGE_SEQUENCE.index("counter_evidence"):
        for item in pipeline.gaps:
            item.counter = CounterSearchOutcome()
            item.validation = GapValidation()
            item.gap_id = None
    elif index <= STAGE_SEQUENCE.index("validation"):
        for item in pipeline.gaps:
            item.validation = GapValidation()
    pipeline.current_stage = from_stage
    pipeline.status = "running"


async def advance(
    store: Store,
    pipeline: GapPipelineRun,
    *,
    max_stages: int = len(STAGE_SEQUENCE),
    from_stage: StageId | None = None,
    through_stage: StageId | None = None,
    provider: LLMProvider | None = None,
) -> tuple[GapPipelineRun, list[str]]:
    """Run at most `max_stages` stages, stopping at the first real obstacle."""
    if from_stage is not None:
        rewind(pipeline, from_stage)
    agents = GapAgents(store, provider)
    settings = get_settings()
    pipeline.llm_budget = settings.llm_max_calls
    pipeline.provider = (
        settings.llm_provider_label if settings.llm_configured else LLM_NOT_CONFIGURED
    )
    pipeline.model = settings.llm_model
    executed: list[str] = []
    last = STAGE_SEQUENCE.index(through_stage) if through_stage else len(STAGE_SEQUENCE) - 1

    for stage in pipeline.stages:
        if len(executed) >= max_stages:
            break
        if stage.is_terminal:
            continue
        if STAGE_SEQUENCE.index(stage.stage_id) > last:
            break
        if stage.status == "failed" and stage.attempts >= MAX_STAGE_ATTEMPTS:
            pipeline.status = "failed"
            pipeline.notices.append(
                f"stage {stage.stage_id} failed {stage.attempts} times; inspect the LLM audit "
                "trail before retrying"
            )
            break
        stage.status = "running"
        stage.attempts += 1
        stage.started_at = _now()
        stage.error = None
        pipeline.current_stage = stage.stage_id
        pipeline.status = "running"
        store.save_gap_pipeline(pipeline)
        try:
            await HANDLERS[stage.stage_id](store, pipeline, stage, agents)
        except LLMNotConfigured as exc:
            stage.status = "failed"
            stage.error = str(exc)
            stage.finished_at = _now()
            # Being unconfigured or out of budget is not a failed attempt: a resume
            # after the operator fixes either must not hit the retry ceiling.
            stage.attempts -= 1
            pipeline.status = "not_configured"
            pipeline.notices.append(NOT_CONFIGURED_REASON)
            store.save_gap_pipeline(pipeline)
            break
        except LLMBudgetExhausted as exc:
            stage.status = "failed"
            stage.error = str(exc)
            stage.finished_at = _now()
            stage.attempts -= 1
            pipeline.status = "awaiting_budget"
            pipeline.notices.append(str(exc))
            store.save_gap_pipeline(pipeline)
            break
        except Exception as exc:
            stage.status = "failed"
            stage.error = f"{type(exc).__name__}: {exc}"
            stage.finished_at = _now()
            pipeline.status = "failed"
            logger.warning("gap pipeline stage %s failed: %s", stage.stage_id, exc)
            store.save_gap_pipeline(pipeline)
            break
        stage.status = "completed"
        stage.finished_at = _now()
        executed.append(stage.stage_id)
        pipeline.current_stage = stage.stage_id
        store.save_gap_pipeline(pipeline)

    summary = agents.provider.usage_summary()
    pipeline.llm_calls_used = summary.calls_used
    pipeline.llm_cache_hits = summary.cache_hits
    if pipeline.status == "running":
        remaining = [
            s.stage_id
            for s in pipeline.stages
            if not s.is_terminal and STAGE_SEQUENCE.index(s.stage_id) <= last
        ]
        if not remaining:
            pipeline.status = "completed"
    pipeline.updated_at = _now()
    store.save_gap_pipeline(pipeline)
    return pipeline, executed