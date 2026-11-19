"""Test-only LLM doubles. Application code must never import this module.

The fake replaces the single network seam (`LLMProvider._post`), so budget
enforcement, caching, auditing and schema rejection are exercised for real. Its
replies are built from the payload the agent actually sent, which means the
evidence spans it quotes really do exist in the abstracts under test.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from app.services.llm import LLMProvider

CARD_FIELDS = (
    "research_problem",
    "method",
    "setting",
    "dataset",
    "evaluation",
    "limitations",
    "future_work",
)


def sentences(abstract: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", abstract.strip()) if s.strip()]


# Which sentence a role would quote for each card field. Purely a test double:
# the spans it returns are still real sentences of the abstract under test.
FIELD_CUES: dict[str, tuple[str, ...]] = {
    "research_problem": ("we study", "we investigate", "we address", "this paper"),
    "method": ("we propose", "we present", "we develop", "we design"),
    "setting": ("environment", "agent runs", "multi-session", "setting"),
    "dataset": ("dataset", "corpus", "we evaluate on"),
    "evaluation": ("we report", "measure", "accuracy", "f1", "bleu", "mrr"),
    "limitations": ("however", "limitation", "cannot", "remains"),
    "future_work": ("future work", "will release", "we plan"),
}


def card_reply(payload: dict, *, hallucinate: str | None = None) -> dict:
    """One card per abstract, quoting real sentences; optionally one invented span."""
    parts = sentences(payload.get("abstract", ""))
    used: set[int] = set()
    picked: dict[str, int] = {}
    for name in CARD_FIELDS:
        chosen = next(
            (
                i
                for i, part in enumerate(parts)
                if i not in used and any(cue in part.lower() for cue in FIELD_CUES[name])
            ),
            None,
        )
        if chosen is not None:
            used.add(chosen)
            picked[name] = chosen
    for index, name in enumerate(CARD_FIELDS):
        if name in picked or index >= len(parts) or index in used:
            continue
        used.add(index)
        picked[name] = index
    reply: dict[str, Any] = {}
    for name in CARD_FIELDS:
        if name not in picked:
            reply[name] = {"claim": "", "evidence_span": ""}
            continue
        part = parts[picked[name]]
        reply[name] = {
            "claim": part[:160],
            "evidence_span": part,
            "evidence_source": "abstract",
            "confidence": "medium",
        }
    if hallucinate:
        reply[hallucinate] = {
            "claim": "An invented finding",
            "evidence_span": "This sentence was never present in the abstract.",
            "evidence_source": "abstract",
            "confidence": "high",
        }
    return reply


def plan_reply(payload: dict) -> dict:
    topic = payload.get("research_topic", "agent memory")
    return {
        "research_topic": topic,
        "research_questions": [f"Which evaluation protocols for {topic} are comparable?"],
        "search_angles": ["survey/review", "foundational", "recent", "methods", "challenges"],
        "review_queries": [f"{topic} survey"],
        "foundational_queries": [f"{topic} foundations"],
        "recent_queries": [f"{topic} 2025"],
        "method_queries": [f"{topic} method"],
        "challenge_queries": [f"{topic} limitations"],
        "inclusion_criteria": ["peer-reviewed or arXiv preprint with an abstract"],
        "exclusion_criteria": ["no abstract available"],
    }


def gap_reply(payload: dict) -> dict:
    """Propose one candidate grounded in the cards that were actually sent."""
    cards = payload.get("evidence_cards", [])
    supporting = [c["paper_id"] for c in cards[:3]]
    evidence = []
    for card in cards[:3]:
        span = card["fields"].get("limitations", {}).get("evidence_span", "")
        if span:
            evidence.append(
                {"paper_id": card["paper_id"], "field": "limitations", "evidence_span": span}
            )
    topic = payload.get("research_topic", "agent memory")
    return {
        "synthesis": {
            "already_solved": [f"{topic} improves recall on the authors' own benchmarks"],
            "main_method_routes": ["memory-augmented agents"],
            "consistent_findings": ["reported gains are benchmark-specific"],
            "conflicting_findings": [],
            "uncovered_scenarios": ["held-out subtopics"],
            "shared_limitations": ["evaluation is not comparable across papers"],
            "uncovered_metrics": ["cost", "human judgement"],
            "repeatedly_mentioned_unresolved": ["cross-paper comparability"],
            "mature_but_uncombined": ["retrieval and memory consolidation"],
        },
        "candidates": [
            {
                "gap_claim": (
                    f"Across the retrieved {topic} papers, evaluation protocols share no "
                    "common metric family, so reported gains cannot be compared across works."
                ),
                "gap_type": "evaluation_gap",
                "problem_context": f"{topic} papers report gains on their own benchmarks.",
                "already_solved": "Each paper evaluates its own method on its own dataset.",
                "unresolved_boundary": "No shared metric family across the compared papers.",
                "why_it_matters": "Without comparability, progress cannot be accumulated.",
                "supporting_papers": supporting,
                "supporting_evidence": evidence,
                "contradicting_evidence": [],
                "candidate_research_question": (
                    f"Can a shared metric family make {topic} results comparable?"
                ),
                "minimum_experiment": (
                    "Compare metric-family coverage against a human-confirmed reference set "
                    "under a fixed retrieval budget."
                ),
                "testability": "Measurable with the existing retrieval benchmark.",
                "novelty_risk": "MEDIUM",
                "uncertainties": ["Only abstracts were available."],
            }
        ],
    }


def critic_reply(payload: dict) -> dict:
    return {
        "evidence_grounding": 4,
        "cross_paper_support": 4,
        "specificity": 4,
        "testability": 4,
        "novelty_risk": "LOW",
        "contradiction_risk": "LOW",
        "major_weaknesses": ["Abstract-only evidence."],
        "missing_evidence": ["Full-text evaluation protocols."],
        "recommended_action": "accept",
        "rationale": "Three papers quote the same evaluation limitation verbatim.",
    }


def counter_reply(payload: dict) -> dict:
    topic = payload.get("research_topic", "agent memory")
    return {"queries": [f"{topic} shared evaluation benchmark", f"{topic} comparability metrics"]}


DEFAULT_REPLIES: dict[str, Callable[[dict], dict]] = {
    "research_planner": plan_reply,
    "literature_analyst": card_reply,
    "gap_analyst": gap_reply,
    "gap_critic": critic_reply,
    "counter_query": counter_reply,
}

FAKE_USAGE = {"prompt_tokens": 120, "completion_tokens": 60, "total_tokens": 180}


class FakeLLMProvider(LLMProvider):
    """A provider double for unit and integration tests only."""

    def __init__(
        self,
        store,
        *,
        replies: dict[str, Any] | None = None,
        fail_roles: tuple[str, ...] = (),
        malformed_roles: tuple[str, ...] = (),
        hallucinate: dict[str, str] | None = None,
    ) -> None:
        super().__init__(store)
        self.replies = {**DEFAULT_REPLIES, **(replies or {})}
        self.fail_roles = set(fail_roles)
        self.malformed_roles = set(malformed_roles)
        # paper_id -> card field that gets an invented, unverifiable span
        self.hallucinate = hallucinate or {}
        self.calls: list[dict] = []

    async def _post(self, agent_role: str, system: str, user: str) -> tuple[str, dict]:
        payload = json.loads(user)
        self.calls.append({"role": agent_role, "system": system, "payload": payload})
        if agent_role in self.fail_roles:
            raise RuntimeError("fake provider unreachable")
        if agent_role in self.malformed_roles:
            return "this is not JSON", {}
        builder = self.replies[agent_role]
        if agent_role == "literature_analyst":
            reply = card_reply(
                payload, hallucinate=self.hallucinate.get(payload.get("paper_id", ""))
            )
        elif callable(builder):
            reply = builder(payload)
        else:
            reply = builder
        return json.dumps(reply, ensure_ascii=False), dict(FAKE_USAGE)

    def roles_called(self) -> list[str]:
        return [c["role"] for c in self.calls]