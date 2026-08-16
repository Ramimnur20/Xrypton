import asyncio
import fnmatch
from typing import List, Optional


class _RedisLock:
    def __init__(self, redis: "FakeRedis", key: str):
        self.redis = redis
        self.key = key
        self._lock = None

    async def __aenter__(self):
        if self.key not in self.redis._locks:
            self.redis._locks[self.key] = asyncio.Lock()
        self._lock = self.redis._locks[self.key]
        await self._lock.acquire()
        return self

    async def __aexit__(self, *args):
        try:
            self._lock.release()
        except Exception:
            pass


class FakeRedis:
    """In-memory stand-in for the ``redis`` client the economy cog expects.

    Xrypton has no Redis instance, so this keeps an in-process store with the
    small subset of the API the cog uses (locks, get/set/setex/delete/keys).
    """

    def __init__(self):
        self._store: dict = {}
        self._locks: dict = {}

    def lock(self, key: str, timeout: int = 5) -> _RedisLock:
        return _RedisLock(self, key)

    async def get(self, key: str) -> Optional[str]:
        return self._store.get(key)

    async def set(self, key: str, value, ex: Optional[int] = None) -> None:
        self._store[key] = value

    async def setex(self, key: str, ttl: int, value) -> None:
        self._store[key] = value

    async def delete(self, *keys) -> None:
        for key in keys:
            self._store.pop(key, None)

    async def keys(self, pattern: str) -> List[str]:
        return [k for k in self._store if fnmatch.fnmatch(k, pattern)]
