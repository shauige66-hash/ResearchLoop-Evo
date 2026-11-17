"""Experience-driven evolution of the literature search strategy.

The loop is: read what the executed trials actually did -> name the failures with
the numbers that justify them -> propose at most three cost-affordable mutations.
It stops there. Judging a candidate is the independent evaluator's job, and
activating one is a gated human decision.

Three rules keep the loop honest:
- mutations are derived from development trials only;
- a candidate's query count is bounded by the *measured* baseline request count
  times the promotion ceiling, so a proposal cannot be born already over budget;
- when the evidence needed for a mutation does not exist (no confirmed reference
  set, for instance), the mutation is skipped with a stated reason instead of
  being filled in with plausible-looking guesses.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from ..config import get_settings
from ..models.evolution import (
    EVOLVABLE_COMPONENTS,
    FROZEN_FIX,
    MAX_CANDIDATES_PER_ROUND,
    CandidateProposal,
    EvolutionRound,
    FailureDiagnosis,
    FailureType,
    SourceTally,
    StrategyChange,
    TrialExperience,
)
from ..models.experiment import ExperimentRun, ExperimentSpec
from ..models.skill import SKILL_ID, SearchStrategy, SkillVersion, plan_queries
from ..storage.store import Store
from .evaluator import MAX_REQUEST_RATIO
from .experiment import effective_years

logger = logging.getLogger(__name__)

_WORDS = re.compile(r"[a-zA-Z]{4,}")
_SALIENCE_STOPWORDS = frozenset("""
with from that this these those have been were their which what when where while
about into over under between across using used based toward towards study studies
paper papers results result method methods approach approaches novel propose
proposed present presents evaluation evaluate analysis review survey
""".split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def salient_terms(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for word in _WORDS.findall(text.lower()):
        if word in _SALIENCE_STOPWORDS or word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out


def _snapshot_payload(run: ExperimentRun) -> dict | None:
    if not run.raw_snapshot_path:
        return None
    path = Path(run.raw_snapshot_path)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("unreadable snapshot for run %s: %s", run.run_id, exc)
        return None


def collect_experiences(store: Store, spec: ExperimentSpec) -> list[TrialExperience]:
    """Reduce every stored run of this spec to the signals a diagnosis may use."""
    cases = {c.case_id: c for c in store.list_benchmark_cases() if c.case_id in spec.case_ids}
    out: list[TrialExperience] = []
    for run in store.list_experiment_runs(spec_id=spec.spec_id):
        case = cases.get(run.case_id)
        if case is None:
            continue
        payload = _snapshot_payload(run)
        papers = ((payload or {}).get("response") or {}).get("papers") or []
        # Seed every frozen source with zero: a source that contributed nothing is
        # absent from the counter, and that absence is exactly the signal we need.
        counts: Counter[str] = Counter({source: 0 for source in spec.sources})
        counts.update(p.get("source", "unknown") for p in papers)
        tallies = [
            SourceTally(source=source, paper_count=count)
            for source, count in sorted(counts.items())
        ]
        # Reference titles and years are ground truth: only development trials may
        # see them, otherwise a mutation would be tuned on validation material.
        is_dev = case.split == "development"
        confirmed = [r for r in case.references if r.is_confirmed] if is_dev else []
        year_from, year_to = effective_years(spec, run.skill_snapshot)
        evaluation = run.evaluation
        out.append(
            TrialExperience(
                run_id=run.run_id,
                spec_id=run.spec_id,
                case_id=run.case_id,
                topic=case.topic,
                query=case.query,
                split=case.split,
                arm=run.arm,
                skill_version_id=run.skill_version_id,
                queries_used=list(run.queries_used),
                status=run.status,
                reference_status=case.reference_status,
                unique_paper_count=run.unique_paper_count,
                top_k=spec.top_k,
                api_request_count=run.api_request_count,
                cache_hits=run.cache_hits,
                execution_time_ms=run.execution_time_ms,
                coverage_at_k=evaluation.coverage_at_k if evaluation else None,
                hit_references=list(evaluation.hit_references) if evaluation else [],
                missed_references=list(evaluation.missed_references) if evaluation else [],
                source_errors=[dict(e) for e in run.source_errors],
                source_tallies=tallies,
                source_priority=list(run.skill_snapshot.source_priority),
                retrieved_titles=[p.get("title") or "" for p in papers],
                reference_titles=[r.title for r in confirmed if r.title],
                reference_years=[r.publication_year for r in confirmed if r.publication_year],
                effective_year_from=year_from,
                effective_year_to=year_to,
                snapshot_available=payload is not None,
            )
        )
    return out


def _query_vocabulary(exp: TrialExperience) -> set[str]:
    return {t for q in exp.queries_used for t in salient_terms(q)}


def _real_errors(exp: TrialExperience) -> list[dict]:
    return [e for e in exp.source_errors if e.get("source") != "budget"]


def diagnose(exp: TrialExperience) -> list[FailureDiagnosis]:
    """Name failures from measured signals only. No signal, no diagnosis."""
    out: list[FailureDiagnosis] = []

    def add(kind: FailureType, evidence: dict, rationale: str, component: str) -> None:
        out.append(
            FailureDiagnosis(
                failure_type=kind,
                run_id=exp.run_id,
                case_id=exp.case_id,
                split=exp.split,
                evidence=evidence,
                rationale=rationale,
                suggested_component=component,
            )
        )

    errors = _real_errors(exp)
    if errors:
        add(
            "api_failure",
            {"errors": errors, "sources": sorted({e.get("source", "?") for e in errors})},
            f"{len(errors)} retrieval request(s) failed at the API level; this is a transport "
            "failure, not evidence that the query wording is wrong.",
            "source_priority",
        )

    if exp.status == "failed":
        return out

    if exp.unique_paper_count < exp.top_k:
        add(
            "query_too_narrow",
            {
                "unique_paper_count": exp.unique_paper_count,
                "top_k": exp.top_k,
                "queries_used": exp.queries_used,
            },
            f"the APIs returned {exp.unique_paper_count} unique papers against a page size of "
            f"{exp.top_k}, so the query is more specific than the available literature.",
            "query_templates",
        )

    if exp.source_tallies:
        present = {t.source for t in exp.source_tallies if t.paper_count > 0}
        silent = [t.source for t in exp.source_tallies if t.paper_count == 0]
        if present and silent:
            first = exp.source_priority[0] if exp.source_priority else None
            misaligned = first in silent
            consequence = (
                f"the highest-priority source {first!r} is one of the silent ones, so tie-break "
                "order works against this case"
                if misaligned
                else f"the productive source is already first in priority ({first!r}), so "
                "reordering alone cannot recover the missing coverage"
            )
            add(
                "source_coverage_insufficient",
                {
                    "tallies": [t.model_dump() for t in exp.source_tallies],
                    "silent_sources": silent,
                    "first_priority_source": first,
                    "priority_misaligned": misaligned,
                },
                f"{', '.join(silent)} contributed no paper to the retained top-k while "
                f"{', '.join(sorted(present))} did; {consequence}.",
                "source_priority",
            )

    vocabulary = _query_vocabulary(exp)
    if exp.retrieved_titles and vocabulary:
        title_words = {t for title in exp.retrieved_titles for t in salient_terms(title)}
        matched = sorted(vocabulary & title_words)
        ratio = len(matched) / len(vocabulary)
        if ratio < 0.34:
            add(
                "wrong_research_terminology",
                {
                    "query_terms": sorted(vocabulary),
                    "matched_terms": matched,
                    "overlap_ratio": round(ratio, 3),
                    "titles_sampled": len(exp.retrieved_titles),
                },
                f"only {len(matched)} of {len(vocabulary)} query terms appear anywhere in the "
                f"{len(exp.retrieved_titles)} retrieved titles (overlap {ratio:.0%}); the query "
                "uses wording the literature does not use.",
                "query_templates",
            )

    if exp.reference_status != "confirmed":
        return out

    missed = set(exp.missed_references)
    absent_terms: Counter[str] = Counter()
    for title in exp.reference_titles:
        for term in salient_terms(title):
            if term not in vocabulary:
                absent_terms[term] += 1
    if missed and absent_terms:
        top = absent_terms.most_common(5)
        add(
            "missing_synonym",
            {
                "missed_references": sorted(missed),
                "absent_reference_terms": [{"term": t, "references": n} for t, n in top],
            },
            f"{len(missed)} confirmed reference(s) were missed and their titles use "
            f"{len(absent_terms)} salient terms absent from every query, most often "
            f"{top[0][0]!r}.",
            "domain_synonyms",
        )

    if exp.reference_years:
        outside = [
            y
            for y in exp.reference_years
            if (exp.effective_year_from is not None and y < exp.effective_year_from)
            or (exp.effective_year_to is not None and y > exp.effective_year_to)
        ]
        if outside:
            add(
                "time_filter_too_restrictive",
                {
                    "excluded_reference_years": sorted(set(outside)),
                    "effective_year_from": exp.effective_year_from,
                    "effective_year_to": exp.effective_year_to,
                },
                f"{len(outside)} confirmed reference(s) were published outside the effective "
                f"year window [{exp.effective_year_from}, {exp.effective_year_to}], so no query "
                "wording can retrieve them. Widening the frozen window is a human decision.",
                FROZEN_FIX,
            )

    return out


def affordable_budget(
    baseline_requests: int, source_count: int, spec_ceiling: int
) -> tuple[int, int]:
    """Requests and queries a candidate may spend without breaching the cost gate.

    Uses the measured baseline cost, so a proposal is never born already over the
    promotion ceiling. Cache hits are included by the caller.
    """
    sources = max(1, source_count)
    affordable = min(int(baseline_requests * MAX_REQUEST_RATIO), spec_ceiling)
    affordable = max(sources, affordable)
    return affordable, max(1, affordable // sources)


def _change(component: str, before: object, after: object) -> StrategyChange:
    return StrategyChange(component=component, before=before, after=after)


def _reference_term_candidates(experiences: list[TrialExperience]) -> list[str]:
    """Salient terms from confirmed development reference titles, most frequent first."""
    dev = [e for e in experiences if e.split == "development" and e.reference_status == "confirmed"]
    vocabulary = {t for e in dev for t in _query_vocabulary(e)}
    counts: Counter[str] = Counter()
    for exp in dev:
        for title in exp.reference_titles:
            for term in salient_terms(title):
                if term not in vocabulary:
                    counts[term] += 1
    return [t for t, _ in counts.most_common()]


def _topic_term_candidates(experiences: list[TrialExperience]) -> list[str]:
    dev = [e for e in experiences if e.split == "development"]
    counts: Counter[str] = Counter()
    for exp in dev:
        vocabulary = _query_vocabulary(exp)
        for term in salient_terms(exp.topic):
            if term not in vocabulary:
                counts[term] += 1
    return [t for t, _ in counts.most_common()]


def _productive_source_order(experiences: list[TrialExperience]) -> list[str]:
    """Rank sources by how many retained papers they actually contributed."""
    dev = [e for e in experiences if e.split == "development"]
    totals: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    for exp in dev:
        for tally in exp.source_tallies:
            totals[tally.source] += tally.paper_count
        for error in _real_errors(exp):
            failures[error.get("source", "?")] += 1
    if not totals:
        return []
    return sorted(totals, key=lambda s: (-totals[s], failures[s], s))


class CandidateProposer:
    """Deterministic by default. Every proposal cites the trials that motivated it."""

    def __init__(
        self,
        parent: SkillVersion,
        spec: ExperimentSpec,
        experiences: list[TrialExperience],
        diagnoses: list[FailureDiagnosis],
        max_candidates: int = MAX_CANDIDATES_PER_ROUND,
    ) -> None:
        self.parent = parent
        self.spec = spec
        self.experiences = [e for e in experiences if e.split == "development"]
        self.diagnoses = [d for d in diagnoses if d.split == "development"]
        self.max_candidates = min(max_candidates, MAX_CANDIDATES_PER_ROUND)
        baseline = [e for e in self.experiences if e.arm == "baseline"]
        self.baseline_requests = (
            max(e.total_api_queries for e in baseline) if baseline else 0
        )
        self.affordable_requests, self.affordable_queries = affordable_budget(
            self.baseline_requests, len(spec.sources), spec.max_api_requests
        )
        self.skipped: list[dict] = []

    def _trials(self, kinds: set[FailureType]) -> list[str]:
        matched = sorted({d.run_id for d in self.diagnoses if d.failure_type in kinds})
        # A mutation may also be grounded in reference vocabulary rather than in a
        # diagnosed failure; it still has to name the trials it read.
        return matched or sorted({e.run_id for e in self.experiences})

    def _kinds(self) -> set[FailureType]:
        return {d.failure_type for d in self.diagnoses}

    def _build(
        self,
        strategy: SearchStrategy,
        description: str,
        kinds: set[FailureType],
        changes: list[StrategyChange],
        grounding: str,
    ) -> CandidateProposal:
        queries = plan_queries(strategy, self.experiences[0].topic, self.experiences[0].query)
        projected = len(queries) * max(1, len(self.spec.sources))
        return CandidateProposal(
            version_id=f"skillv_{uuid.uuid4().hex[:12]}",
            parent_version=self.parent.version_id,
            version_number=0,
            mutation_description=description,
            source_trials=self._trials(kinds),
            addressed_failures=sorted(kinds & self._kinds()),
            changes=changes,
            strategy=strategy,
            created_at=_now(),
            projected_query_count=len(queries),
            projected_api_requests=projected,
            projected_request_ratio=(
                round(projected / self.baseline_requests, 3) if self.baseline_requests else None
            ),
            grounding=grounding,
        )

    def _budgeted(self, strategy: SearchStrategy) -> SearchStrategy:
        strategy.retrieval_budget.max_keywords = self.affordable_queries
        strategy.retrieval_budget.top_k = self.spec.top_k
        strategy.retrieval_budget.max_api_requests = self.spec.max_api_requests
        return strategy

    def propose(self) -> list[CandidateProposal]:
        if not self.experiences:
            self.skipped.append(
                {
                    "mutation": "all",
                    "reason": "no development trial has been executed for this spec yet; "
                    "run the development split before proposing a mutation",
                }
            )
            return []

        proposals: list[CandidateProposal] = []
        kinds = self._kinds()
        reformulation_kinds: set[FailureType] = {
            "query_too_narrow",
            "missing_synonym",
            "wrong_research_terminology",
        }

        ref_terms = _reference_term_candidates(self.experiences)
        if ref_terms:
            term = ref_terms[0]
            strategy = self._budgeted(self.parent.strategy.model_copy(deep=True))
            before = list(strategy.query_templates)
            strategy.query_templates = [f"{{query}} {term}"]
            proposals.append(
                self._build(
                    strategy,
                    f"Substitute the reference-grounded term {term!r} into the query template. "
                    f"The budget affords {self.affordable_queries} query/queries, so the term "
                    "replaces the wording instead of adding a second search.",
                    reformulation_kinds,
                    [_change("query_templates", before, list(strategy.query_templates))],
                    "term frequency in human-confirmed development reference titles",
                )
            )
        else:
            self.skipped.append(
                {
                    "mutation": "reference_grounded_reformulation",
                    "reason": "no human-confirmed reference set on the development split, so "
                    "there is no ground-truth vocabulary to derive a term from; refusing to "
                    "invent one",
                }
            )

        topic_terms = _topic_term_candidates(self.experiences)
        if topic_terms:
            term = topic_terms[0]
            strategy = self._budgeted(self.parent.strategy.model_copy(deep=True))
            before_templates = list(strategy.query_templates)
            before_synonyms = {k: list(v) for k, v in strategy.domain_synonyms.items()}
            before_rules = list(strategy.keyword_expansion_rules)
            strategy.query_templates = [f"{{query}} {term}"]
            strategy.domain_synonyms[term] = [t for t in topic_terms[1:4]]
            if "domain_synonyms" not in strategy.keyword_expansion_rules:
                strategy.keyword_expansion_rules.append("domain_synonyms")
            changes = [
                _change("query_templates", before_templates, list(strategy.query_templates)),
                _change(
                    "domain_synonyms",
                    before_synonyms,
                    {k: list(v) for k, v in strategy.domain_synonyms.items()},
                ),
                _change(
                    "keyword_expansion_rules", before_rules, list(strategy.keyword_expansion_rules)
                ),
            ]
            proposals.append(
                self._build(
                    strategy,
                    f"Cover the topic term {term!r} that the original question omits, and record "
                    "its sibling terms as domain synonyms for future rounds. Synonyms are "
                    "substituted into the single affordable query rather than appended.",
                    reformulation_kinds,
                    changes,
                    "topic terms of development cases absent from the executed queries",
                )
            )
        else:
            self.skipped.append(
                {
                    "mutation": "topic_coverage_reformulation",
                    "reason": "every salient topic term already appears in the executed queries",
                }
            )

        order = _productive_source_order(self.experiences)
        if order and order != list(self.parent.strategy.source_priority):
            strategy = self._budgeted(self.parent.strategy.model_copy(deep=True))
            before = list(strategy.source_priority)
            strategy.source_priority = order + [s for s in before if s not in order]
            proposals.append(
                self._build(
                    strategy,
                    "Reorder source priority by measured contribution to the retained top-k, "
                    "pushing persistently failing sources last. The frozen source set is "
                    "unchanged; only tie-break order moves. Retrieval cost is identical.",
                    {"source_coverage_insufficient", "api_failure"},
                    [_change("source_priority", before, list(strategy.source_priority))],
                    "per-source paper tallies and API errors from development snapshots",
                )
            )
        elif not order:
            self.skipped.append(
                {
                    "mutation": "source_priority_reorder",
                    "reason": "no development snapshot is available to measure per-source "
                    "contribution",
                }
            )
        else:
            self.skipped.append(
                {
                    "mutation": "source_priority_reorder",
                    "reason": "the parent's source priority already matches the measured "
                    "contribution order; a no-op mutation is not proposed",
                }
            )

        if kinds & {"time_filter_too_restrictive"}:
            self.skipped.append(
                {
                    "mutation": "year_window_widening",
                    "reason": "the excluded reference years fall outside the frozen spec window; "
                    "a candidate may only narrow filters, so this needs a new spec authored "
                    "by a human",
                }
            )

        return proposals[: self.max_candidates]


def _persist_proposal(store: Store, proposal: CandidateProposal, number: int) -> CandidateProposal:
    version = SkillVersion(
        version_id=proposal.version_id,
        skill_id=SKILL_ID,
        version_number=number,
        parent_version=proposal.parent_version,
        strategy=proposal.strategy,
        mutation_description=proposal.mutation_description,
        source_trials=proposal.source_trials,
        created_at=proposal.created_at,
        status="candidate",
        created_by="proposer",
    )
    store.save_skill_version(version)
    store.add_skill_event(
        version.version_id,
        "proposed",
        {
            "parent_version": proposal.parent_version,
            "addressed_failures": proposal.addressed_failures,
            "source_trials": proposal.source_trials,
            "grounding": proposal.grounding,
            "projected_request_ratio": proposal.projected_request_ratio,
            "changes": [c.model_dump() for c in proposal.changes],
        },
    )
    return proposal.model_copy(update={"version_number": number})


async def run_evolution_round(
    store: Store,
    spec: ExperimentSpec,
    max_candidates: int = MAX_CANDIDATES_PER_ROUND,
    use_llm: bool = False,
) -> EvolutionRound:
    """Collect real experience, diagnose it, and register up to three candidates."""
    parent = store.get_skill_version(spec.candidate_version_id)
    if parent is None:
        raise ValueError(f"candidate version {spec.candidate_version_id} not found")

    experiences = collect_experiences(store, spec)
    diagnoses = [d for exp in experiences for d in diagnose(exp)]
    proposer = CandidateProposer(parent, spec, experiences, diagnoses, max_candidates)
    proposals = proposer.propose()

    mode = "deterministic"
    skip_reason = ""
    if use_llm:
        extra, skip_reason = await llm_proposal(store, proposer)
        if extra is not None:
            mode = "llm"
            proposals = (proposals + [extra])[:max_candidates]
    elif not get_settings().llm_configured:
        skip_reason = (
            "no LLM provider is configured on the server; the deterministic proposer ran instead"
        )

    persisted: list[CandidateProposal] = []
    for proposal in proposals:
        persisted.append(
            _persist_proposal(store, proposal, store.next_version_number(SKILL_ID))
        )

    round_record = EvolutionRound(
        round_id=f"evor_{uuid.uuid4().hex[:12]}",
        spec_id=spec.spec_id,
        parent_version_id=parent.version_id,
        proposer_mode=mode,
        llm_skip_reason=skip_reason,
        experiences=experiences,
        diagnoses=diagnoses,
        proposals=persisted,
        skipped_mutations=proposer.skipped,
        baseline_api_requests=proposer.baseline_requests,
        affordable_api_requests=proposer.affordable_requests,
        affordable_query_count=proposer.affordable_queries,
        created_at=_now(),
    )
    store.save_evolution_round(round_record)
    return round_record


def strategy_diff(parent: SearchStrategy, child: SearchStrategy) -> list[StrategyChange]:
    out: list[StrategyChange] = []
    for component in EVOLVABLE_COMPONENTS:
        before = getattr(parent, component)
        after = getattr(child, component)
        before_dump = before.model_dump() if hasattr(before, "model_dump") else before
        after_dump = after.model_dump() if hasattr(after, "model_dump") else after
        if before_dump != after_dump:
            out.append(_change(component, before_dump, after_dump))
    return out


class _LLMStrategyReply(BaseModel):
    """The only shape an LLM reply may take. Anything else is rejected."""

    strategy: SearchStrategy
    mutation_description: str = Field(min_length=3, max_length=1000)


async def llm_proposal(
    store: Store,
    proposer: CandidateProposer,
) -> tuple[CandidateProposal | None, str]:
    """One quota-limited LLM call. Returns (proposal, skip_reason).

    The prompt carries development diagnoses only. The reply is validated as a
    SearchStrategy, so it structurally cannot reach the benchmark, the evaluator
    or the frozen protocol, and its budget is clamped afterwards regardless.
    """
    settings = get_settings()
    if not settings.llm_configured:
        return None, (
            "LLM proposer unavailable: RLE_LLM_ENABLED / RLE_LLM_API_KEY / RLE_LLM_BASE_URL / "
            "RLE_LLM_MODEL are not all set on the server; the deterministic proposer ran instead"
        )
    used = sum(
        1 for e in store.list_skill_events() if e["event"] == "llm_call"
    )
    if used >= settings.llm_max_calls:
        return None, (
            f"LLM quota exhausted ({used}/{settings.llm_max_calls} calls); "
            "the deterministic proposer ran instead"
        )
    if not proposer.experiences:
        return None, "no development trial to reflect on; no LLM call was made"

    payload = {
        "parent_strategy": proposer.parent.strategy.model_dump(),
        "evolvable_components": list(EVOLVABLE_COMPONENTS),
        "affordable_query_count": proposer.affordable_queries,
        "development_diagnoses": [
            {"failure_type": d.failure_type, "evidence": d.evidence, "rationale": d.rationale}
            for d in proposer.diagnoses
        ],
    }
    store.add_skill_event(
        proposer.parent.version_id, "llm_call", {"purpose": "candidate_proposal", "call_index": used + 1}
    )
    try:
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.post(
                settings.llm_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You mutate a literature search strategy. Reply with JSON only: "
                                '{"strategy": {...}, "mutation_description": "..."}. Change only '
                                "the evolvable components. Do not exceed affordable_query_count."
                            ),
                        },
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                },
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            reply = _LLMStrategyReply.model_validate_json(content)
    except Exception as exc:
        reason = f"LLM proposer failed ({type(exc).__name__}: {exc}); the deterministic proposer ran instead"
        logger.warning(reason)
        return None, reason

    strategy = proposer._budgeted(reply.strategy.model_copy(deep=True))
    changes = strategy_diff(proposer.parent.strategy, strategy)
    if not changes:
        return None, "the LLM returned a strategy identical to its parent; no candidate was created"
    proposal = proposer._build(
        strategy,
        reply.mutation_description,
        {d.failure_type for d in proposer.diagnoses},
        changes,
        "quota-limited LLM reflection over development diagnoses, validated by Pydantic",
    )
    return proposal, ""