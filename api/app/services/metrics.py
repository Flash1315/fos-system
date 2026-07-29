"""Lightweight in-process HTTP metrics (Prometheus text exposition)."""

from __future__ import annotations

import threading
import time
from collections import defaultdict

_lock = threading.Lock()
_started = time.time()
_requests_total: dict[str, int] = defaultdict(int)
_duration_ms_sum: float = 0.0
_duration_ms_count: int = 0
_duration_buckets = (50, 100, 250, 500, 1000, 2500, 5000, 10000)
_duration_bucket_counts: dict[int, int] = {b: 0 for b in _duration_buckets}
_duration_bucket_inf = 0


def _normalize_path(path: str) -> str:
    parts = [p for p in (path or "/").split("/") if p != ""]
    out = []
    for p in parts:
        if p.isdigit():
            out.append(":id")
        elif len(p) == 32 and all(c in "0123456789abcdef" for c in p.lower()):
            out.append(":file")
        else:
            out.append(p)
    return "/" + "/".join(out) if out else "/"


def normalize_path(path: str) -> str:
    """Public alias for request-log cardinality collapse."""
    return _normalize_path(path)


def observe_request(*, method: str, path: str, status: int, duration_ms: float) -> None:
    # Collapse /records/123 → /records/:id for cardinality
    norm = _normalize_path(path)
    key = f"{method.upper()}|{norm}|{int(status)}"
    with _lock:
        global _duration_ms_sum, _duration_ms_count, _duration_bucket_inf
        _requests_total[key] += 1
        _duration_ms_sum += max(0.0, float(duration_ms))
        _duration_ms_count += 1
        placed = False
        for b in _duration_buckets:
            if duration_ms <= b:
                _duration_bucket_counts[b] += 1
                placed = True
                break
        if not placed:
            _duration_bucket_inf += 1


def render_prometheus(
    *,
    app: str,
    version: str,
    db_ok: bool,
    limiter: str,
    media_ok: bool = True,
    limiter_redis_up: bool | None = None,
) -> str:
    lines = [
        f"# HELP fos_up 1 if process is up",
        f"# TYPE fos_up gauge",
        f"fos_up 1",
        f"# HELP fos_app_info Build identity",
        f"# TYPE fos_app_info gauge",
        f'fos_app_info{{app="{_esc(app)}",version="{_esc(version)}",limiter="{_esc(limiter)}"}} 1',
        f"# HELP fos_process_uptime_seconds Process uptime",
        f"# TYPE fos_process_uptime_seconds gauge",
        f"fos_process_uptime_seconds {time.time() - _started:.3f}",
        f"# HELP fos_db_up 1 if last ready check could open DB (best-effort at scrape)",
        f"# TYPE fos_db_up gauge",
        f"fos_db_up {1 if db_ok else 0}",
        f"# HELP fos_media_up 1 if media backend probe succeeded (best-effort at scrape)",
        f"# TYPE fos_media_up gauge",
        f"fos_media_up {1 if media_ok else 0}",
    ]
    if limiter_redis_up is not None:
        lines += [
            f"# HELP fos_limiter_redis_up 1 if Redis limiter is configured and reachable",
            f"# TYPE fos_limiter_redis_up gauge",
            f"fos_limiter_redis_up {1 if limiter_redis_up else 0}",
        ]
    lines += [
        f"# HELP fos_http_requests_total HTTP requests",
        f"# TYPE fos_http_requests_total counter",
    ]
    with _lock:
        for key, n in sorted(_requests_total.items()):
            method, path, status = key.split("|", 2)
            lines.append(
                f'fos_http_requests_total{{method="{_esc(method)}",path="{_esc(path)}",status="{status}"}} {n}'
            )
        lines += [
            f"# HELP fos_http_request_duration_ms Request duration histogram (ms)",
            f"# TYPE fos_http_request_duration_ms histogram",
        ]
        cumulative = 0
        for b in _duration_buckets:
            cumulative += _duration_bucket_counts[b]
            lines.append(f'fos_http_request_duration_ms_bucket{{le="{b}"}} {cumulative}')
        cumulative += _duration_bucket_inf
        lines.append(f'fos_http_request_duration_ms_bucket{{le="+Inf"}} {cumulative}')
        lines.append(f"fos_http_request_duration_ms_sum {_duration_ms_sum:.3f}")
        lines.append(f"fos_http_request_duration_ms_count {_duration_ms_count}")
    return "\n".join(lines) + "\n"


def _esc(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\n", "\\n")
        .replace('"', '\\"')
    )
