"""Audit records for every LLM call.

Only hashes of prompts and responses are persisted, never the prompt text and
never the API key. Token counts are recorded when the provider returns them and
stay None when it does not, so a missing number is never invented.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# A call that never reached the network is still recorded, with the reason.
LLMCallStatus = Literal[
    "success",
    "failed",
    "cache_hit",
    "budget_exhausted",
    "not_configured",
    "output_rejected",
]

# Only these statuses consumed a real HTTP attempt against RLE_LLM_MAX_CALLS.
BILLABLE_STATUSES: frozenset[str] = frozenset({"success", "failed", "output_rejected"})

# The literal the API and the UI must show when no provider is configured.
LLM_NOT_CONFIGURED = "LLM_NOT_CONFIGURED"

NOT_CONFIGURED_REASON = (
    "LLM_NOT_CONFIGURED: RLE_LLM_ENABLED / RLE_LLM_API_KEY / RLE_LLM_BASE_URL / "
    "RLE_LLM_MODEL are not all set on the server. No LLM call was made and no LLM "
    "output exists for this stage."
)


class LLMCallRecord(BaseModel):
    request_id: str
    agent_role: str
    provider: str
    model: str
    status: LLMCallStatus
    prompt_version: str
    prompt_hash: str
    response_hash: str | None = None
    pipeline_id: str | None = None
    paper_id: str | None = None
    latency_ms: int | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    error: str | None = None
    created_at: str = ""


class LLMUsageSummary(BaseModel):
    """Cost transparency: real attempts, free cache hits, and the configured ceiling."""

    configured: bool
    status: str = "not_configured"
    provider: str
    model: str
    max_calls: int
    calls_used: int
    cache_hits: int
    role_budgets: dict[str, int] = Field(default_factory=dict)
    role_usage: dict[str, int] = Field(default_factory=dict)
    failed_calls: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    notice: str = (
        "calls_used counts real HTTP attempts, including failures. Cache hits are free "
        "and are reported separately. Token counts are None when the provider did not "
        "return usage."
    )