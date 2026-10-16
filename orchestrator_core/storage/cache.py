"""
orchestrator_core/storage/cache.py

High-performance in-memory TTL cache with thread-safe expiration and invalidation.
Supports server-side caching of expensive database queries and API responses.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")


class TTLCache:
    """Thread-safe in-memory cache with time-to-live expiration."""

    def __init__(self, default_ttl_seconds: float = 30.0, max_entries: int = 1000):
        self._default_ttl = default_ttl_seconds
        self._max_entries = max_entries
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """Retrieve a value if present and not expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expiry, value = entry
            if time.monotonic() > expiry:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        """Store a value with an expiration timestamp."""
        ttl_seconds = ttl if ttl is not None else self._default_ttl
        expiry = time.monotonic() + ttl_seconds
        with self._lock:
            # Simple eviction if exceeding max entries
            if len(self._store) >= self._max_entries:
                now = time.monotonic()
                expired = [k for k, (exp, _) in self._store.items() if exp <= now]
                for k in expired:
                    del self._store[k]
                if len(self._store) >= self._max_entries:
                    # Drop oldest entry
                    first_key = next(iter(self._store))
                    del self._store[first_key]
            self._store[key] = (expiry, value)

    def delete(self, key: str) -> None:
        """Explicitly invalidate a key."""
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self._store.clear()

    def invalidate_prefix(self, prefix: str) -> None:
        """Invalidate all keys starting with prefix."""
        with self._lock:
            to_del = [k for k in self._store if k.startswith(prefix)]
            for k in to_del:
                del self._store[k]


# Global cache instances
api_cache = TTLCache(default_ttl_seconds=15.0)
query_cache = TTLCache(default_ttl_seconds=30.0)
