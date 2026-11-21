"""In-memory RateLimitStore with a controllable clock (unit/SQLite tests only).

Production uses RedisRateLimitStore; the PostgreSQL/HTTP suite exercises real Redis.
"""

import math


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


class MemoryRateLimitStore:
    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self._data: dict[str, tuple[int, float]] = {}

    def _live(self, key: str) -> tuple[int, float] | None:
        entry = self._data.get(key)
        if entry and entry[1] <= self._clock.now:
            del self._data[key]
            return None
        return entry

    def get(self, key: str) -> tuple[int, int]:
        entry = self._live(key)
        if not entry:
            return 0, 0
        return entry[0], math.ceil(entry[1] - self._clock.now)

    def hit(self, key: str, window_seconds: int) -> tuple[int, int]:
        entry = self._live(key)
        if entry:
            count, expires = entry[0] + 1, entry[1]
        else:
            count, expires = 1, self._clock.now + window_seconds
        self._data[key] = (count, expires)
        return count, math.ceil(expires - self._clock.now)

    def reset(self, key: str) -> None:
        self._data.pop(key, None)
