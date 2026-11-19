"""Runtime configuration for the ResearchLoop Evo backend.

All values are environment-driven so that nothing sensitive is hard-coded.
API keys never reach the frontend: only this backend talks to academic APIs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

try:  # optional: .env loading keeps local setup simple
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv missing is tolerated
    pass

BASE_DIR = Path(__file__).resolve().parent.parent

# Per-role LLM ceilings (§16 of the gap-pipeline spec). The global
# RLE_LLM_MAX_CALLS budget still applies on top of these.
DEFAULT_ROLE_BUDGETS: dict[str, int] = {
    "research_planner": 1,
    "literature_analyst": 30,
    "gap_analyst": 2,
    "gap_critic": 5,
    "counter_query": 5,
    "candidate_proposer": 20,
}

# Deterministic gap gate. These thresholds only mean "reached the system gate
# within the current search scope"; they never prove novelty mathematically.
DEFAULT_GAP_GATE: dict[str, Any] = {
    "min_supporting_papers": 3,
    "min_evidence_grounding": 3,
    "min_cross_paper_support": 3,
    "min_specificity": 3,
    "min_testability": 3,
    "max_novelty_risk": "MEDIUM",
    "max_contradiction_risk": "MEDIUM",
    "require_counter_search_success": True,
    "max_prior_art_collisions": 0,
    "min_critic_score_scale": 0,
    "max_critic_score_scale": 5,
}

GATE_NOTICE = (
    "Passing this gate means the candidate reached the configured evidence thresholds "
    "within the current search scope. It is not a mathematical proof of novelty."
)


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_flag(name: str, default: bool = False) -> bool:
    return _env(name, "1" if default else "0").lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # identity for the polite pools of OpenAlex / Crossref
    mailto: str
    data_dir: Path
    cache_dir: Path
    db_path: Path

    request_timeout: float
    arxiv_timeout: float
    cache_ttl_seconds: int

    # requests per second, per source (token bucket)
    rate_openalex: float
    rate_crossref: float
    rate_arxiv: float
    # arXiv additionally needs a fixed gap between calls
    arxiv_min_interval: float

    max_concurrency: int
    max_retries: int
    max_keywords: int
    default_top_k: int
    max_top_k: int
    per_query_limit: int

    title_jaccard_threshold: float
    title_ratio_threshold: float

    llm_enabled: bool
    llm_max_calls: int
    # Server-side only. Never serialized into any API response.
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_timeout: float = 60.0
    llm_cache_enabled: bool = True
    # Per-role ceilings on top of the global RLE_LLM_MAX_CALLS budget.
    llm_role_budgets: dict[str, int] = field(default_factory=dict)
    # Deterministic gap gate thresholds. Kept here so no magic number lives in code.
    gap_gate: dict[str, Any] = field(default_factory=dict)
    cors_origins: list[str] = field(default_factory=list)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_enabled and self.llm_api_key and self.llm_base_url and self.llm_model)

    @property
    def llm_provider_label(self) -> str:
        """Identify the provider without ever exposing the key or the full URL."""
        if not self.llm_base_url:
            return "not_configured"
        host = self.llm_base_url.split("://")[-1].split("/")[0].lower()
        for name in ("deepseek", "dashscope", "qwen", "openai", "moonshot", "bigmodel", "siliconflow"):
            if name in host:
                return name
        return host

    @property
    def enabled_sources(self) -> list[str]:
        return ["openalex", "crossref", "arxiv"]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    data_dir = Path(_env("RLE_DATA_DIR", str(BASE_DIR / "var")))
    cache_dir = Path(_env("RLE_CACHE_DIR", str(data_dir / "http-cache")))
    settings = Settings(
        mailto=_env("RLE_MAILTO", ""),
        data_dir=data_dir,
        cache_dir=cache_dir,
        db_path=Path(_env("RLE_DB_PATH", str(data_dir / "researchloop.db"))),
        request_timeout=_env_float("RLE_REQUEST_TIMEOUT", 20.0),
        arxiv_timeout=_env_float("RLE_ARXIV_TIMEOUT", 15.0),
        cache_ttl_seconds=_env_int("RLE_CACHE_TTL", 86400),
        rate_openalex=_env_float("RLE_RATE_OPENALEX", 8.0),
        rate_crossref=_env_float("RLE_RATE_CROSSREF", 4.0),
        rate_arxiv=_env_float("RLE_RATE_ARXIV", 0.3),
        arxiv_min_interval=_env_float("RLE_ARXIV_MIN_INTERVAL", 3.0),
        max_concurrency=_env_int("RLE_MAX_CONCURRENCY", 6),
        max_retries=_env_int("RLE_MAX_RETRIES", 2),
        max_keywords=_env_int("RLE_MAX_KEYWORDS", 6),
        default_top_k=_env_int("RLE_DEFAULT_TOP_K", 40),
        max_top_k=_env_int("RLE_MAX_TOP_K", 200),
        per_query_limit=_env_int("RLE_PER_QUERY_LIMIT", 50),
        title_jaccard_threshold=_env_float("RLE_TITLE_JACCARD", 0.85),
        title_ratio_threshold=_env_float("RLE_TITLE_RATIO", 0.92),
        llm_enabled=_env_flag("RLE_LLM_ENABLED", False),
        llm_max_calls=_env_int("RLE_LLM_MAX_CALLS", 60),
        llm_api_key=_env("RLE_LLM_API_KEY", ""),
        llm_base_url=_env("RLE_LLM_BASE_URL", ""),
        llm_model=_env("RLE_LLM_MODEL", ""),
        llm_timeout=_env_float("RLE_LLM_TIMEOUT", 60.0),
        llm_cache_enabled=_env_flag("RLE_LLM_CACHE", True),
        llm_role_budgets={
            role: _env_int(f"RLE_LLM_{role.upper()}_MAX", limit)
            for role, limit in DEFAULT_ROLE_BUDGETS.items()
        },
        gap_gate={
            key: (
                _env_flag(f"RLE_GATE_{key.upper()}", value)
                if isinstance(value, bool)
                else _env_int(f"RLE_GATE_{key.upper()}", value)
                if isinstance(value, int)
                else _env(f"RLE_GATE_{key.upper()}", str(value))
            )
            for key, value in DEFAULT_GAP_GATE.items()
        },
        cors_origins=[
            o.strip()
            for o in _env(
                "RLE_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if o.strip()
        ],
    )
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
