"""Online data source manager backed by Overpass."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
from typing import Any

from hipparchus.data_sources.overpass_provider import OverpassMapProvider, OverpassSettings
from hipparchus.data_sources.provider import BBoxQuery, FeatureCollection


_LOGGER = logging.getLogger("hipparchus.data_sources")


class DataSource(Enum):
    """Available data sources."""

    OVERPASS = "overpass"


@dataclass
class DataSourceConfig:
    """Configuration for the online data source stack."""

    local_cache_dir: Path = Path.home() / ".hipparchus" / "cache"
    overpass_endpoint: str = "https://overpass-api.de/api/interpreter"
    overpass_timeout: float = 60.0
    overpass_rps: float = 1.0


@dataclass
class DataSourceManager:
    """Coordinates online map fetching through Overpass."""

    config: DataSourceConfig = field(default_factory=DataSourceConfig)

    _overpass: OverpassMapProvider | None = field(init=False, repr=False, default=None)

    def __post_init__(self) -> None:
        self._initialize_providers()

    def _initialize_providers(self) -> None:
        """Initialize the Overpass provider."""
        cache_dir = self._get_cache_dir()
        self._overpass = OverpassMapProvider(
            cache_dir=cache_dir / "overpass",
            settings=OverpassSettings(
                endpoint=self.config.overpass_endpoint,
                timeout_seconds=self.config.overpass_timeout,
                requests_per_second=self.config.overpass_rps,
            ),
        )
        _LOGGER.info("Overpass provider initialized with cache at %s", cache_dir / "overpass")

    def _get_cache_dir(self) -> Path:
        """Return the cache directory used for online requests."""
        return self.config.local_cache_dir

    def fetch(
        self,
        query: BBoxQuery,
        sources: tuple[DataSource, ...] | None = None,
    ) -> FeatureCollection:
        """Fetch data from Overpass."""
        if sources is None:
            sources = (DataSource.OVERPASS,)

        if DataSource.OVERPASS in sources and self._overpass is not None:
            try:
                import asyncio

                result = asyncio.run(self._overpass.fetch_bbox_async(query))
                result.bbox = (query.min_lon, query.min_lat, query.max_lon, query.max_lat)
                _LOGGER.info("Fetched from Overpass: cache=%s", result.metadata.get("cache", "unknown"))
                return result
            except Exception as e:
                _LOGGER.error("Overpass fetch failed: %s", e)
                raise

        # No data available
        return FeatureCollection(
            features_by_layer={},
            geojson_by_layer={},
            metadata={"source": "none", "error": "No data sources available"},
            bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat),
        )

    async def fetch_async(self, query: BBoxQuery, sources: tuple[DataSource, ...] | None = None) -> FeatureCollection:
        """Async version of fetch."""
        if sources is None:
            sources = (DataSource.OVERPASS,)

        if DataSource.OVERPASS in sources and self._overpass is not None:
            result = await self._overpass.fetch_bbox_async(query)
            return result

        return FeatureCollection(
            features_by_layer={},
            geojson_by_layer={},
            metadata={"source": "none", "error": "No data sources available"},
        )

    def _has_data(self, result: FeatureCollection) -> bool:
        """Check if a FeatureCollection has any data."""
        return any(len(features) > 0 for features in result.features_by_layer.values())

    def get_status(self) -> dict[str, Any]:
        """Get current online data source status."""
        return {
            "overpass": {
                "available": self._overpass is not None,
                "cache_dir": str(self._get_cache_dir()),
            },
        }

    def get_overpass_settings(self) -> dict[str, Any]:
        """Get current Overpass provider settings."""
        if self._overpass is None:
            return {
                "endpoint": self.config.overpass_endpoint,
                "timeout_seconds": self.config.overpass_timeout,
                "requests_per_second": self.config.overpass_rps,
            }
        return {
            "endpoint": self._overpass.settings.endpoint,
            "timeout_seconds": self._overpass.settings.timeout_seconds,
            "requests_per_second": self._overpass.settings.requests_per_second,
        }

    def set_overpass_settings(
        self,
        endpoint: str | None = None,
        timeout_seconds: float | None = None,
        requests_per_second: float | None = None,
    ) -> None:
        """Update Overpass provider settings."""
        if self._overpass is None:
            return
        if endpoint is not None:
            self._overpass.settings.endpoint = endpoint
        if timeout_seconds is not None:
            self._overpass.settings.timeout_seconds = timeout_seconds
        if requests_per_second is not None:
            self._overpass.settings.requests_per_second = requests_per_second
