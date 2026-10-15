"""In-process sliding-window rate limiter.

The application runs as a single process (SQLite + background worker), so an
in-memory limiter is exact. Behind several processes, swap it for Redis.
"""

from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_prune = time.monotonic()

    def hit(self, key: str, limit: int, window_seconds: float) -> bool:
        """Record one event; return False if it exceeds ``limit`` per window."""
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.setdefault(key, deque())
            cutoff = now - window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                return False
            bucket.append(now)
            if now - self._last_prune > 300:
                self._prune(now)
            return True

    def retry_after(self, key: str, window_seconds: float) -> int:
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return 0
            return max(1, int(bucket[0] + window_seconds - time.monotonic()) + 1)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)

    def _prune(self, now: float) -> None:
        # Drop keys idle for over an hour so memory cannot grow without bound.
        stale = [k for k, b in self._hits.items() if not b or b[-1] < now - 3600]
        for k in stale:
            del self._hits[k]
        self._last_prune = now
