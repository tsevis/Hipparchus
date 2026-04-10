"""Map provider contracts and null implementation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Protocol


GeoJSONMapping = dict[str, Any]


@dataclass(slots=True, frozen=True)
class BBoxQuery:
    """Bounding box request in WGS84."""

    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    layers: tuple[str, ...] = (
        "roads",
        "buildings",
        "water",
        "parks",
        "railways",
    )


@dataclass(slots=True)
class FeatureCollection:
    """Normalized feature payload across providers."""

    features_by_layer: dict[str, list[GeoJSONMapping]] = field(default_factory=dict)
    geojson_by_layer: dict[str, GeoJSONMapping] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    # Optional bbox (min_lon, min_lat, max_lon, max_lat) for the query area
    bbox: tuple[float, float, float, float] | None = None


class AsyncMapProvider(Protocol):
    """Contract for async map data sources."""

    provider_id: str

    def name(self) -> str:
        """Human readable provider name."""

    async def fetch_bbox_async(self, query: BBoxQuery) -> FeatureCollection:
        """Fetch normalized map features for a bounding box."""

    async def fetch_bbox_stale_while_revalidate(self, query: BBoxQuery) -> FeatureCollection:
        """Fetch cached data immediately and refresh in background when possible."""


class MapProvider(Protocol):
    """Contract for synchronous map data sources."""

    provider_id: str

    def name(self) -> str:
        """Human readable provider name."""

    def fetch_bbox(self, query: BBoxQuery) -> FeatureCollection:
        """Fetch normalized map features for a bounding box."""


@dataclass(slots=True)
class NullMapProvider:
    """Local stub provider that returns empty geometry."""

    provider_id: str = "null"

    def name(self) -> str:
        return "Null Provider"

    async def fetch_bbox_async(self, query: BBoxQuery) -> FeatureCollection:
        _ = query
        return FeatureCollection(
            features_by_layer={},
            geojson_by_layer={},
            metadata={"source": self.provider_id, "empty": True},
        )

    def fetch_bbox(self, query: BBoxQuery) -> FeatureCollection:
        return asyncio.run(self.fetch_bbox_async(query))
