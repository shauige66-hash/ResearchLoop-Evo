"""Unit tests for evidence-card grounding: the model proposes, Python verifies.

The card is the only place an LLM claim becomes a stored fact, so these tests pin
the rule that a span must exist verbatim in the abstract that was actually sent,
and that a card can never imply the full text was read.
"""

from __future__ import annotations

import json

import pytest

from app.models.gap_pipeline import PROMPT_VERSION
from app.models.paper import Paper
from app.services.gap_agents import GapAgents, abstract_hash, find_verbatim_span, paper_payload
from app.services.llm import LLMProvider

ABSTRACT = (
    "We study memory consolidation for LLM agents. "
    "We propose a module that compresses episodic traces into reusable skills. "
    "However, evaluation protocols differ across papers and results are not comparable. "
    "Future work will release a shared benchmark for this task."
)
METHOD_SPAN = "We propose a module that compresses episodic traces into reusable skills."
LIMIT_SPAN = "evaluation protocols differ across papers and results are not comparable"


def _paper(store, abstract: str = ABSTRACT) -> Paper:
    store.save_project("proj_card", "memory consolidation for LLM agents")
    paper = Paper(
        paper_id="card:p1",
        title="Memory consolidation for LLM agents",
        doi="10.9999/card.1",
        abstract=abstract,
        source="openalex",
        source_url="https://openalex.org/card:p1",
        publication_year=2024,
        retrieved_at="2025-01-01T00:00:00Z",
        run_id="run_card",
    )
    store.save_paper(paper, "proj_card")
    return paper


def _agents(store, monkeypatch, fields: dict):
    """A real provider whose only replaced part is the network seam."""
    provider = LLMProvider(store)
    payloads: list[dict] = []

    async def fake_post(agent_role, system, user):
        payloads.append(json.loads(user))
        return json.dumps(fields, ensure_ascii=False), {}

    monkeypatch.setattr(provider, "_post", fake_post)
    return GapAgents(store, provider), payloads


def _field(claim: str, span: str) -> dict:
    return {"claim": claim, "evidence_span": span, "confidence": "medium"}


# ------------------------------------------------------------- span matching
def test_a_quote_must_exist_verbatim_in_the_source_text():
    assert find_verbatim_span(ABSTRACT, LIMIT_SPAN) == LIMIT_SPAN
    assert find_verbatim_span(ABSTRACT, "the authors never released any code") is None
    assert find_verbatim_span(ABSTRACT, "   ") is None
    assert find_verbatim_span("", LIMIT_SPAN) is None


def test_a_reflowed_quote_is_corrected_to_the_source_whitespace():
    reflowed = "evaluation  protocols differ across papers\nand results are not comparable"
    located = find_verbatim_span(ABSTRACT, reflowed)
    assert located == LIMIT_SPAN
    assert located in ABSTRACT


# ------------------------------------------------------------------- grounding
@pytest.mark.asyncio
async def test_a_grounded_card_quotes_only_the_abstract(temp_db, llm_configured, monkeypatch):
    paper = _paper(temp_db)
    agents, payloads = _agents(
        temp_db,
        monkeypatch,
        {
            "method": _field("a compression module", METHOD_SPAN),
            "limitations": _field("protocols are not comparable", LIMIT_SPAN),
        },
    )

    card = await agents.analyze_paper(paper, "gpipe_a")

    assert card.grounded_fields == ["method", "limitations"]
    assert card.rejected_fields == []
    assert card.from_cache is False
    assert card.abstract_hash == abstract_hash(ABSTRACT)
    assert card.prompt_version == PROMPT_VERSION
    for name in card.grounded_fields:
        field = card.field(name)
        assert field.evidence_source == "abstract"
        assert field.evidence_span in ABSTRACT
    assert card.field("dataset").is_filled is False
    assert temp_db.get_evidence_card(paper.paper_id, PROMPT_VERSION).paper_id == paper.paper_id
    # The model is fed metadata plus the abstract, and nothing else.
    assert set(payloads[0]) == set(paper_payload(paper))
    assert payloads[0]["abstract"] == ABSTRACT


@pytest.mark.asyncio
async def test_a_reflowed_quote_is_stored_as_the_source_text(temp_db, llm_configured, monkeypatch):
    paper = _paper(temp_db)
    agents, _ = _agents(
        temp_db,
        monkeypatch,
        {
            "limitations": _field(
                "protocols are not comparable",
                "evaluation  protocols differ across papers\nand results are not comparable",
            )
        },
    )

    card = await agents.analyze_paper(paper, "gpipe_a")

    assert card.grounded_fields == ["limitations"]
    assert card.limitations.evidence_span == LIMIT_SPAN


@pytest.mark.asyncio
async def test_an_invented_span_is_rejected_and_never_becomes_a_claim(
    temp_db, llm_configured, monkeypatch
):
    paper = _paper(temp_db)
    agents, _ = _agents(
        temp_db,
        monkeypatch,
        {
            "method": _field("a compression module", METHOD_SPAN),
            "limitations": _field("no code was released", "the authors never released any code"),
        },
    )

    card = await agents.analyze_paper(paper, "gpipe_a")

    assert card.grounded_fields == ["method"]
    assert card.limitations.is_filled is False
    assert card.limitations.claim == ""
    rejected = {item["field"]: item for item in card.rejected_fields}
    assert "limitations" in rejected
    assert "not found verbatim" in rejected["limitations"]["reason"]


@pytest.mark.asyncio
async def test_a_claim_without_a_span_is_rejected(temp_db, llm_configured, monkeypatch):
    paper = _paper(temp_db)
    agents, _ = _agents(
        temp_db, monkeypatch, {"dataset": _field("a private long-history dataset", "")}
    )

    card = await agents.analyze_paper(paper, "gpipe_a")

    assert card.grounded_fields == []
    assert card.rejected_fields[0]["reason"] == "claim was made without an evidence_span"


@pytest.mark.asyncio
async def test_a_paper_without_an_abstract_never_calls_the_model(
    temp_db, llm_configured, monkeypatch
):
    paper = _paper(temp_db, abstract="")
    agents, payloads = _agents(temp_db, monkeypatch, {})

    with pytest.raises(ValueError, match="no retrieved abstract"):
        await agents.analyze_paper(paper, "gpipe_a")

    assert payloads == []
    assert temp_db.list_evidence_cards() == []


# ------------------------------------------------------------------ card cache
@pytest.mark.asyncio
async def test_the_same_paper_and_prompt_version_reuse_the_card_for_free(
    temp_db, llm_configured, monkeypatch
):
    paper = _paper(temp_db)
    agents, payloads = _agents(
        temp_db, monkeypatch, {"limitations": _field("protocols differ", LIMIT_SPAN)}
    )

    first = await agents.analyze_paper(paper, "gpipe_a")
    second = await agents.analyze_paper(paper, "gpipe_b")

    assert len(payloads) == 1
    assert second.from_cache is True
    # A reused card keeps the pipeline that actually paid for it.
    assert second.pipeline_id == first.pipeline_id == "gpipe_a"
    assert temp_db.count_llm_attempts() == 1


@pytest.mark.asyncio
async def test_a_changed_abstract_invalidates_the_cached_card(
    temp_db, llm_configured, monkeypatch
):
    paper = _paper(temp_db)
    agents, payloads = _agents(
        temp_db, monkeypatch, {"limitations": _field("protocols differ", LIMIT_SPAN)}
    )
    await agents.analyze_paper(paper, "gpipe_a")

    paper.abstract = ABSTRACT + " We additionally report latency under a fixed budget."
    temp_db.save_paper(paper, "proj_card")
    again = await agents.analyze_paper(paper, "gpipe_a")

    assert len(payloads) == 2
    assert again.from_cache is False
    assert again.abstract_hash == abstract_hash(paper.abstract)