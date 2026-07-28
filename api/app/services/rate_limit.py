"""Process-local fixed-window rate limiting (approximate under multi-worker)."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request

from app.config import settings

# Drop keys with no recent hits once the map grows.
_PRUNE_AFTER_KEYS = 2048
_PRUNE_IDLE_SEC = 900


class FixedWindowLimiter:
    def __init__(self) -> None:
        self._lock = Lock()
        self._hits: dict[str, list[float]] = defaultdict(list)

    def _prune_idle(self, now: float) -> None:
        if len(self._hits) < _PRUNE_AFTER_KEYS:
            return
        stale = [
            key
            for key, hits in self._hits.items()
            if not hits or now - max(hits) > _PRUNE_IDLE_SEC
        ]
        for key in stale:
            del self._hits[key]

    def check(self, key: str, *, limit: int, window_sec: int) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            self._prune_idle(now)
            hits = [t for t in self._hits.get(key, []) if now - t < window_sec]
            if len(hits) >= limit:
                oldest = hits[0] if hits else now
                retry = int(window_sec - (now - oldest)) + 1
                if hits:
                    self._hits[key] = hits
                else:
                    self._hits.pop(key, None)
                return False, max(1, retry)
            hits.append(now)
            self._hits[key] = hits
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_limiter = FixedWindowLimiter()


def client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    if settings.trust_x_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def enforce_rate_limit(
    key: str,
    *,
    limit: int,
    window_sec: int = 60,
) -> None:
    if not settings.rate_limit_enabled:
        return
    ok, retry_after = _limiter.check(key, limit=limit, window_sec=window_sec)
    if not ok:
        raise HTTPException(
            status_code=429,
            detail="Too many attempts — try again later",
            headers={"Retry-After": str(retry_after)},
        )


def reset_limiter_for_tests() -> None:
    _limiter.reset()
