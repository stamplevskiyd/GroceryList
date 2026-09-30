"""Sliding-window лимиты входа в памяти единственного процесса (ADR-0010)."""

import math
import time
from collections import deque
from collections.abc import Callable
from functools import lru_cache

from grocery.config import get_settings
from grocery.services.auth.errors import TooManyAttemptsError


class LoginLimiter:
    def __init__(
        self,
        *,
        username_limit: int,
        ip_limit: int,
        window_seconds: int,
        max_keys: int = 10000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if min(username_limit, ip_limit, window_seconds) <= 0 or max_keys < 2:
            raise ValueError("Лимиты и окно должны быть положительными, max_keys — не менее двух")
        self._username_limit = username_limit
        self._ip_limit = ip_limit
        self._window_seconds = window_seconds
        self._max_keys = max_keys
        self._clock = clock
        self._buckets: dict[tuple[str, str], deque[float]] = {}

    def reserve(self, *, username: str, ip: str) -> None:
        """Проверить оба bucket до изменения; без await, атомарно для event loop."""
        now = self._clock()
        cutoff = now - self._window_seconds
        for key, bucket in list(self._buckets.items()):
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                del self._buckets[key]

        keys = (("username", username), ("ip", ip))
        limits = (self._username_limit, self._ip_limit)
        releases: list[float] = []
        for key, limit in zip(keys, limits, strict=True):
            candidate = self._buckets.get(key)
            if candidate is not None and len(candidate) >= limit:
                releases.append(candidate[len(candidate) - limit] + self._window_seconds)

        missing_keys = sum(key not in self._buckets for key in keys)
        shortage = len(self._buckets) + missing_keys - self._max_keys
        if shortage > 0:
            # Нужный текущему запросу ключ будет создан заново после expiry,
            # поэтому ёмкость освобождают только остальные ключи.
            expiries = sorted(
                bucket[-1] + self._window_seconds
                for key, bucket in self._buckets.items()
                if key not in keys
            )
            releases.append(expiries[shortage - 1])
        if releases:
            raise TooManyAttemptsError(max(1, math.ceil(max(releases) - now)))

        for key in keys:
            self._buckets.setdefault(key, deque()).append(now)


@lru_cache
def get_login_limiter() -> LoginLimiter:
    settings = get_settings().auth
    return LoginLimiter(
        username_limit=settings.login_username_limit,
        ip_limit=settings.login_ip_limit,
        window_seconds=settings.login_window_seconds,
    )
