"""Small thread-safe TTL cache used by live-data provider services.

Each external data layer gets its own cache instance with a config-driven TTL so
repeated requests for the same coordinate do not hammer the upstream provider.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional


class TTLCache:
    def __init__(self, default_ttl_seconds: float = 600.0, max_entries: int = 4096) -> None:
        self._default_ttl = max(0.0, float(default_ttl_seconds))
        self._max = max(1, int(max_entries))
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            value, expires_at = item
            if time.monotonic() > expires_at:
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: Optional[float] = None) -> None:
        ttl = self._default_ttl if ttl_seconds is None else max(0.0, float(ttl_seconds))
        with self._lock:
            if len(self._data) >= self._max:
                self._evict_locked()
            self._data[key] = (value, time.monotonic() + ttl)

    def _evict_locked(self) -> None:
        now = time.monotonic()
        stale = [k for k, v in self._data.items() if v[1] <= now]
        for key in stale[: max(1, self._max // 8)]:
            self._data.pop(key, None)
        # Still full? drop oldest expiry.
        if len(self._data) >= self._max and self._data:
            oldest = min(self._data, key=lambda k: self._data[k][1])
            self._data.pop(oldest, None)

    def get_or_set(
        self,
        key: str,
        factory: Callable[[], Any],
        ttl_seconds: Optional[float] = None,
    ) -> Any:
        value = self.get(key)
        if value is None:
            value = factory()
            if value is not None:
                self.set(key, value, ttl_seconds)
        return value

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)