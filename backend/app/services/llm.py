"""The single OpenAI-compatible LLM entry point used by every agent.

Rules this module enforces, because a research product cannot afford a model
quietly grading its own homework:

- the API key comes from the environment only, is sent as a header, and is never
  written to the database, the logs, a response body or an error string;
- every attempt is audited with hashes of the prompt and the reply, never their
  text, plus latency and whatever token usage the provider actually returned;
- real HTTP attempts (including failures) consume `RLE_LLM_MAX_CALLS` and the
  per-role ceiling; cache hits are free and are reported separately;
- a reply that does not validate against the caller's schema is rejected and is
  not cached, so a malformed answer can never be replayed as a success;
- when no provider is configured the call raises `LLMNotConfigured`. Nothing is
  fabricated and no fake "LLM result" is produced.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from ..config import DEFAULT_ROLE_BUDGETS, get_settings
from ..models.gap_pipeline import PROMPT_VERSION
from ..models.llm import (
    LLM_NOT_CONFIGURED,
    NOT_CONFIGURED_REASON,
    LLMCallRecord,
    LLMUsageSummary,
)
from ..storage.store import Store

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)


class LLMError(Exception):
    """Base class carrying the audit row that explains what happened."""

    def __init__(self, message: str, record: LLMCallRecord | None = None) -> None:
        super().__init__(message)
        self.record = record


class LLMNotConfigured(LLMError):
    pass


class LLMBudgetExhausted(LLMError):
    pass


class LLMCallFailed(LLMError):
    pass


class LLMOutputRejected(LLMError):
    pass


@dataclass
class LLMReply:
    content: str
    record: LLMCallRecord
    from_cache: bool = False
    parsed: Any | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _strip_code_fence(text: str) -> str:
    """Some providers wrap JSON in a markdown fence despite being asked not to."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1] if "\n" in cleaned else ""
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3]
    return cleaned.strip()


class LLMProvider:
    """Chat-completions client with audit, budget and response cache.

    Tests inject a fake with the same `complete` signature; application code only
    ever constructs this real one.
    """

    def __init__(self, store: Store) -> None:
        self.store = store

    @property
    def settings(self):
        return get_settings()

    @property
    def configured(self) -> bool:
        return self.settings.llm_configured

    # ------------------------------------------------------------------ budget
    def role_budget(self, agent_role: str) -> int:
        return self.settings.llm_role_budgets.get(
            agent_role, DEFAULT_ROLE_BUDGETS.get(agent_role, 5)
        )

    def usage_summary(self) -> LLMUsageSummary:
        settings = self.settings
        records = self.store.list_llm_calls()
        used = self.store.count_llm_attempts()
        role_usage: dict[str, int] = {}
        tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        seen_tokens = False
        for record in records:
            if record.status in ("success", "failed", "output_rejected"):
                role_usage[record.agent_role] = role_usage.get(record.agent_role, 0) + 1
            for key in tokens:
                value = getattr(record, key)
                if value is not None:
                    tokens[key] += value
                    seen_tokens = True
        if not settings.llm_configured:
            status = LLM_NOT_CONFIGURED
        elif used >= settings.llm_max_calls:
            status = "budget_exhausted"
        else:
            status = "ready"
        summary = LLMUsageSummary(
            configured=settings.llm_configured,
            status=status,
            provider=settings.llm_provider_label,
            model=settings.llm_model,
            max_calls=settings.llm_max_calls,
            calls_used=used,
            cache_hits=sum(1 for r in records if r.status == "cache_hit"),
            role_budgets=dict(settings.llm_role_budgets),
            role_usage=role_usage,
            failed_calls=sum(1 for r in records if r.status in ("failed", "output_rejected")),
            prompt_tokens=tokens["prompt_tokens"] if seen_tokens else None,
            completion_tokens=tokens["completion_tokens"] if seen_tokens else None,
            total_tokens=tokens["total_tokens"] if seen_tokens else None,
        )
        if not settings.llm_configured:
            summary.notice = NOT_CONFIGURED_REASON
        return summary

    def _redact(self, text: str) -> str:
        key = self.settings.llm_api_key
        return text.replace(key, "[redacted]") if key else text

    def _record(
        self,
        *,
        agent_role: str,
        status: str,
        prompt_version: str,
        prompt_hash: str,
        response_hash: str | None = None,
        pipeline_id: str | None = None,
        paper_id: str | None = None,
        latency_ms: int | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> LLMCallRecord:
        settings = self.settings
        usage = usage or {}
        record = LLMCallRecord(
            request_id=f"llm_{uuid.uuid4().hex[:12]}",
            agent_role=agent_role,
            provider=settings.llm_provider_label,
            model=settings.llm_model,
            status=status,
            prompt_version=prompt_version,
            prompt_hash=prompt_hash,
            response_hash=response_hash,
            pipeline_id=pipeline_id,
            paper_id=paper_id,
            latency_ms=latency_ms,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            total_tokens=usage.get("total_tokens"),
            error=self._redact(error) if error else None,
            created_at=_now(),
        )
        self.store.record_llm_call(record)
        return record

    # -------------------------------------------------------------------- call
    async def _post(self, agent_role: str, system: str, user: str) -> tuple[str, dict[str, Any]]:
        """The only network seam. Tests replace this, never the budget or audit."""
        settings = self.settings
        async with httpx.AsyncClient(timeout=settings.llm_timeout, trust_env=False) as client:
            response = await client.post(
                settings.llm_base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                json={
                    "model": settings.llm_model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            response.raise_for_status()
            payload = response.json()
        return payload["choices"][0]["message"]["content"], payload.get("usage") or {}

    async def complete(
        self,
        agent_role: str,
        system: str,
        user: str,
        *,
        schema: type[SchemaT] | None = None,
        pipeline_id: str | None = None,
        paper_id: str | None = None,
        prompt_version: str = PROMPT_VERSION,
        refresh: bool = False,
    ) -> LLMReply:
        """One audited, budgeted call. Raises on every non-success path."""
        settings = self.settings
        prompt_hash = _sha256(
            json.dumps({"system": system, "user": user}, ensure_ascii=False, sort_keys=True)
        )
        common = {
            "agent_role": agent_role,
            "prompt_version": prompt_version,
            "prompt_hash": prompt_hash,
            "pipeline_id": pipeline_id,
            "paper_id": paper_id,
        }

        if not settings.llm_configured:
            record = self._record(status="not_configured", error=NOT_CONFIGURED_REASON, **common)
            raise LLMNotConfigured(NOT_CONFIGURED_REASON, record)

        cache_key = _sha256(
            f"{agent_role}\n{settings.llm_model}\n{prompt_version}\n{prompt_hash}"
        )
        if settings.llm_cache_enabled and not refresh:
            cached = self.store.read_llm_cache(cache_key)
            if cached is not None:
                parsed = None
                if schema is not None:
                    try:
                        parsed = schema.model_validate_json(_strip_code_fence(cached))
                    except Exception:
                        # A cached reply that no longer validates is not evidence.
                        parsed = None
                if schema is None or parsed is not None:
                    record = self._record(
                        status="cache_hit",
                        response_hash=_sha256(cached),
                        latency_ms=0,
                        **common,
                    )
                    return LLMReply(cached, record, True, parsed)

        used = self.store.count_llm_attempts()
        if used >= settings.llm_max_calls:
            reason = (
                f"LLM budget exhausted ({used}/{settings.llm_max_calls} real calls); "
                "no further LLM call was made"
            )
            record = self._record(status="budget_exhausted", error=reason, **common)
            raise LLMBudgetExhausted(reason, record)
        role_used = self.store.count_llm_attempts(agent_role)
        role_budget = self.role_budget(agent_role)
        if role_used >= role_budget:
            reason = (
                f"LLM role budget exhausted for {agent_role} ({role_used}/{role_budget} calls); "
                "no further LLM call was made for this role"
            )
            record = self._record(status="budget_exhausted", error=reason, **common)
            raise LLMBudgetExhausted(reason, record)

        started = time.monotonic()
        try:
            content, usage = await self._post(agent_role, system, user)
        except Exception as exc:
            # The message is persisted as a stage error, so it is redacted too.
            reason = self._redact(f"{type(exc).__name__}: {exc}")
            record = self._record(
                status="failed",
                latency_ms=int((time.monotonic() - started) * 1000),
                error=reason,
                **common,
            )
            logger.warning("LLM call failed role=%s status=%s", agent_role, record.status)
            raise LLMCallFailed(reason, record) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        if not isinstance(content, str) or not content.strip():
            reason = "the provider returned an empty completion"
            record = self._record(
                status="output_rejected",
                response_hash=_sha256(str(content)),
                latency_ms=latency_ms,
                usage=usage,
                error=reason,
                **common,
            )
            raise LLMOutputRejected(reason, record)

        parsed = None
        if schema is not None:
            try:
                parsed = schema.model_validate_json(_strip_code_fence(content))
            except Exception as exc:
                reason = self._redact(
                    f"the reply did not match {schema.__name__}: {type(exc).__name__}: {exc}"
                )
                record = self._record(
                    status="output_rejected",
                    response_hash=_sha256(content),
                    latency_ms=latency_ms,
                    usage=usage,
                    error=reason[:2000],
                    **common,
                )
                raise LLMOutputRejected(reason, record) from exc

        record = self._record(
            status="success",
            response_hash=_sha256(content),
            latency_ms=latency_ms,
            usage=usage,
            **common,
        )
        if settings.llm_cache_enabled:
            self.store.write_llm_cache(
                cache_key, agent_role, settings.llm_model, prompt_version, content
            )
        return LLMReply(content, record, False, parsed)