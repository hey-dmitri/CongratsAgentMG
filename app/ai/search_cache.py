from __future__ import annotations

import hashlib
import json
from pathlib import Path
from threading import Lock
from typing import Optional

CACHE_PATH = Path(__file__).parent.parent.parent / "data" / "search_cache.json"


class SearchCache:
    """
    Persistent JSON cache for external search requests.
    Keys are SHA-256 hashes of the query/URL.
    Claude analysis is never cached — only raw external API responses.
    """

    def __init__(self, path: Path = CACHE_PATH):
        self._path = path
        self._lock = Lock()
        self._data: dict[str, object] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, "r") as f:
                    self._data = json.load(f)
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)

    @staticmethod
    def _key(value: str) -> str:
        return hashlib.sha256(value.encode()).hexdigest()

    def get(self, query: str) -> Optional[object]:
        return self._data.get(self._key(query))

    def set(self, query: str, result: object) -> None:
        with self._lock:
            self._data[self._key(query)] = result
            self._save()

    def clear(self) -> None:
        with self._lock:
            self._data = {}
            self._save()

    def size(self) -> int:
        return len(self._data)


# Singleton
_cache: Optional[SearchCache] = None


def get_cache() -> SearchCache:
    global _cache
    if _cache is None:
        _cache = SearchCache()
    return _cache
