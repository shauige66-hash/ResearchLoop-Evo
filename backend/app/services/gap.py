"""Candidate research gap detection by comparing experimental scope across papers.

Every rule here needs at least two papers. Absence-based rules (nobody in the
compared set measures X) are explicitly weaker than presence-based rules (two
papers independently state the same limitation), and the confidence label records
which kind of evidence produced the gap.

Nothing in this module concludes that a gap exists. It proposes candidates for
human review, then runs a real counter-evidence search against all three sources.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from ..models.gap import (
    ConfidenceLabel,
    CounterEvidenceItem,
    Experimentability,
    GapEvidenceItem,
    GapType,
    RelatedWork,
    ResearchGap,
)
from ..models.paper import Paper
from ..models.schemas import TopicInput
from .classify import UNCLASSIFIED, classify_method
from .pipeline import search_pipeline

# Capability signals looked for in retrieved text. Absence of a signal is only
# ever a statement about the retrieved abstracts, never about the paper itself.
SIGNAL_CUES: dict[str, tuple[str, ...]] = {
    "generalization": (
        "unseen", "held-out", "holdout", "out-of-distribution", "cross-domain",
        "cross domain", "transfer to", "generaliz", "generalis", "new subtopic",
        "泛化", "未见",
    ),
    "reliability": (
        "robust", "failure rate", "adversarial", "poisoning", "privacy", "attack",
        "hallucination", "error analysis", "reliability", "鲁棒", "可靠性",
    ),
    "efficiency": (
        "latency", "runtime", "execution time", "token cost", "api cost", "cost-",
        "memory footprint", "throughput", "efficien", "开销", "耗时", "成本",
    ),
    "reproducibility": (
        "code is available", "code available", "open source", "open-source", "github",
        "we release", "publicly available", "artifact", "reproduc", "开源", "代码公开",
    ),
}

METRIC_FAMILIES: dict[str, tuple[str, ...]] = {
    "accuracy": ("accuracy", "acc@", "正确率"),
    "f1": ("f1", "f-measure", "precision", "recall"),
    "retrieval": ("mrr", "ndcg", "recall@", "hit rate", "coverage@", "map"),
    "generation": ("bleu", "rouge", "meteor", "bertscore", "perplexity"),
    "human": ("human eval", "human judg", "annotator", "user study", "人工评"),
    "efficiency": ("latency", "tokens", "runtime", "cost", "耗时"),
}

_ABSENCE_RULES: tuple[tuple[GapType, str], ...] = (
    ("generalization", "generalization"),
    ("reliability", "reliability"),
    ("efficiency", "efficiency"),
    ("reproducibility", "reproducibility"),
)

# Generic words that recur in any limitation sentence and therefore say nothing
# about a shared technical constraint.
_LIMITATION_STOPWORDS: frozenset[str] = frozenset("""
about above across after again against also although always among another around
because before being below between both cannot could does doing down during each
either else even ever every from further have having here however into itself
just like little many more most much must need neither never none nor only onto
other others otherwise ought ours ourselves over own rather really remains
same shall should since some such than that their theirs them themselves then
there these they this those through thus till toward under until upon used
using very want were what when where whether which while whom whose will with
within without would your user users study studies paper papers work works
approach approaches method methods result results show shows shown found
findings limited limitation limitations future futurework
""".split())

EXPERIMENTABILITY: dict[GapType, Experimentability] = {
    "evaluation": Experimentability(
        testable_minimally=True,
        proposed_experiment=(
            "Compare metric-family coverage across a human-confirmed reference set "
            "under a fixed retrieval budget."
        ),
        required_inputs=["human-confirmed benchmark reference DOIs", "fixed API budget"],
    ),
    "generalization": Experimentability(
        testable_minimally=True,
        proposed_experiment=(
            "Measure Reference Coverage@K on held-out subtopics that the active "
            "search strategy has never been tuned on."
        ),
        required_inputs=["topic-grouped Development/Validation/Holdout splits",
                         "human-confirmed reference DOIs"],
    ),
    "efficiency": Experimentability(
        testable_minimally=True,
        proposed_experiment=(
            "Measure API query count and execution time for the same reference set "
            "under baseline and candidate strategies."
        ),
        required_inputs=["fixed API budget", "identical source set and top-k"],
    ),
    "method": Experimentability(
        testable_minimally=False,
        proposed_experiment="Implement and train the missing mechanism.",
        blocking_reason=(
            "Requires building a new mechanism and full-text reading, which is outside "
            "the minimal experiment budget of this prototype."
        ),
    ),
    "reliability": Experimentability(
        testable_minimally=False,
        proposed_experiment="Run adversarial and failure-mode evaluations.",
        blocking_reason="Requires adversarial evaluation infrastructure and full-text protocols.",
    ),
    "reproducibility": Experimentability(
        testable_minimally=False,
        proposed_experiment="Re-run the authors' released artifacts.",
        blocking_reason="Requires artifact availability checks and executing third-party code.",
    ),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text(paper: Paper, fields: tuple[str, ...]) -> str:
    parts: list[str] = []
    for name in fields:
        ev = getattr(paper, name)
        if ev.is_known and ev.value:
            parts.append(ev.value)
    return " ".join(parts).lower()


def _has_signal(paper: Paper, signal: str) -> bool:
    text = _text(
        paper,
        ("findings", "dataset", "evaluation_metrics", "limitations", "method"),
    )
    if paper.abstract:
        text += " " + paper.abstract.lower()
    return any(cue in text for cue in SIGNAL_CUES[signal])


def _metric_families(paper: Paper) -> set[str]:
    text = _text(paper, ("evaluation_metrics", "findings"))
    return {fam for fam, cues in METRIC_FAMILIES.items() if any(c in text for c in cues)}


def _search_text(paper: Paper) -> str:
    parts = [paper.title or "", paper.abstract or ""]
    for name in ("method", "findings", "evaluation_metrics", "limitations", "dataset"):
        ev = getattr(paper, name)
        if ev.is_known and ev.value:
            parts.append(ev.value)
    return " ".join(p for p in parts if p)


def _snippet(text: str, cue: str, width: int = 220) -> str:
    idx = text.lower().find(cue.lower())
    if idx < 0:
        return text[:width].strip()
    start = max(0, idx - width // 3)
    return text[start : start + width].strip()


def _counter_match(paper: Paper, gap: ResearchGap) -> tuple[str, str] | None:
    """Does this retrieved paper actually address the specific claim of the gap?

    Being about the same topic is not counter-evidence. The paper must mention the
    capability the compared set lacked, bridge the disjoint metric families, or
    engage with the recurring constraint term.
    """
    key = gap.detection_key.strip()
    if not key:
        return None
    haystack = _search_text(paper)
    lowered = haystack.lower()

    if gap.gap_type in SIGNAL_CUES:
        cues = SIGNAL_CUES.get(key, (key,))
        matched = next((c for c in cues if c in lowered), None)
        return (matched, _snippet(haystack, matched)) if matched else None

    if gap.gap_type == "evaluation":
        wanted = {f for f in key.split(",") if f}
        families = {
            fam for fam, cues in METRIC_FAMILIES.items() if any(c in lowered for c in cues)
        }
        shared = sorted(wanted & families)
        # One family alone cannot make two disjoint evaluations comparable.
        if len(shared) < 2:
            return None
        cue = next(
            (c for fam in shared for c in METRIC_FAMILIES[fam] if c in lowered), shared[0]
        )
        return ", ".join(shared), _snippet(haystack, cue)

    if key not in lowered:
        return None
    return key, _snippet(haystack, key)


def _evidence(papers: list[Paper], fields: tuple[str, ...]) -> list[GapEvidenceItem]:
    items: list[GapEvidenceItem] = []
    for paper in papers:
        for name in fields:
            ev = getattr(paper, name)
            if ev.is_known and ev.evidence_span:
                items.append(
                    GapEvidenceItem(
                        paper_id=paper.paper_id,
                        title=paper.title,
                        doi=paper.doi,
                        source_url=paper.source_url,
                        field=name,
                        evidence_span=ev.evidence_span,
                        extraction_method=ev.extraction_method,
                    )
                )
    return items


def _label(positive: bool, support_count: int, counter_count: int) -> tuple[ConfidenceLabel, str]:
    if positive and support_count >= 3:
        base: ConfidenceLabel = "High"
        why = f"{support_count} papers independently state the limitation"
    elif positive or support_count >= 3:
        base = "Medium"
        why = (
            f"{support_count} papers state the limitation"
            if positive
            else f"absence observed across {support_count} papers, no positive statement"
        )
    else:
        base = "Low"
        why = f"absence observed across only {support_count} papers, no positive statement"

    if counter_count:
        downgraded: dict[ConfidenceLabel, ConfidenceLabel] = {
            "High": "Medium", "Medium": "Low", "Low": "Low",
        }
        final = downgraded[base]
        why += (
            f"; downgraded from {base} because {counter_count} counter-evidence "
            "paper(s) were retrieved"
        )
    else:
        final = base
        why += "; no counter-evidence found within the current search scope"
    return final, why


class ResearchGapAnalyzer:
    """Compare a set of retrieved papers and propose candidate gaps."""

    def __init__(self, papers: list[Paper], topic: str, run_id: str) -> None:
        self.papers = papers
        self.topic = topic
        self.run_id = run_id
        for paper in self.papers:
            if not paper.method_class:
                paper.method_class = classify_method(paper)

    # ------------------------------------------------------------------ rules
    def _groups(self) -> dict[str, list[Paper]]:
        groups: dict[str, list[Paper]] = {}
        for paper in self.papers:
            label = paper.method_class or UNCLASSIFIED
            if label == UNCLASSIFIED:
                continue
            groups.setdefault(label, []).append(paper)
        return {k: v for k, v in groups.items() if len(v) >= 2}

    def _method_gaps(self, group: list[Paper], label: str) -> list[ResearchGap]:
        """Two or more papers independently reporting a limitation is positive evidence."""
        with_limits = [p for p in group if p.limitations.is_known and p.limitations.evidence_span]
        if len(with_limits) < 2:
            return []
        shared = self._shared_limitation_terms(with_limits)
        if not shared:
            return []
        term = shared[0]
        gap = self._build(
            gap_type="method",
            title=f"Recurring method limitation around '{term}' in {label}",
            description=(
                f"{len(with_limits)} independent works classified as '{label}' report "
                f"limitations mentioning '{term}'. Because the same constraint recurs "
                "across separate methods, it is a candidate method gap rather than one "
                "paper's wish list."
            ),
            papers=with_limits,
            fields=("limitations", "method"),
            positive=True,
            unresolved_question=(
                f"Can a {label} approach remove the '{term}' constraint without "
                "sacrificing the reported gains?"
            ),
            detection_key=term,
        )
        return [gap] if gap else []

    def _shared_limitation_terms(self, papers: list[Paper]) -> list[str]:
        stop = _LIMITATION_STOPWORDS
        # A word shared by every limitation because it is the topic itself carries
        # no information about a recurring constraint.
        stop = stop | set(re.findall(r"[a-z]{4,}", self.topic.lower()))
        counts: dict[str, int] = {}
        for paper in papers:
            words = set(re.findall(r"[a-z]{4,}", (paper.limitations.value or "").lower()))
            for word in words - stop:
                counts[word] = counts.get(word, 0) + 1
        return [w for w, c in sorted(counts.items(), key=lambda kv: -kv[1]) if c >= 2]

    def _evaluation_gaps(self, group: list[Paper], label: str) -> list[ResearchGap]:
        measured = [p for p in group if p.evaluation_metrics.is_known]
        if len(measured) < 2:
            return []
        families = {p.paper_id: _metric_families(p) for p in measured}
        populated = {pid: fam for pid, fam in families.items() if fam}
        if len(populated) < 2:
            return []
        sets = list(populated.values())
        union = set().union(*sets)
        intersection = set.intersection(*sets)
        if not union or intersection:
            return []
        papers = [p for p in measured if p.paper_id in populated]
        gap = self._build(
            gap_type="evaluation",
            title=f"Disjoint metric families among {label} works",
            description=(
                f"{len(papers)} works in '{label}' report evaluation metrics, but they "
                f"share no common metric family (union: {', '.join(sorted(union))}). "
                "Their results are therefore not directly comparable, which is a "
                "candidate evaluation gap."
            ),
            papers=papers,
            fields=("evaluation_metrics", "dataset"),
            positive=True,
            unresolved_question=(
                "Which shared metric family would make these results comparable?"
            ),
            detection_key=",".join(sorted(union)),
        )
        return [gap] if gap else []

    def _absence_gaps(self, group: list[Paper], label: str) -> list[ResearchGap]:
        gaps: list[ResearchGap] = []
        for gap_type, signal in _ABSENCE_RULES:
            if any(_has_signal(p, signal) for p in group):
                continue
            papers = [p for p in group if p.abstract]
            if len(papers) < 2:
                continue
            gap = self._build(
                gap_type=gap_type,
                title=f"No {signal} evidence among compared {label} works",
                description=(
                    f"None of the {len(papers)} compared '{label}' abstracts mentions "
                    f"{signal}. This is an observation about the retrieved abstracts only; "
                    "the papers may address it in full text we have not read."
                ),
                papers=papers,
                fields=("dataset", "evaluation_metrics", "limitations"),
                positive=False,
                unresolved_question=(
                    f"Do these {label} approaches actually hold up under {signal} testing?"
                ),
                detection_key=signal,
            )
            if gap:
                gaps.append(gap)
        return gaps

    def _build(
        self,
        *,
        gap_type: GapType,
        title: str,
        description: str,
        papers: list[Paper],
        fields: tuple[str, ...],
        positive: bool,
        unresolved_question: str,
        detection_key: str = "",
    ) -> ResearchGap | None:
        evidence = _evidence(papers, fields)
        if not evidence:
            evidence = _evidence(papers, ("method", "research_problem", "findings"))
        if not evidence:
            # Absence-based gap on papers whose abstract yielded no cue match:
            # quote the abstract that was actually examined.
            evidence = [
                GapEvidenceItem(
                    paper_id=p.paper_id,
                    title=p.title,
                    doi=p.doi,
                    source_url=p.source_url,
                    field="abstract",
                    evidence_span=(p.abstract or "")[:400],
                    extraction_method="heuristic",
                )
                for p in papers
                if p.abstract and p.abstract.strip()
            ]
        if len(evidence) < 2:
            return None
        label, rationale = _label(positive, len(papers), 0)
        return ResearchGap(
            gap_id=f"gap_{uuid.uuid4().hex[:12]}",
            title=title,
            description=description,
            gap_type=gap_type,
            supporting_papers=[p.paper_id for p in papers],
            supporting_evidence=evidence,
            closest_related_work=self._closest(papers),
            unresolved_question=unresolved_question,
            experimentability=EXPERIMENTABILITY[gap_type],
            confidence_label=label,
            confidence_rationale=rationale,
            run_id=self.run_id,
            topic=self.topic,
            detection_key=detection_key,
            counter_search_queries=[self.counter_query(gap_type, detection_key)],
            created_at=_now(),
        )

    def _closest(self, papers: list[Paper]) -> list[RelatedWork]:
        ranked = sorted(
            papers,
            key=lambda p: (p.citation_count or 0, p.publication_year or 0),
            reverse=True,
        )[:3]
        return [
            RelatedWork(
                paper_id=p.paper_id,
                title=p.title,
                doi=p.doi,
                source_url=p.source_url,
                method_class=p.method_class,
                why_closest=(
                    f"Same method class '{p.method_class}'; "
                    f"citations={p.citation_count if p.citation_count is not None else 'unknown'}"
                ),
            )
            for p in ranked
        ]

    def counter_query(self, gap_type: GapType, detection_key: str = "") -> str:
        """Build a query that would surface work already solving this specific gap."""
        keywords = {
            "method": "method improvement",
            "evaluation": "shared evaluation metrics benchmark",
            "generalization": "unseen subtopic generalization held-out",
            "reliability": "robustness failure evaluation",
            "efficiency": "cost latency efficiency measurement",
            "reproducibility": "open source artifact reproducibility",
        }[gap_type]
        key = detection_key.strip()
        if key and gap_type == "method":
            keywords = f"{key} improvement"
        elif key and gap_type == "evaluation":
            families = [f for f in key.split(",") if f]
            if families:
                keywords = " ".join(families[:3]) + " shared benchmark"
        topic = self.topic.strip() or "LLM agent"
        return f"{topic} {keywords}"

    # ----------------------------------------------------------------- public
    def analyze(self, max_gaps: int = 6, per_type_limit: int = 2) -> list[ResearchGap]:
        gaps: list[ResearchGap] = []
        for label, group in self._groups().items():
            gaps.extend(self._method_gaps(group, label))
            gaps.extend(self._evaluation_gaps(group, label))
            gaps.extend(self._absence_gaps(group, label))
        # Positive-evidence gaps first; they are the ones a reviewer can act on.
        order = {"method": 0, "evaluation": 1, "generalization": 2,
                 "reliability": 3, "efficiency": 4, "reproducibility": 5}
        gaps.sort(key=lambda g: (order[g.gap_type], g.confidence_label))
        selected: list[ResearchGap] = []
        per_type: dict[str, int] = {}
        for gap in gaps:
            if per_type.get(gap.gap_type, 0) >= per_type_limit:
                continue
            per_type[gap.gap_type] = per_type.get(gap.gap_type, 0) + 1
            selected.append(gap)
            if len(selected) >= max_gaps:
                break
        return selected

    async def add_counter_evidence(
        self, gaps: list[ResearchGap], top_k: int = 10
    ) -> list[ResearchGap]:
        """Run a real counter-evidence search per gap across all three sources.

        A retrieved paper only counts as counter-evidence if it addresses the
        specific claim of the gap, not merely the same topic.
        """
        for gap in gaps:
            query = gap.counter_search_queries[0] if gap.counter_search_queries else (
                self.counter_query(gap.gap_type, gap.detection_key)
            )
            topic = TopicInput(
                topic=self.topic.strip() or query,
                keywords=[query],
                sources=["openalex", "crossref", "arxiv"],
                top_k=top_k,
                expand_keywords=False,
                refresh=False,
            )
            response = await search_pipeline(topic)
            supporting = set(gap.supporting_papers)
            found: list[CounterEvidenceItem] = []
            retrieved = 0
            off_claim = 0
            for paper in response.papers:
                if paper.paper_id in supporting:
                    continue
                retrieved += 1
                match = _counter_match(paper, gap)
                if match is None:
                    off_claim += 1
                    continue
                cue, span = match
                found.append(
                    CounterEvidenceItem(
                        paper_id=paper.paper_id,
                        title=paper.title,
                        doi=paper.doi,
                        source=paper.source,
                        source_url=paper.source_url,
                        publication_year=paper.publication_year,
                        abstract_snippet=(paper.abstract or "")[:400] or None,
                        matched_query=query,
                        matched_cue=cue,
                        evidence_span=span,
                        why_relevant=(
                            f"Addresses the specific '{gap.gap_type}' claim: retrieved text "
                            f"matches '{cue}' (detection key '{gap.detection_key}'). "
                            f"Method class '{paper.method_class or UNCLASSIFIED}'."
                        ),
                    )
                )
            gap.counter_search_scope = {
                "sources": topic.sources,
                "top_k": top_k,
                "query": query,
                "requests_made": response.meta.get("requests_made", 0),
                "cache_hits": response.meta.get("cache_hits", 0),
                "papers_retrieved": retrieved,
                "rejected_as_not_addressing_claim": off_claim,
                "acceptance_rule": (
                    "counter-evidence must match the gap's detection key, not just the topic"
                ),
            }
            gap.counter_search_errors = [e.model_dump() for e in response.source_errors]
            gap.counter_evidence = found
            positive = gap.gap_type in ("method", "evaluation")
            label, rationale = _label(positive, len(gap.supporting_papers), len(found))
            gap.confidence_label = label
            gap.confidence_rationale = rationale
            gap.updated_at = _now()
        return gaps