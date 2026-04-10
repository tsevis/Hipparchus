"""Data source provider interfaces and adapters."""

from hipparchus.data_sources.data_source_manager import DataSource, DataSourceConfig, DataSourceManager
from hipparchus.data_sources.overpass_provider import OverpassMapProvider, OverpassSettings
from hipparchus.data_sources.provider import AsyncMapProvider, BBoxQuery, FeatureCollection, MapProvider

__all__ = [
    "AsyncMapProvider",
    "BBoxQuery",
    "DataSource",
    "DataSourceConfig",
    "DataSourceManager",
    "FeatureCollection",
    "MapProvider",
    "OverpassMapProvider",
    "OverpassSettings",
]
