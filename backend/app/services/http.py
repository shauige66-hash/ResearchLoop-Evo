"""Shared HTTP layer: per-source rate limiting, bounded retries, disk cache.

Every upstream failure is surfaced as a `HttpFailure` carrying the real status
code and reason, because the product must show network errors instead of
papering over them with generated content.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import get_settings

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
BACKOFF_SECONDS = (1.0, 3.0)

logger = logging.getLogger(__name__)

# NO_PROXY entries httpx could not turn into a URL pattern, kept for diagnostics.
REJECTED_PROXY_ENTRIES: list[str] = []


def _no_proxy_pattern(entry: str) -> str | None:
    """Translate one NO_PROXY entry into an httpx mount pattern, or None."""
    host = entry.strip()
    if not host:
        return None
    if "://" in host:
        return host
    # An already-bracketed IPv6 literal such as "[::1]" is not recognised as IPv6
    # by httpx, which then emits the unparseable pattern "all://*[::1]".
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if "/" in host:  # CIDR block: httpx patterns match hosts, not ranges
        host = host.split("/", 1)[0]
    try:
        ipaddress.IPv6Address(host)
        return f"all://[{host}]"
    except ValueError:
        pass
    try:
        ipaddress.IPv4Address(host)
        return f"all://{host}"
    except ValueError:
        pass
    if host.lower() == "localhost":
        return f"all://{host}"
    return f"all://*{host}"


def build_proxy_mounts() -> dict[str, httpx.AsyncBaseTransport | None]:
    """Build proxy mounts from the ambient environment, validating every pattern.

    httpx parses each NO_PROXY entry as a URL while constructing the client, so a
    single malformed entry raises InvalidURL before any request is sent and takes
    down all three literature sources at once. Validating here keeps legitimate
    proxy settings working and records what had to be dropped.
    """
    mounts: dict[str, httpx.AsyncBaseTransport | None] = {}
    rejected: list[str] = []

    def usable(pattern: str) -> bool:
        try:
            httpx.URL(pattern)
        except (httpx.InvalidURL, ValueError):
            return False
        return True

    for scheme in ("http", "https", "all"):
        raw = os.environ.get(f"{scheme.upper()}_PROXY") or os.environ.get(f"{scheme}_proxy")
        if not raw:
            continue
        url = raw if "://" in raw else f"http://{raw}"
        if not usable(url):
            rejected.append(f"{scheme.upper()}_PROXY={raw}")
            continue
        mounts[f"{scheme}://"] = httpx.AsyncHTTPTransport(proxy=url)

    no_proxy = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    for entry in no_proxy.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if entry == "*":
            return {}
        pattern = _no_proxy_pattern(entry)
        if pattern is None or not usable(pattern):
            rejected.append(f"NO_PROXY={entry}")
            continue
        mounts[pattern] = None

    REJECTED_PROXY_ENTRIES[:] = rejected
    if rejected:
        logger.warning("Ignoring unparseable proxy environment entries: %s", ", ".join(rejected))
    return mounts


class HttpFailure(Exception):
    def __init__(
        self,
        source: str,
        detail: str,
        status: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.source = source
        self.detail = detail
        self.status = status
        self.url = url

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"HttpFailure(source={self.source!r}, status={self.status!r}, detail={self.detail!r})"


@dataclass
class HttpOutcome:
    payload: Any
    from_cache: bool
    status: int
    elapsed_ms: int
    requests_made: int


class TokenBucket:
    """Simple async rate limiter: at most `rate` requests per second."""

    def __init__(self, rate_per_second: float, min_interval: float = 0.0) -> None:
        self.rate = max(rate_per_second, 0.05)
        # Capacity must hold at least one whole token, otherwise a rate below 1/s
        # (arXiv uses 0.3) can never accumulate enough to issue a single request.
        self.capacity = max(1.0, self.rate)
        self.min_interval = max(min_interval, 0.0)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(
                    self.capacity, self._tokens + (now - self._updated) * self.rate
                )
                self._updated = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    await asyncio.sleep(self.min_interval)
                    return
                await asyncio.sleep((1.0 - self._tokens) / self.rate + 0.01)


class SourceClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None
        self._buckets: dict[str, TokenBucket] = {}
        self._cache_hits = 0
        self._requests_made = 0

    # ------------------------------------------------------------------ plumbing
    def bucket(self, source: str) -> TokenBucket:
        if source not in self._buckets:
            rates = {
                "openalex": (self.settings.rate_openalex, 0.0),
                "crossref": (self.settings.rate_crossref, 0.0),
                "arxiv": (self.settings.rate_arxiv, self.settings.arxiv_min_interval),
            }
            rate, gap = rates.get(source, (2.0, 0.0))
            self._buckets[source] = TokenBucket(rate, gap)
        return self._buckets[source]

    async def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            # Supplying an explicit transport stops httpx from re-parsing the raw
            # proxy environment itself; build_proxy_mounts() has already validated it.
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.settings.request_timeout),
                follow_redirects=True,
                headers={"User-Agent": "ResearchLoopEvo/0.1 (research prototype)"},
                transport=httpx.AsyncHTTPTransport(),
                mounts=build_proxy_mounts(),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    @property
    def stats(self) -> dict[str, int]:
        return {"cache_hits": self._cache_hits, "requests_made": self._requests_made}

    def reset_stats(self) -> None:
        self._cache_hits = 0
        self._requests_made = 0

    # --------------------------------------------------------------------- cache
    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]
        return self.settings.cache_dir / f"{digest}.json"

    def read_cache(self, url: str, ttl: int | None = None) -> Any | None:
        ttl = self.settings.cache_ttl_seconds if ttl is None else ttl
        path = self._cache_path(url)
        if not path.exists() or ttl <= 0:
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if time.time() - float(entry.get("fetched_at", 0)) > ttl:
            return None
        return entry.get("payload")

    def write_cache(self, url: str, payload: Any) -> None:
        try:
            self._cache_path(url).write_text(
                json.dumps({"url": url, "fetched_at": time.time(), "payload": payload}),
                encoding="utf-8",
            )
        except OSError:
            # a broken cache must never look like a successful retrieval
            return

    # --------------------------------------------------------------------- fetch
    async def fetch_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        source: str,
        timeout: float | None = None,
        accept: str = "application/json",
        refresh: bool = False,
        cache_ttl: int | None = None,
    ) -> HttpOutcome:
        timeout = timeout or self.settings.request_timeout
        # httpx 0.28 removed send(timeout=...); per-request timeouts travel in extensions.
        request = httpx.Request(
            "GET",
            url,
            params=params,
            headers={"Accept": accept},
            extensions={"timeout": httpx.Timeout(timeout).as_dict()},
        )
        cache_key = str(request.url)
        ttl = self.settings.cache_ttl_seconds if cache_ttl is None else cache_ttl

        if not refresh and ttl > 0:
            cached = self.read_cache(cache_key, ttl)
            if cached is not None:
                self._cache_hits += 1
                return HttpOutcome(cached, True, 200, 0, 0)

        client = await self.client()
        attempts = self.settings.max_retries
        last_status: int | None = None
        last_detail = "no request attempted"
        retry_after: str | None = None
        started = time.monotonic()
        requests_made = 0

        for attempt in range(attempts + 1):
            await self.bucket(source).acquire()
            try:
                response = await client.send(request)
            except httpx.TimeoutException:
                last_status, last_detail = None, f"timeout after {timeout:.0f}s"
            except httpx.HTTPError as exc:
                last_status, last_detail = None, f"{type(exc).__name__}: {exc}"
            else:
                requests_made += 1
                self._requests_made += 1
                last_status = response.status_code
                if response.status_code == 200:
                    try:
                        if accept.startswith("application/json") or response.headers.get(
                            "content-type", ""
                        ).startswith("application/json"):
                            payload = response.json()
                        else:
                            payload = response.text
                    except (json.JSONDecodeError, ValueError):
                        payload = response.text
                    if requests_made:
                        self.write_cache(cache_key, payload)
                    return HttpOutcome(
                        payload,
                        False,
                        response.status_code,
                        int((time.monotonic() - started) * 1000),
                        requests_made,
                    )
                if response.status_code not in RETRYABLE_STATUS:
                    detail = _error_detail(response)
                    raise HttpFailure(source, detail, response.status_code, cache_key)
                last_detail = _error_detail(response)
                retry_after = response.headers.get("Retry-After")
            if attempt < attempts:
                delay = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
                if retry_after:
                    try:
                        delay = min(float(retry_after), 10.0)
                    except ValueError:
                        pass
                await asyncio.sleep(delay)

        raise HttpFailure(
            source,
            f"{last_detail} (after {requests_made} attempt(s))",
            last_status,
            cache_key,
        )


def _error_detail(response: httpx.Response) -> str:
    body = (response.text or "").strip().replace("\n", " ")[:220]
    if response.status_code == 429:
        return f"rate limited by upstream API: {body or 'HTTP 429'}"
    if response.status_code == 403:
        return f"rejected by upstream API: {body or 'HTTP 403'}"
    reason = response.reason_phrase or ""
    return f"HTTP {response.status_code} {reason}: {body}".strip()


_client: SourceClient | None = None


def get_client() -> SourceClient:
    global _client
    if _client is None:
        _client = SourceClient()
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
