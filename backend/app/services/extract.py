"""Heuristic extraction of structured fields from abstracts.

This module extracts research_problem, method, dataset, evaluation_metrics,
findings, limitations, and future_work from paper abstracts using cue-word
matching. Each extraction carries an evidence_span (verbatim sentence) and
evidence_source="abstract".

The goal is evidence navigation, not academic conclusion: we surface the most
relevant sentences so researchers can quickly judge whether to read further.
"""

from __future__ import annotations

import re
from typing import Literal

from ..models.paper import EXTRACTED_FIELDS, Confidence, FieldEvidence, Paper

CueCategory = Literal[
    "research_problem",
    "method",
    "agent_architecture",
    "memory_strategy",
    "skill_strategy",
    "dataset",
    "evaluation_metrics",
    "findings",
    "limitations",
    "future_work",
]

# Cue words/phrases for each category (English + Chinese)
CUE_PATTERNS: dict[CueCategory, list[str]] = {
    "research_problem": [
        "problem",
        "challenge",
        "however",
        "existing approaches",
        "difficult",
        "hard",
        "limited",
        "难以",
        "尚缺乏",
        "不足",
        "challenge is",
        "remains a challenge",
    ],
    "method": [
        "we propose",
        "we present",
        "we develop",
        "our approach",
        "we design",
        "本文提出",
        "方法",
        "propose a",
        "present a",
        "develop a",
    ],
    "agent_architecture": [
        "multi-agent",
        "multi agent",
        "single-agent",
        "agent architecture",
        "planner",
        "executor",
        "orchestrat",
        "tool-use",
        "tool use",
        "react-style",
        "workflow",
        "智能体架构",
        "多智能体",
        "规划器",
    ],
    "memory_strategy": [
        "episodic memory",
        "semantic memory",
        "working memory",
        "long-term memory",
        "short-term memory",
        "memory module",
        "memory mechanism",
        "memory bank",
        "retrieval-augmented",
        "retrieval augmented",
        "vector store",
        "context compression",
        "记忆机制",
        "检索增强",
        "长期记忆",
    ],
    "skill_strategy": [
        "skill library",
        "skill learning",
        "skill acquisition",
        "reusable skill",
        "self-improvement",
        "self-evolving",
        "self-evolution",
        "experience replay",
        "learning from trajectories",
        "failure trajectories",
        "技能库",
        "经验复用",
        "自我进化",
    ],
    "dataset": [
        "dataset",
        "benchmark",
        "experiments on",
        "corpus",
        "we evaluate on",
        "数据集",
        "evaluated on",
        "tested on",
    ],
    "evaluation_metrics": [
        "accuracy",
        "F1",
        "recall",
        "precision",
        "MRR",
        "指标",
        "评价",
        "metric",
        "measured by",
    ],
    "findings": [
        "results show",
        "outperform",
        "improve by",
        "achieves",
        "实验表明",
        "提升",
        "demonstrate",
        "achieve",
        "show that",
    ],
    "limitations": [
        "limitation",
        "however",
        "still remains",
        "cannot",
        "不足",
        "局限",
        "drawback",
        "weakness",
    ],
    "future_work": [
        "future work",
        "remain",
        "further investigate",
        "展望",
        "future research",
        "future studies",
    ],
}

# Priority order when multiple categories match the same sentence
PRIORITY_ORDER: list[CueCategory] = [
    "method",
    "agent_architecture",
    "memory_strategy",
    "skill_strategy",
    "dataset",
    "evaluation_metrics",
    "findings",
    "research_problem",
    "limitations",
    "future_work",
]


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences on . ! ? followed by space or end."""
    if not text:
        return []
    # Simple regex: split on sentence-ending punctuation followed by space or end
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\u4e00-\u9fff])", text)
    return [s.strip() for s in sentences if s.strip()]


def _match_cues(sentence: str, category: CueCategory) -> bool:
    """Check if sentence contains any cue for the category."""
    sentence_lower = sentence.lower()
    cues = CUE_PATTERNS.get(category, [])
    return any(cue.lower() in sentence_lower for cue in cues)


def extract_from_abstract(paper: Paper) -> Paper:
    """Extract structured fields from paper abstract using cue matching.

    For each extracted field, we set:
    - value: the matched sentence(s)
    - evidence_source: "abstract"
    - evidence_span: verbatim sentence
    - confidence: "medium" (single cue) or "high" (multiple cues)

    Fields that don't match any cue remain as unknown (evidence_source="none").
    """
    if not paper.abstract:
        return paper

    sentences = _split_sentences(paper.abstract)
    if not sentences:
        return paper

    # For each category, collect matching sentences
    matches: dict[CueCategory, list[str]] = {cat: [] for cat in EXTRACTED_FIELDS}

    for sentence in sentences:
        matched_categories: list[CueCategory] = []
        for category in PRIORITY_ORDER:
            if _match_cues(sentence, category):
                matched_categories.append(category)

        # Assign to ALL matching categories (not just highest priority)
        for category in matched_categories:
            matches[category].append(sentence)

    # Build FieldEvidence for each category
    for category in EXTRACTED_FIELDS:
        if matches[category]:
            value = " ".join(matches[category])
            span = matches[category][0]  # first sentence as primary span
            confidence: Confidence = "high" if len(matches[category]) > 1 else "medium"
            evidence = FieldEvidence(
                value=value,
                evidence_source="abstract",
                evidence_span=span,
                source_url=paper.source_url,
                confidence=confidence,
                extraction_method="heuristic",
            )
            setattr(paper, category, evidence)

    return paper
