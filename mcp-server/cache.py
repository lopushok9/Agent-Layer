"""In-memory TTL cache with stale data support."""

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    expires_at: float
    created_at: float = field(default_factory=time.monotonic)


class Cache:
    """Simple dict-based TTL cache.

    - ``get(key)`` returns data only if fresh.
    - ``get_stale(key, max_age)`` returns data even if TTL expired,
      as long as it was created within *max_age* seconds.  Useful as
      a fallback when the upstream provider is down.
    - Automatic eviction when *max_entries* is exceeded (oldest first).
    """

    def __init__(self, max_entries: int = 10_000):
        self._store: dict[str, CacheEntry] = {}
        self._max_entries = max_entries

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            return None
        return entry.value

    def get_stale(self, key: str, max_age: float = 300) -> Any | None:
        """Return cached value even if expired, within *max_age* seconds of creation."""
        entry = self._store.get(key)
        if entry is None:
            return None
        age = time.monotonic() - entry.created_at
        if age > max_age:
            return None
        return entry.value

    def set(self, key: str, value: Any, ttl: float) -> None:
        if len(self._store) >= self._max_entries:
            self._evict()
        now = time.monotonic()
        self._store[key] = CacheEntry(value=value, expires_at=now + ttl, created_at=now)

    def _evict(self) -> None:
        """Remove oldest 20% of entries."""
        if not self._store:
            return
        count = max(1, len(self._store) // 5)
        sorted_keys = sorted(self._store, key=lambda k: self._store[k].created_at)
        for k in sorted_keys[:count]:
            del self._store[k]

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)
