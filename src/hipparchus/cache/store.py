"""Cache interface and simple implementations."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
from pathlib import Path
from typing import Protocol
import zlib


class CacheStore(Protocol):
    """Minimal cache contract for map/data artifacts."""

    def get(self, key: str) -> bytes | None:
        """Get cached payload by key."""

    def set(self, key: str, value: bytes) -> None:
        """Store payload by key."""


@dataclass(slots=True)
class InMemoryCacheStore:
    """Simple process-local cache placeholder."""

    _data: dict[str, bytes] = field(default_factory=dict)

    def get(self, key: str) -> bytes | None:
        return self._data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self._data[key] = value


@dataclass(slots=True)
class DiskCacheStore:
    """Filesystem-backed cache store keyed by SHA-256 hash."""

    root: Path
    memory_items: int = 128
    compress_on_disk: bool = True
    _hot_cache: OrderedDict[str, bytes] = field(default_factory=OrderedDict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> bytes | None:
        hot = self._hot_cache.get(key)
        if hot is not None:
            self._touch_hot_cache(key, hot)
            return hot

        path = self._path_for_key(key)
        if not path.exists():
            return None
        raw = path.read_bytes()
        value = self._decode(raw)
        self._touch_hot_cache(key, value)
        return value

    def set(self, key: str, value: bytes) -> None:
        self._touch_hot_cache(key, value)
        path = self._path_for_key(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self._encode(value)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_bytes(payload)
        tmp_path.replace(path)

    def _path_for_key(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / digest[:2] / f"{digest}.bin"

    def _touch_hot_cache(self, key: str, value: bytes) -> None:
        self._hot_cache[key] = value
        self._hot_cache.move_to_end(key)
        while len(self._hot_cache) > self.memory_items:
            self._hot_cache.popitem(last=False)

    def _encode(self, value: bytes) -> bytes:
        if not self.compress_on_disk:
            return value
        # Prefix compressed payloads so we can safely read old uncompressed files.
        return b"ZC01" + zlib.compress(value, level=1)

    def _decode(self, raw: bytes) -> bytes:
        if len(raw) >= 4 and raw[:4] == b"ZC01":
            return zlib.decompress(raw[4:])
        return raw
