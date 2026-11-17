"""Deterministic method classification for matrix grouping and gap comparison.

The label is a system inference over retrieved title/abstract text, not a claim
made by the paper's authors. It is deliberately coarse: the gap analyzer compares
experimental scope across papers, so the classes must be stable and reproducible
rather than clever.
"""

from __future__ import annotations

from ..models.paper import Paper

# Ordered: the first class whose cues match wins.
METHOD_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "survey / review",
        ("survey", "systematic review", "literature review", "综述", "a review of"),
    ),
    (
        "benchmark / evaluation",
        ("benchmark", "we introduce a dataset", "evaluation suite", "testbed", "评测基准"),
    ),
    (
        "security / robustness",
        ("poisoning", "privacy", "attack", "adversarial", "jailbreak", "安全", "隐私"),
    ),
    (
        "skill / experience learning",
        ("skill library", "skill learning", "self-evolving", "self-improvement",
         "learning from experience", "trajectory", "技能", "经验"),
    ),
    (
        "memory-augmented agent",
        ("episodic memory", "semantic memory", "long-term memory", "memory mechanism",
         "memory module", "memory bank", "记忆"),
    ),
    (
        "retrieval-augmented generation",
        ("retrieval-augmented", "retrieval augmented", "rag", "dense retrieval", "检索增强"),
    ),
    (
        "multi-agent system",
        ("multi-agent", "multi agent", "agent collaboration", "多智能体"),
    ),
    (
        "planning / reasoning",
        ("planner", "planning", "chain-of-thought", "reasoning", "tool use", "规划", "推理"),
    ),
    (
        "fine-tuning / training",
        ("fine-tuning", "fine tuning", "finetune", "reinforcement learning", "distillation",
         "微调", "强化学习"),
    ),
    (
        "prompt engineering",
        ("prompt engineering", "prompt design", "in-context learning", "提示工程"),
    ),
)

UNCLASSIFIED = "other / unclassified"


def classify_method(paper: Paper) -> str:
    """Assign a coarse method class from retrieved text, or UNCLASSIFIED."""
    if paper.is_review:
        return "survey / review"
    parts = [paper.title or ""]
    for name in ("method", "research_problem", "agent_architecture", "memory_strategy"):
        field = getattr(paper, name)
        if field.is_known and field.value:
            parts.append(field.value)
    if paper.abstract:
        parts.append(paper.abstract)
    text = " ".join(parts).lower()
    for label, cues in METHOD_CLASSES:
        if any(cue in text for cue in cues):
            return label
    return UNCLASSIFIED