"""AOI-aware cache index metadata store."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import time


@dataclass(slots=True)
class CacheIndexEntry:
    key: str
    source_endpoint: str
    aoi_hash: str
    layer_set_hash: str
    schema_version: str
    timestamp_unix: float


class AOICacheIndex:
    """Simple JSON index for AOI cache metadata."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load_all(self) -> dict[str, CacheIndexEntry]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        out: dict[str, CacheIndexEntry] = {}
        for key, value in data.items():
            out[key] = CacheIndexEntry(**value)
        return out

    def upsert(self, entry: CacheIndexEntry) -> None:
        data = self.load_all()
        data[entry.key] = entry
        self.path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {k: asdict(v) for k, v in data.items()}
        self.path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")

    def touch(
        self,
        key: str,
        source_endpoint: str,
        aoi_hash: str,
        layer_set_hash: str,
        schema_version: str = "v1",
    ) -> None:
        self.upsert(
            CacheIndexEntry(
                key=key,
                source_endpoint=source_endpoint,
                aoi_hash=aoi_hash,
                layer_set_hash=layer_set_hash,
                schema_version=schema_version,
                timestamp_unix=time.time(),
            )
        )
