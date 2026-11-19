"""Independent Python verification of a candidate gap, and the final gate.

Nothing here asks a model whether the gap is real. Every check reads records that
were actually retrieved or spans that were actually quoted, and the gate is a
deterministic function of those facts plus the configured thresholds.

Passing the gate means "reached the configured evidence thresholds within the
current search scope". It is never a proof of novelty.
"""

from __future__ import annotations

import re
from typing import Any

from ..config import GATE_NOTICE, get_settings
from ..models.gap_pipeline import (
    CARD_FIELDS,
    RISK_ORDER,
    CandidateGap,
    CounterSearchOutcome,
    EvidenceCard,
    GapCheck,
    GapCritique,
    GapGateResult,
    GapValidation,
    RiskLabel,
)
from ..storage.store import Store
from .gap_agents import find_verbatim_span

DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)

GENERIC_CLAIMS = (
    "further research is needed",
    "more research is needed",
    "more work is needed",
    "future work is needed",
    "this needs further study",
    "research gap exists",
)

# A search that failed is not a search that found nothing.
FAILED_SEARCH_STATUSES = frozenset({"COUNTER_SEARCH_FAILED", "NOT_RUN"})

# Failures that reject a candidate outright. A failed counter search is not one of
# them: it leaves the candidate for a human, because the system could not look.
_HARD_CHECKS = frozenset(
    {
        "supporting_papers_exist",
        "no_duplicate_paper_counting",
        "evidence_spans_verbatim",
        "evidence_subset_of_supporting_papers",
        "claim_is_specific",
        "critic_does_not_reject",
    }
)


def _risk_at_least(left: RiskLabel, right: RiskLabel) -> RiskLabel:
    return left if RISK_ORDER[left] >= RISK_ORDER[right] else right


def _check(name: str, passed: bool, detail: str) -> GapCheck:
    return GapCheck(name=name, passed=passed, detail=detail)


def validate_gap(
    store: Store,
    candidate: CandidateGap,
    cards: list[EvidenceCard],
    critique: GapCritique | None,
    counter: CounterSearchOutcome,
    *,
    gap_index: int = 0,
    gate: dict[str, Any] | None = None,
) -> GapValidation:
    """Re-derive every factual claim the candidate makes, from stored records."""
    gate = gate if gate is not None else get_settings().gap_gate
    by_id = {card.paper_id: card for card in cards}
    checks: list[GapCheck] = []
    reasons: list[str] = []

    supporting = list(candidate.supporting_papers)
    unique_supporting = list(dict.fromkeys(supporting))
    papers = {pid: store.get_paper(pid) for pid in unique_supporting}
    missing = [pid for pid, paper in papers.items() if paper is None]
    checks.append(
        _check(
            "supporting_papers_exist",
            not missing,
            f"{len(unique_supporting) - len(missing)}/{len(unique_supporting)} supporting "
            f"paper_ids resolve to retrieved records"
            + (f"; missing: {missing}" if missing else ""),
        )
    )
    if missing:
        reasons.append(f"supporting papers were never retrieved: {missing}")

    min_support = int(gate["min_supporting_papers"])
    checks.append(
        _check(
            "min_supporting_papers",
            len(unique_supporting) >= min_support,
            f"{len(unique_supporting)} distinct supporting papers, gate requires {min_support}",
        )
    )

    # Two ids can still be one paper: the same DOI retrieved from two sources.
    dois = [
        (paper.doi or "").strip().lower()
        for paper in papers.values()
        if paper is not None and (paper.doi or "").strip()
    ]
    duplicate_doi = len(dois) != len(set(dois))
    duplicate_ids = len(supporting) != len(unique_supporting)
    duplicate_counting = duplicate_doi or duplicate_ids
    checks.append(
        _check(
            "no_duplicate_paper_counting",
            not duplicate_counting,
            "supporting papers are distinct records"
            if not duplicate_counting
            else "the same paper is counted more than once "
            + ("(repeated paper_id)" if duplicate_ids else "(repeated DOI across sources)"),
        )
    )
    if duplicate_counting:
        reasons.append("duplicate paper counting inflates the support for this gap")

    valid_refs = 0
    invalid_refs: list[dict[str, str]] = []
    for ref in candidate.supporting_evidence:
        paper = papers.get(ref.paper_id)
        card = by_id.get(ref.paper_id)
        problem = ""
        if paper is None:
            problem = "paper_id does not resolve to a retrieved record"
        elif ref.field not in CARD_FIELDS:
            problem = f"'{ref.field}' is not an evidence card field"
        else:
            haystacks = [paper.abstract or ""]
            if card is not None:
                haystacks.append(card.field(ref.field).evidence_span)
            if not any(find_verbatim_span(text, ref.evidence_span) for text in haystacks):
                problem = "evidence_span is not verbatim in the retrieved abstract or card"
        if problem:
            invalid_refs.append(
                {"paper_id": ref.paper_id, "field": ref.field, "reason": problem}
            )
        else:
            valid_refs += 1
    checks.append(
        _check(
            "evidence_spans_verbatim",
            bool(candidate.supporting_evidence) and not invalid_refs,
            f"{valid_refs} valid evidence reference(s), {len(invalid_refs)} invalid",
        )
    )
    if invalid_refs:
        reasons.append(f"{len(invalid_refs)} evidence reference(s) could not be verified")
    if not candidate.supporting_evidence:
        reasons.append("the candidate quotes no supporting evidence")

    outside = sorted(
        {ref.paper_id for ref in candidate.supporting_evidence} - set(unique_supporting)
    )
    checks.append(
        _check(
            "evidence_subset_of_supporting_papers",
            not outside,
            "every evidence reference belongs to a declared supporting paper"
            if not outside
            else f"evidence cites non-supporting papers: {outside}",
        )
    )
    if outside:
        reasons.append(f"evidence references non-supporting papers: {outside}")

    unverified: list[str] = []
    for pid, paper in papers.items():
        if paper is None:
            continue
        doi = (paper.doi or "").strip()
        if not doi or not DOI_PATTERN.match(doi):
            unverified.append(pid)
    checks.append(
        _check(
            "doi_present_and_wellformed",
            not unverified,
            f"{len(papers) - len(unverified)}/{len(papers)} supporting papers carry a "
            "well-formed DOI from a real source record. No external DOI resolution was "
            "performed, so this is a format and provenance check, not a registry lookup."
            + (f"; without a usable DOI: {unverified}" if unverified else ""),
        )
    )

    counter_status = counter.status
    require_success = bool(gate["require_counter_search_success"])
    search_ok = counter_status not in FAILED_SEARCH_STATUSES
    specific_key = bool(counter.detection_key.strip())
    checks.append(
        _check(
            "counter_search_targets_the_claim",
            specific_key or not search_ok,
            f"detection_key = '{counter.detection_key}'"
            if specific_key
            else "no specific detection key could be derived, so retrieved papers could "
            "only be matched against the general topic",
        )
    )
    checks.append(
        _check(
            "counter_search_completed",
            search_ok or not require_success,
            f"counter-evidence search status = {counter_status}"
            + (
                "; a failed or unrun search is never treated as 'no counter-evidence'"
                if not search_ok
                else f"; {counter.requests_made} real request(s), "
                f"{counter.cache_hits} cache hit(s), "
                f"{counter.papers_retrieved} paper(s) retrieved, "
                f"{counter.rejected_as_not_addressing_claim} rejected as off-claim"
            ),
        )
    )
    if not search_ok:
        reasons.append(
            f"counter-evidence search did not complete ({counter_status}); the gap cannot "
            "be cleared by an absence of results"
        )

    collisions = len(counter.prior_art)
    max_collisions = int(gate["max_prior_art_collisions"])
    checks.append(
        _check(
            "prior_art_collisions",
            collisions <= max_collisions,
            f"{collisions} retrieved paper(s) address this specific claim; gate allows "
            f"{max_collisions}",
        )
    )

    novelty_risk: RiskLabel = critique.novelty_risk if critique else "MEDIUM"
    if collisions:
        novelty_risk = "HIGH"
    if len(unique_supporting) < min_support:
        novelty_risk = _risk_at_least(novelty_risk, "MEDIUM")
    max_novelty = gate["max_novelty_risk"]
    checks.append(
        _check(
            "novelty_risk_within_gate",
            RISK_ORDER[novelty_risk] <= RISK_ORDER[max_novelty],
            f"novelty_risk = {novelty_risk} (gate allows at most {max_novelty})"
            + (
                f"; potential prior art: {[p.get('paper_id') for p in counter.prior_art]}"
                if collisions
                else ""
            ),
        )
    )

    contradicting = len(candidate.contradicting_evidence)
    contradiction_risk: RiskLabel = critique.contradiction_risk if critique else "MEDIUM"
    evidence_contradiction = contradicting > 0
    if evidence_contradiction:
        contradiction_risk = _risk_at_least(contradiction_risk, "MEDIUM")
    max_contradiction = gate["max_contradiction_risk"]
    checks.append(
        _check(
            "contradiction_risk_within_gate",
            RISK_ORDER[contradiction_risk] <= RISK_ORDER[max_contradiction],
            f"contradiction_risk = {contradiction_risk} (gate allows at most "
            f"{max_contradiction}); {contradicting} contradicting evidence reference(s)",
        )
    )

    claim = candidate.gap_claim.strip().lower()
    generic = len(claim) < 30 or any(phrase in claim for phrase in GENERIC_CLAIMS)
    checks.append(
        _check(
            "claim_is_specific",
            not generic,
            "the claim is a specific statement, not a generic 'more research is needed'"
            if not generic
            else "the claim is too short or too generic to be a research gap",
        )
    )
    if generic:
        reasons.append("the gap claim is generic rather than specific")

    if critique is not None:
        for name, key in (
            ("evidence_grounding", "min_evidence_grounding"),
            ("cross_paper_support", "min_cross_paper_support"),
            ("specificity", "min_specificity"),
            ("testability", "min_testability"),
        ):
            score = getattr(critique, name)
            threshold = int(gate[key])
            checks.append(
                _check(
                    f"critic_{name}",
                    score >= threshold,
                    f"critic scored {name} = {score}/5; gate requires {threshold}",
                )
            )
        checks.append(
            _check(
                "critic_does_not_reject",
                critique.recommended_action != "reject",
                f"critic recommended_action = {critique.recommended_action}",
            )
        )
    else:
        checks.append(
            _check(
                "critic_available",
                False,
                "no critic review was recorded for this candidate",
            )
        )
        reasons.append("the candidate has no independent critic review")

    passed = all(c.passed for c in checks)
    return GapValidation(
        gap_index=gap_index,
        checks=checks,
        unique_supporting_papers=len(unique_supporting),
        unique_counter_papers=len({p.get("paper_id") for p in counter.prior_art}),
        valid_evidence_refs=valid_refs,
        invalid_evidence_refs=invalid_refs,
        missing_papers=missing,
        unverified_dois=unverified,
        duplicate_paper_counting=duplicate_counting,
        counter_search_status=counter_status,
        prior_art_collisions=collisions,
        novelty_risk=novelty_risk,
        evidence_contradiction=evidence_contradiction,
        passed=passed,
        reasons=reasons,
    )


def decide_gate(
    validation: GapValidation,
    critique: GapCritique | None,
    *,
    gap_index: int = 0,
    gate: dict[str, Any] | None = None,
) -> GapGateResult:
    """Map verified facts onto accepted / needs_human_review / rejected."""
    gate = gate if gate is not None else get_settings().gap_gate
    hard_failures = [
        c for c in validation.checks if not c.passed and c.name in _HARD_CHECKS
    ]
    critic_rejected = critique is not None and critique.recommended_action == "reject"
    if hard_failures or critic_rejected or not validation.checks:
        status = "rejected"
        reasons = [c.detail for c in hard_failures] or list(validation.reasons)
        if critic_rejected:
            reasons.append("the independent critic recommended reject")
    elif validation.passed:
        status = "accepted"
        reasons = [
            "every configured Python check and critic threshold was met within the "
            "current search scope"
        ]
    else:
        status = "needs_human_review"
        reasons = [c.detail for c in validation.checks if not c.passed]
    return GapGateResult(
        gap_index=gap_index,
        status=status,
        python_passed=validation.passed,
        critic_rejected=critic_rejected,
        reasons=reasons,
        thresholds=dict(gate),
        notice=GATE_NOTICE,
    )