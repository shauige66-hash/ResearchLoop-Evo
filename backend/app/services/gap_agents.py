"""The four LLM roles of the gap pipeline, plus the Python checks around them.

Division of labour:

- the planner proposes search angles, it does not retrieve anything;
- the literature analyst reads one abstract at a time and must quote a verbatim
  span for every claim; Python re-finds that span in the abstract that was
  actually sent, and drops the field when it cannot;
- the gap analyst synthesises across cards and proposes candidates;
- the critic scores a candidate without ever seeing the gap analyst's reasoning,
  its own risk label, or its uncertainties.

No role verifies itself. Every factual check lives in `gap_validator.py`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ..models.gap_pipeline import (
    CARD_FIELDS,
    PROMPT_VERSION,
    CandidateGap,
    CrossPaperSynthesis,
    EvidenceCard,
    EvidenceCardField,
    GapAnalystOutput,
    GapCritique,
    ResearchPlan,
)
from ..models.paper import Paper
from ..storage.store import Store
from .llm import LLMProvider

logger = logging.getLogger(__name__)

ABSTRACT_ONLY_NOTICE = (
    "Only the retrieved abstract was available. No full text was read, so every "
    "evidence_source is 'abstract' and no claim about the full paper is made."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def abstract_hash(abstract: str) -> str:
    return hashlib.sha256(abstract.encode("utf-8")).hexdigest()


def find_verbatim_span(text: str, span: str) -> str | None:
    """Return the exact substring of `text` that grounds `span`, or None.

    A model may reflow whitespace while quoting. The corrected span is taken from
    the source text itself, so what is stored is always verbatim; a span that
    cannot be located is rejected rather than trusted.
    """
    if not span.strip() or not text:
        return None
    if span in text:
        return span
    pattern = r"\s+".join(re.escape(part) for part in span.split())
    match = re.search(pattern, text)
    return match.group(0) if match else None


def paper_payload(paper: Paper) -> dict:
    """Exactly what the model is allowed to see: metadata plus the abstract."""
    return {
        "paper_id": paper.paper_id,
        "title": paper.title,
        "publication_year": paper.publication_year,
        "venue": paper.venue,
        "doi": paper.doi,
        "source": paper.source,
        "is_review": paper.is_review,
        "abstract": paper.abstract or "",
    }


class _CardReply(BaseModel):
    research_problem: EvidenceCardField = Field(default_factory=EvidenceCardField)
    method: EvidenceCardField = Field(default_factory=EvidenceCardField)
    setting: EvidenceCardField = Field(default_factory=EvidenceCardField)
    dataset: EvidenceCardField = Field(default_factory=EvidenceCardField)
    evaluation: EvidenceCardField = Field(default_factory=EvidenceCardField)
    limitations: EvidenceCardField = Field(default_factory=EvidenceCardField)
    future_work: EvidenceCardField = Field(default_factory=EvidenceCardField)


class _CounterQueries(BaseModel):
    queries: list[str] = Field(default_factory=list, max_length=5)


PLANNER_SYSTEM = (
    "You are a research search planner. Reply with JSON only, matching the requested "
    "schema. Cover five angles: survey/review, foundational, recent, representative "
    "methods, and limitations/challenges. Every query must be a concrete literature "
    "search string in English. State at least one research question. Do not invent "
    "papers, authors or DOIs. You are planning retrieval, not answering the question."
)

ANALYST_SYSTEM = (
    "You extract an evidence card from ONE paper abstract. Reply with JSON only. For "
    "each of the seven fields give a short claim and an evidence_span copied VERBATIM "
    "from the abstract text you were given. If the abstract does not state a field, "
    "leave claim and evidence_span empty; never guess and never use outside knowledge. "
    "You only have the abstract, not the full text. Do not report percentages or "
    "numbers that are not in the abstract."
)

GAP_ANALYST_SYSTEM = (
    "You synthesise across evidence cards to propose candidate research gaps. Reply "
    "with JSON only. First fill the cross-paper synthesis, then propose candidates. "
    "Every candidate must cite at least two distinct paper_ids from the cards and "
    "quote evidence spans that appear in those cards. A gap is a hypothesis about the "
    "literature, not a finding. Use gap_type from the allowed vocabulary. Set "
    "novelty_risk to exactly one bare uppercase token, LOW or MEDIUM or HIGH, with no "
    "other text in that field; put the textual justification in novelty_rationale. "
    "Never output a novelty probability or percentage. Do not invent papers, DOIs or "
    "results."
)

CRITIC_SYSTEM = (
    "You are an independent reviewer of a proposed research gap. Reply with JSON only. "
    "Score evidence_grounding, cross_paper_support, specificity and testability each "
    "as an integer from 0 to 5. Give novelty_risk and contradiction_risk as exactly "
    "one bare uppercase token each, LOW or MEDIUM or HIGH, with no other text in those "
    "fields. List major_weaknesses and missing_evidence, then recommended_action "
    "(accept, revise or reject) and a rationale. You are given the claim and the quoted "
    "evidence only; you have not seen the proposer's reasoning. Never output "
    "percentages or pseudo-precise probabilities. Judge only what the evidence shows."
)

COUNTER_QUERY_SYSTEM = (
    "You write literature search queries that would find work ALREADY SOLVING the "
    "stated gap, so the system can check its own claim. Reply with JSON only: "
    '{"queries": ["...", "..."]}. At most five concrete English search strings. Target '
    "the specific unresolved boundary, not the general topic. Do not invent papers."
)


class GapAgents:
    """Role prompts plus the Python verification that surrounds each reply."""

    def __init__(self, store: Store, provider: LLMProvider | None = None) -> None:
        self.store = store
        self.provider = provider if provider is not None else LLMProvider(store)

    # ------------------------------------------------------------------ planner
    async def plan(self, topic: str, pipeline_id: str, known_queries: list[str]) -> ResearchPlan:
        user = json.dumps(
            {
                "research_topic": topic,
                "queries_already_run": known_queries,
                "required_angles": [
                    "survey/review",
                    "foundational",
                    "recent",
                    "representative methods",
                    "limitations/challenges",
                ],
                "schema": {
                    "research_topic": "str",
                    "research_questions": ["str"],
                    "search_angles": ["str"],
                    "review_queries": ["str"],
                    "foundational_queries": ["str"],
                    "recent_queries": ["str"],
                    "method_queries": ["str"],
                    "challenge_queries": ["str"],
                    "inclusion_criteria": ["str"],
                    "exclusion_criteria": ["str"],
                },
            },
            ensure_ascii=False,
        )
        reply = await self.provider.complete(
            "research_planner",
            PLANNER_SYSTEM,
            user,
            schema=ResearchPlan,
            pipeline_id=pipeline_id,
        )
        return reply.parsed

    # ------------------------------------------------------- literature analyst
    async def analyze_paper(self, paper: Paper, pipeline_id: str) -> EvidenceCard:
        abstract = (paper.abstract or "").strip()
        if not abstract:
            raise ValueError(
                f"paper {paper.paper_id} has no retrieved abstract; an evidence card "
                "cannot be produced without input text"
            )
        digest = abstract_hash(abstract)
        cached = self.store.get_evidence_card(paper.paper_id, PROMPT_VERSION)
        if cached is not None and cached.abstract_hash == digest:
            cached.from_cache = True
            return cached

        reply = await self.provider.complete(
            "literature_analyst",
            ANALYST_SYSTEM,
            json.dumps(paper_payload(paper), ensure_ascii=False),
            schema=_CardReply,
            pipeline_id=pipeline_id,
            paper_id=paper.paper_id,
        )
        card = EvidenceCard(
            paper_id=paper.paper_id,
            pipeline_id=pipeline_id,
            title=paper.title,
            doi=paper.doi,
            source_url=paper.source_url,
            abstract_hash=digest,
            prompt_version=PROMPT_VERSION,
            created_at=_now(),
        )
        for name in CARD_FIELDS:
            claimed: EvidenceCardField = getattr(reply.parsed, name)
            if not claimed.claim.strip():
                continue
            located = find_verbatim_span(abstract, claimed.evidence_span)
            if located is None:
                card.rejected_fields.append(
                    {
                        "field": name,
                        "reason": (
                            "evidence_span was not found verbatim in the abstract that "
                            "was sent to the model"
                            if claimed.evidence_span.strip()
                            else "claim was made without an evidence_span"
                        ),
                        "span": claimed.evidence_span[:300],
                    }
                )
                continue
            setattr(
                card,
                name,
                EvidenceCardField(
                    claim=claimed.claim.strip(),
                    evidence_span=located,
                    evidence_source="abstract",
                    confidence=claimed.confidence,
                ),
            )
            card.grounded_fields.append(name)
        self.store.save_evidence_card(card)
        return card

    # ------------------------------------------------------------ gap analyst
    async def synthesize(
        self,
        topic: str,
        cards: list[EvidenceCard],
        max_gaps: int,
        pipeline_id: str,
    ) -> GapAnalystOutput:
        payload = {
            "research_topic": topic,
            "max_candidates": max_gaps,
            "allowed_gap_types": [
                "coverage_gap",
                "method_gap",
                "evaluation_gap",
                "generalization_gap",
                "contradiction_gap",
                "integration_gap",
            ],
            "evidence_cards": [
                {
                    "paper_id": card.paper_id,
                    "title": card.title,
                    "doi": card.doi,
                    "fields": {
                        name: {
                            "claim": card.field(name).claim,
                            "evidence_span": card.field(name).evidence_span,
                        }
                        for name in CARD_FIELDS
                        if card.field(name).is_filled
                    },
                }
                for card in cards
            ],
            "candidate_schema": {
                "gap_claim": "str, a specific statement",
                "gap_type": "one of allowed_gap_types",
                "problem_context": "str",
                "already_solved": "str",
                "unresolved_boundary": "str",
                "why_it_matters": "str",
                "supporting_papers": ["paper_id"],
                "supporting_evidence": [
                    {"paper_id": "str", "field": "card field name", "evidence_span": "str"}
                ],
                "contradicting_evidence": [
                    {"paper_id": "str", "field": "card field name", "evidence_span": "str"}
                ],
                "candidate_research_question": "str",
                "minimum_experiment": "str",
                "testability": "str",
                "novelty_risk": "exactly LOW or MEDIUM or HIGH, no other text",
                "novelty_rationale": "str, why that risk level",
                "uncertainties": ["str"],
            },
            "synthesis_schema": {
                name: ["str"]
                for name in CrossPaperSynthesis.model_fields
            },
        }
        reply = await self.provider.complete(
            "gap_analyst",
            GAP_ANALYST_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            schema=GapAnalystOutput,
            pipeline_id=pipeline_id,
        )
        output: GapAnalystOutput = reply.parsed
        output.candidates = output.candidates[:max_gaps]
        return output

    # ------------------------------------------------------------------ critic
    async def critique(
        self,
        candidate: CandidateGap,
        cards: list[EvidenceCard],
        gap_index: int,
        pipeline_id: str,
    ) -> GapCritique:
        by_id = {card.paper_id: card for card in cards}
        # Deliberately withheld: problem_context, already_solved, why_it_matters,
        # uncertainties and the proposer's own novelty_risk. The critic judges the
        # claim and the quoted evidence, not the proposer's argument.
        evidence = []
        for ref in candidate.supporting_evidence:
            card = by_id.get(ref.paper_id)
            evidence.append(
                {
                    "paper_id": ref.paper_id,
                    "title": card.title if card else "(unknown paper)",
                    "field": ref.field,
                    "evidence_span": ref.evidence_span,
                }
            )
        payload = {
            "gap_claim": candidate.gap_claim,
            "gap_type": candidate.gap_type,
            "unresolved_boundary": candidate.unresolved_boundary,
            "candidate_research_question": candidate.candidate_research_question,
            "minimum_experiment": candidate.minimum_experiment,
            "supporting_evidence": evidence,
            "contradicting_evidence": [
                {"paper_id": r.paper_id, "field": r.field, "evidence_span": r.evidence_span}
                for r in candidate.contradicting_evidence
            ],
            "score_scale": "integer 0..5 for each of the four scores",
        }
        reply = await self.provider.complete(
            "gap_critic",
            CRITIC_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            schema=GapCritique,
            pipeline_id=pipeline_id,
        )
        critique: GapCritique = reply.parsed
        critique.gap_index = gap_index
        critique.from_cache = reply.from_cache
        return critique

    # ---------------------------------------------------------- counter queries
    async def counter_queries(
        self, topic: str, candidate: CandidateGap, pipeline_id: str
    ) -> list[str]:
        payload = {
            "research_topic": topic,
            "gap_claim": candidate.gap_claim,
            "unresolved_boundary": candidate.unresolved_boundary,
            "already_solved": candidate.already_solved,
            "max_queries": 5,
        }
        reply = await self.provider.complete(
            "counter_query",
            COUNTER_QUERY_SYSTEM,
            json.dumps(payload, ensure_ascii=False),
            schema=_CounterQueries,
            pipeline_id=pipeline_id,
        )
        queries: list[str] = []
        for query in reply.parsed.queries:
            cleaned = query.strip()
            if cleaned and cleaned not in queries:
                queries.append(cleaned)
        return queries[:5]