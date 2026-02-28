"""In-memory analysis cache with 24h TTL and max-size eviction."""

import time
from typing import Optional


CACHE_TTL_S = 86_400  # 24 hours
CACHE_MAX_SIZE = 200


class _CacheEntry:
    __slots__ = ("data", "created_at")

    def __init__(self, data: str):
        self.data = data
        self.created_at = time.monotonic()


class AnalysisCache:
    def __init__(self):
        self._entries: dict[str, _CacheEntry] = {}

    def get(self, video_id: str) -> Optional[str]:
        entry = self._entries.get(video_id)
        if entry is None:
            return None
        if time.monotonic() - entry.created_at > CACHE_TTL_S:
            del self._entries[video_id]
            return None
        return entry.data

    def set(self, video_id: str, data: str):
        self._entries[video_id] = _CacheEntry(data)
        self._cleanup()

    def _cleanup(self):
        now = time.monotonic()
        expired = [k for k, v in self._entries.items() if now - v.created_at > CACHE_TTL_S]
        for k in expired:
            del self._entries[k]
        if len(self._entries) > CACHE_MAX_SIZE:
            sorted_keys = sorted(self._entries, key=lambda k: self._entries[k].created_at)
            for k in sorted_keys[: len(self._entries) - CACHE_MAX_SIZE]:
                del self._entries[k]
