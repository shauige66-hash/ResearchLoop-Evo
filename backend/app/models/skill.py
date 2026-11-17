"""The single evolvable skill in this prototype: literature search strategy.

Only the six components below may evolve. The evaluator, the benchmark reference
DOIs, the dataset splits, the API source set and the budget ceilings live outside
this model and are never reachable from a candidate strategy.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SkillStatus = Literal["active", "candidate", "archived", "rejected"]

SKILL_ID = "literature_search_strategy"

# Words that carry no retrieval signal when a topic is split into terms.
_TOPIC_STOPWORDS = frozenset("""
a an the and or of for in on at to with by from is are was were be been being
this that these those it its as we our their study studies paper papers toward
towards based using via new novel approach approaches method methods
""".split())

ExpansionRule = Literal["topic_terms", "domain_synonyms", "query_terms"]


class SearchFilters(BaseModel):
    year_from: int | None = Field(default=None, ge=1900, le=2100)
    year_to: int | None = Field(default=None, ge=1900, le=2100)
    document_types: list[str] = Field(default_factory=list)
    prefer_reviews: bool = False


class RetrievalBudget(BaseModel):
    """Ceilings a candidate may tighten but never loosen past the spec limit."""

    top_k: int = Field(default=20, ge=1, le=200)
    max_keywords: int = Field(default=1, ge=1, le=6)
    max_api_requests: int = Field(default=3, ge=1, le=60)


class SearchStrategy(BaseModel):
    query_templates: list[str] = Field(default_factory=lambda: ["{query}"])
    domain_synonyms: dict[str, list[str]] = Field(default_factory=dict)
    keyword_expansion_rules: list[ExpansionRule] = Field(default_factory=list)
    source_priority: list[str] = Field(default_factory=lambda: ["openalex", "crossref", "arxiv"])
    search_filters: SearchFilters = Field(default_factory=SearchFilters)
    retrieval_budget: RetrievalBudget = Field(default_factory=RetrievalBudget)

    @model_validator(mode="after")
    def _templates_must_be_renderable(self) -> "SearchStrategy":
        if not self.query_templates:
            raise ValueError("a search strategy needs at least one query template")
        for template in self.query_templates:
            unknown = set(re.findall(r"\{(\w+)\}", template)) - {"topic", "query"}
            if unknown:
                raise ValueError(f"unknown template placeholders: {sorted(unknown)}")
        return self


class SkillVersion(BaseModel):
    """An immutable strategy snapshot. Versions are never overwritten."""

    version_id: str
    skill_id: str = SKILL_ID
    version_number: int
    parent_version: str | None = None
    strategy: SearchStrategy
    mutation_description: str = "initial strategy"
    # Real run ids whose failure trajectories motivated this mutation.
    source_trials: list[str] = Field(default_factory=list)
    created_at: str
    status: SkillStatus = "candidate"
    created_by: Literal["seed", "human", "proposer"] = "seed"

    @property
    def label(self) -> str:
        return f"{self.skill_id}@v{self.version_number}"


def _terms(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z一-鿿]{3,}", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for word in words:
        if word in _TOPIC_STOPWORDS or word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out


def plan_queries(strategy: SearchStrategy, topic: str, query: str) -> list[str]:
    """Render a strategy into the concrete queries that will be sent to the APIs.

    Deterministic: the same strategy and case always produce the same query list,
    which is what makes a replay comparable to the original run.
    """
    budget = strategy.retrieval_budget
    rendered: list[str] = []
    for template in strategy.query_templates:
        text = template.replace("{topic}", topic).replace("{query}", query).strip()
        if text:
            rendered.append(text)

    expansions: list[str] = []
    for rule in strategy.keyword_expansion_rules:
        if rule == "topic_terms":
            expansions.extend(_terms(topic))
        elif rule == "query_terms":
            expansions.extend(_terms(query))
        elif rule == "domain_synonyms":
            haystack = f"{topic} {query}".lower()
            lowered_query = query.lower()
            for term, synonyms in strategy.domain_synonyms.items():
                if term.lower() not in haystack:
                    continue
                for synonym in synonyms:
                    # Appending a term the query already contains buys no recall.
                    if synonym.lower() in lowered_query:
                        continue
                    expansions.append(f"{query} {synonym}")

    ordered: list[str] = []
    seen: set[str] = set()
    for text in rendered + expansions:
        key = " ".join(text.lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(text)
    return ordered[: budget.max_keywords]


def baseline_strategy() -> SearchStrategy:
    """v1: the original question, one query, no expansion."""
    return SearchStrategy(
        query_templates=["{query}"],
        domain_synonyms={},
        keyword_expansion_rules=[],
        source_priority=["openalex", "crossref", "arxiv"],
        search_filters=SearchFilters(),
        retrieval_budget=RetrievalBudget(top_k=20, max_keywords=1, max_api_requests=3),
    )


class SkillVersionCreate(BaseModel):
    """A human-authored candidate. Creating one never activates it."""

    strategy: SearchStrategy
    mutation_description: str = Field(min_length=3, max_length=1000)
    source_trials: list[str] = Field(default_factory=list)
    parent_version: str | None = None
    created_by: Literal["human", "proposer"] = "human"