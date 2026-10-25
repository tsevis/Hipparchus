"""Optional providers for richer Hipparchus map sources.

These adapters intentionally keep heavy geospatial dependencies optional. Every
provider can consume GeoJSON/JSON fixtures directly; specialized formats become
available only when their backend package is installed.
"""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Iterable
import zlib

from shapely.geometry import LineString, box, mapping, shape
from shapely.geometry.base import BaseGeometry

from hipparchus.data_sources.map_models import ProviderStatus
from hipparchus.data_sources.overpass_geojson import _classify_layer, _geometry_for_element
from hipparchus.data_sources.overpass_query import SUPPORTED_LAYERS
from hipparchus.data_sources.provider import BBoxQuery, FeatureCollection, GeoJSONMapping


EXTRA_LAYERS = (
    "admin_boundaries",
    "state_boundaries",
    "county_boundaries",
    "terrain_contours",
    "terrain_index_contours",
    "terrain_hillshade",
    "elevation_bands",
    "depth_bands",
    "night_lights",
    "earthquakes_shallow",
    "earthquakes_intermediate",
    "earthquakes_deep",
    "satellite_tracks",
    "satellite_footprints",
    "bathymetry",
    "summits",
    "current_streamlines",
)
ALL_OPTIONAL_LAYERS = tuple(dict.fromkeys((*SUPPORTED_LAYERS, *EXTRA_LAYERS)))

# Providers whose source is a single-band raster read through the contour path.
RASTER_PROVIDER_IDS = frozenset({"terrain_dem", "night_lights"})
RASTER_SUFFIXES = frozenset({".tif", ".tiff"})


class OptionalProviderUnavailable(RuntimeError):
    """Raised when an optional source provider is selected without its backend."""


@dataclass(slots=True)
class OptionalSourceProvider:
    """Dependency-isolated provider for local/rich sources."""

    provider_id: str
    label: str
    dependency_module: str | None = None
    source_path: Path | None = None
    # Raster providers name their contour output. Terrain reads elevation;
    # night lights read radiance from the same code path.
    raster_layer: str = "terrain_contours"
    raster_value_key: str = "elevation"
    raster_levels: int = 12

    def status(self) -> ProviderStatus:
        if self.source_path is None:
            return ProviderStatus(
                provider_id=self.provider_id,
                label=self.label,
                available=False,
                detail="No source path configured",
            )
        if not self.source_path.exists():
            return ProviderStatus(
                provider_id=self.provider_id,
                label=self.label,
                available=False,
                detail=f"Source path not found: {self.source_path}",
            )
        if _is_geojson_source(self.source_path):
            return ProviderStatus(provider_id=self.provider_id, label=self.label, available=True)
        if self.provider_id == "vector_tiles":
            tile_status = _vector_tile_status(self.source_path)
            if tile_status is not None:
                return ProviderStatus(
                    provider_id=self.provider_id,
                    label=self.label,
                    available=tile_status[0],
                    detail=tile_status[1],
                )
        if self.provider_id in RASTER_PROVIDER_IDS and self.source_path.suffix.lower() in RASTER_SUFFIXES:
            try:
                __import__("rasterio")
            except Exception as exc:  # noqa: BLE001
                return ProviderStatus(
                    provider_id=self.provider_id,
                    label=self.label,
                    available=False,
                    detail=f"Optional dependency missing: {exc}",
                )
            return ProviderStatus(provider_id=self.provider_id, label=self.label, available=True)
        if self.dependency_module:
            try:
                __import__(self.dependency_module)
            except Exception as exc:  # noqa: BLE001
                return ProviderStatus(
                    provider_id=self.provider_id,
                    label=self.label,
                    available=False,
                    detail=f"Optional dependency missing: {exc}",
                )
        return ProviderStatus(provider_id=self.provider_id, label=self.label, available=True)

    def fetch_bbox(self, query: BBoxQuery) -> FeatureCollection:
        status = self.status()
        if not status.available:
            raise OptionalProviderUnavailable(f"{self.label} is unavailable: {status.detail}")
        if self.source_path is None:
            raise OptionalProviderUnavailable(f"{self.label} has no source path configured")

        if _is_geojson_source(self.source_path):
            return _feature_collection_from_geojson_sources(
                _iter_geojson_payloads(self.source_path),
                query=query,
                provider_id=self.provider_id,
            )
        if self.provider_id == "local_osm_pbf":
            return _feature_collection_from_osm_pbf(self.source_path, query=query, provider_id=self.provider_id)
        if self.provider_id == "natural_earth":
            return _feature_collection_from_fiona(self.source_path, query=query, provider_id=self.provider_id)
        if self.provider_id == "overture":
            return _feature_collection_from_overture_parquet(self.source_path, query=query, provider_id=self.provider_id)
        if self.provider_id == "vector_tiles":
            return _feature_collection_from_vector_tiles(self.source_path, query=query, provider_id=self.provider_id)
        if self.provider_id in RASTER_PROVIDER_IDS:
            if self.source_path.suffix.lower() in RASTER_SUFFIXES:
                return _feature_collection_from_raster_dem(
                    self.source_path,
                    query=query,
                    provider_id=self.provider_id,
                    value_layer=self.raster_layer,
                    value_key=self.raster_value_key,
                    level_count=self.raster_levels,
                )
            return _feature_collection_from_geojson_sources(
                _iter_geojson_payloads(self.source_path),
                query=query,
                provider_id=self.provider_id,
            )

        return FeatureCollection(
            features_by_layer={},
            geojson_by_layer={},
            metadata={"source": self.provider_id, "empty": True},
            bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat),
        )


def local_osm_pbf_provider(source_path: Path | None = None) -> OptionalSourceProvider:
    return OptionalSourceProvider("local_osm_pbf", "Local OSM PBF", "osmium", source_path)


def vector_tile_provider(source_path: Path | None = None) -> OptionalSourceProvider:
    return OptionalSourceProvider("vector_tiles", "PMTiles/MBTiles Vector Tiles", None, source_path)


def natural_earth_provider(source_path: Path | None = None) -> OptionalSourceProvider:
    return OptionalSourceProvider("natural_earth", "Natural Earth", "fiona", source_path)


def overture_provider(source_path: Path | None = None) -> OptionalSourceProvider:
    return OptionalSourceProvider("overture", "Overture Maps", "pyarrow", source_path)


def terrain_dem_provider(source_path: Path | None = None) -> OptionalSourceProvider:
    return OptionalSourceProvider("terrain_dem", "Terrain DEM", None, source_path)


def night_lights_provider(source_path: Path | None = None) -> OptionalSourceProvider:
    """Provider for measured nighttime illumination rasters (VIIRS/Black Marble).

    Shares the single-band raster contour path with the DEM provider; only the
    output naming and level count differ. Values are whatever the source encodes
    -- calibrated radiance for VNL/VNP46A, rendered luminance for a GIBS capture.
    """
    return OptionalSourceProvider(
        "night_lights",
        "VIIRS Night Lights",
        None,
        source_path,
        raster_layer="night_lights",
        raster_value_key="radiance",
        raster_levels=16,
    )


def _is_geojson_source(path: Path) -> bool:
    if path.is_dir():
        return any(child.suffix.lower() in {".geojson", ".json"} for child in path.iterdir())
    return path.suffix.lower() in {".geojson", ".json"}


def _iter_geojson_payloads(path: Path) -> Iterable[GeoJSONMapping]:
    paths = sorted(path.glob("*.geojson")) + sorted(path.glob("*.json")) if path.is_dir() else [path]
    for item in paths:
        with item.open("r", encoding="utf-8") as handle:
            yield json.load(handle)


def _feature_collection_from_geojson_sources(
    payloads: Iterable[GeoJSONMapping],
    *,
    query: BBoxQuery,
    provider_id: str,
) -> FeatureCollection:
    features_by_layer = _empty_layers()
    query_box = box(query.min_lon, query.min_lat, query.max_lon, query.max_lat)

    for payload in payloads:
        for feature in _iter_geojson_features(payload):
            geometry = feature.get("geometry")
            if geometry is None:
                continue
            try:
                geom = shape(geometry)
            except Exception:
                continue
            if geom.is_empty or not geom.intersects(query_box):
                continue
            properties = dict(feature.get("properties", {}))
            layer = _layer_for_properties(properties, provider_id=provider_id, geometry=geom)
            if layer is None or layer not in features_by_layer:
                continue
            normalized = {
                "type": "Feature",
                "id": feature.get("id", f"{provider_id}/{layer}/{len(features_by_layer[layer])}"),
                "geometry": mapping(geom),
                "properties": named_properties(properties) | {"hipparchus_source": provider_id},
            }
            features_by_layer[layer].append(normalized)

    return _collection_from_layers(
        features_by_layer,
        metadata={"source": provider_id, "format": "geojson"},
        bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat),
    )


def _iter_geojson_features(payload: GeoJSONMapping) -> Iterable[GeoJSONMapping]:
    if payload.get("type") == "FeatureCollection":
        yield from payload.get("features", [])
    elif payload.get("type") == "Feature":
        yield payload
    elif "features" in payload:
        yield from payload.get("features", [])


def _bbox_overlaps(
    candidate: tuple[float, float, float, float],
    query_bounds: tuple[float, float, float, float],
) -> bool:
    """Cheap separating-axis test on (min_lon, min_lat, max_lon, max_lat).

    Deliberately a conservative superset of a true intersection: anything that
    might intersect is kept, and the exact shapely test in ``_append_feature``
    still decides. Testing feature bounds rather than 'any vertex inside the
    query' matters -- the latter silently drops long ways that cross the query
    box without placing a vertex in it.
    """
    return not (
        candidate[2] < query_bounds[0]
        or candidate[0] > query_bounds[2]
        or candidate[3] < query_bounds[1]
        or candidate[1] > query_bounds[3]
    )


def _feature_collection_from_osm_pbf(path: Path, *, query: BBoxQuery, provider_id: str) -> FeatureCollection:
    import osmium  # type: ignore

    features_by_layer = _empty_layers()
    query_bounds = (query.min_lon, query.min_lat, query.max_lon, query.max_lat)
    query_box = box(*query_bounds)

    class _Handler(osmium.SimpleHandler):  # type: ignore[misc]
        def node(self, node) -> None:  # noqa: ANN001
            # Location first: it rejects nearly every node in a region-sized
            # extract for the cost of two float comparisons, before any tag
            # dict or shapely geometry is built.
            try:
                lon = float(node.location.lon)
                lat = float(node.location.lat)
            except Exception:
                return
            if not (query_bounds[0] <= lon <= query_bounds[2] and query_bounds[1] <= lat <= query_bounds[3]):
                return
            tags = {str(tag.k): str(tag.v) for tag in node.tags}
            layer = _classify_layer(tags)
            if layer is None or layer not in features_by_layer:
                return
            geom = {"type": "Point", "coordinates": [lon, lat]}
            _append_feature(features_by_layer, layer, f"node/{node.id}", geom, tags, query_box, provider_id)

        def way(self, way) -> None:  # noqa: ANN001
            tags = {str(tag.k): str(tag.v) for tag in way.tags}
            layer = _classify_layer(tags)
            if layer is None or layer not in features_by_layer:
                return
            coords: list[list[float]] = []
            min_lon = min_lat = float("inf")
            max_lon = max_lat = float("-inf")
            for node in way.nodes:
                try:
                    lon = float(node.lon)
                    lat = float(node.lat)
                except Exception:
                    continue
                coords.append([lon, lat])
                min_lon = lon if lon < min_lon else min_lon
                max_lon = lon if lon > max_lon else max_lon
                min_lat = lat if lat < min_lat else min_lat
                max_lat = lat if lat > max_lat else max_lat
            if len(coords) < 2:
                return
            # Reject out-of-area ways before constructing shapely geometry,
            # which dominates the cost on a region-sized extract.
            if not _bbox_overlaps((min_lon, min_lat, max_lon, max_lat), query_bounds):
                return
            element = {"type": "way", "id": way.id, "tags": tags, "geometry": [{"lon": x, "lat": y} for x, y in coords]}
            geom = _geometry_for_element(element)
            if geom is not None:
                _append_feature(features_by_layer, layer, f"way/{way.id}", geom, tags, query_box, provider_id)

    handler = _Handler()
    handler.apply_file(str(path), locations=True)
    return _collection_from_layers(
        features_by_layer,
        metadata={"source": provider_id, "format": "osm.pbf", "path": str(path)},
        bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat),
    )


def _feature_collection_from_fiona(path: Path, *, query: BBoxQuery, provider_id: str) -> FeatureCollection:
    import fiona  # type: ignore

    features_by_layer = _empty_layers()
    query_box = box(query.min_lon, query.min_lat, query.max_lon, query.max_lat)
    paths = _vector_paths(path, suffixes={".shp", ".geojson", ".json", ".gpkg"})

    for vector_path in paths:
        with fiona.open(vector_path) as source:
            for feature in source:
                geometry = feature.get("geometry")
                if geometry is None:
                    continue
                properties = dict(feature.get("properties") or {})
                try:
                    geom = shape(geometry)
                except Exception:
                    continue
                layer = _layer_for_properties(properties, provider_id=provider_id, geometry=geom)
                if layer is not None:
                    # The feature's own ordinal in the layer it landed in, not
                    # the record number fiona reports. A folder reads as one
                    # source and every file in it starts counting records at
                    # zero again, so a Natural Earth scale folder produced seven
                    # features all called "0". Ids travel into the exported SVG.
                    #
                    # The *properties* need no such care: a `.dbf` is paired to
                    # its `.shp` by position, and GDAL does that pairing here.
                    # See `tests/test_natural_earth_shapefile.py` for why that is
                    # worth a test -- the macOS port hand-rolled the reader,
                    # indexed the attributes by how many features it had kept,
                    # and drew a Europe sheet labelled Agra and Albuquerque.
                    feature_id = f"{provider_id}/{layer}/{len(features_by_layer[layer])}"
                    _append_feature(features_by_layer, layer, feature_id, mapping(geom), properties, query_box, provider_id)

    return _collection_from_layers(
        features_by_layer,
        metadata={"source": provider_id, "format": "fiona", "path": str(path)},
        bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat),
    )


def _feature_collection_from_overture_parquet(path: Path, *, query: BBoxQuery, provider_id: str) -> FeatureCollection:
    import pyarrow.parquet as pq  # type: ignore
    from shapely import wkb

    features_by_layer = _empty_layers()
    query_box = box(query.min_lon, query.min_lat, query.max_lon, query.max_lat)
    paths = _vector_paths(path, suffixes={".parquet"})

    for parquet_path in paths:
        table = pq.ParquetFile(parquet_path).read()
        columns = table.to_pydict()
        geometry_values = columns.get("geometry")
        if geometry_values is None:
            continue
        row_count = len(geometry_values)
        for index in range(row_count):
            raw_geom = geometry_values[index]
            if raw_geom is None:
                continue
            try:
                geom = wkb.loads(bytes(raw_geom))
            except Exception:
                continue
            properties = {
                key: values[index]
                for key, values in columns.items()
                if key != "geometry" and index < len(values)
            }
            layer = _layer_for_properties(properties, provider_id=provider_id, geometry=geom)
            if layer is not None:
                _append_feature(features_by_layer, layer, f"{parquet_path.name}/{index}", mapping(geom), properties, query_box, provider_id)

    return _collection_from_layers(
        features_by_layer,
        metadata={"source": provider_id, "format": "geoparquet", "path": str(path)},
        bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat),
    )


def _vector_tile_status(path: Path) -> tuple[bool, str] | None:
    suffix = path.suffix.lower()
    if suffix == ".mbtiles":
        try:
            __import__("mapbox_vector_tile")
        except Exception as exc:  # noqa: BLE001
            return (False, f"Optional dependency missing: {exc}")
        return (True, "")
    if suffix == ".pmtiles":
        try:
            __import__("pmtiles")
            __import__("mapbox_vector_tile")
        except Exception as exc:  # noqa: BLE001
            return (False, f"Optional dependency missing: {exc}")
        return (True, "")
    return None


def _feature_collection_from_vector_tiles(path: Path, *, query: BBoxQuery, provider_id: str) -> FeatureCollection:
    if path.suffix.lower() == ".mbtiles":
        return _feature_collection_from_mbtiles(path, query=query, provider_id=provider_id)
    if path.suffix.lower() == ".pmtiles":
        return _feature_collection_from_pmtiles(path, query=query, provider_id=provider_id)
    raise OptionalProviderUnavailable(f"Unsupported vector tile source: {path.suffix}")


def _feature_collection_from_mbtiles(path: Path, *, query: BBoxQuery, provider_id: str) -> FeatureCollection:
    import mapbox_vector_tile  # type: ignore

    features_by_layer = _empty_layers()
    query_box = box(query.min_lon, query.min_lat, query.max_lon, query.max_lat)
    zoom = _select_tile_zoom(path)
    tiles = _tiles_for_bbox(query, zoom)

    with sqlite3.connect(path) as conn:
        metadata = _mbtiles_metadata(conn)
        scheme = str(metadata.get("scheme", "tms")).lower()
        for z, x, y_xyz in tiles:
            y_db = (2**z - 1 - y_xyz) if scheme != "xyz" else y_xyz
            row = conn.execute(
                "select tile_data from tiles where zoom_level=? and tile_column=? and tile_row=?",
                (z, x, y_db),
            ).fetchone()
            if row is None:
                continue
            tile_bytes = _decompress_tile(row[0])
            decoded = mapbox_vector_tile.decode(tile_bytes, default_options={"y_coord_down": True})
            _append_decoded_tile(features_by_layer, decoded, z=z, x=x, y=y_xyz, query_box=query_box, provider_id=provider_id)

    return _collection_from_layers(
        features_by_layer,
        metadata={"source": provider_id, "format": "mbtiles", "path": str(path), "zoom": zoom},
        bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat),
    )


def _feature_collection_from_pmtiles(path: Path, *, query: BBoxQuery, provider_id: str) -> FeatureCollection:
    import mapbox_vector_tile  # type: ignore

    try:
        from pmtiles.reader import MmapSource, Reader  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise OptionalProviderUnavailable(f"PMTiles reader API unavailable: {exc}") from exc

    features_by_layer = _empty_layers()
    query_box = box(query.min_lon, query.min_lat, query.max_lon, query.max_lat)
    zoom = 14
    with path.open("rb") as handle:
        reader = Reader(MmapSource(handle))
        try:
            header = reader.header()
            zoom = int(header.get("max_zoom", header.get("maxZoom", zoom)))
        except Exception:
            pass
        for z, x, y in _tiles_for_bbox(query, zoom):
            tile = reader.get(z, x, y)
            if tile is None:
                continue
            tile_bytes = _decompress_tile(tile)
            decoded = mapbox_vector_tile.decode(tile_bytes, default_options={"y_coord_down": True})
            _append_decoded_tile(features_by_layer, decoded, z=z, x=x, y=y, query_box=query_box, provider_id=provider_id)

    return _collection_from_layers(
        features_by_layer,
        metadata={"source": provider_id, "format": "pmtiles", "path": str(path), "zoom": zoom},
        bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat),
    )


def _feature_collection_from_raster_dem(
    path: Path,
    *,
    query: BBoxQuery,
    provider_id: str,
    value_layer: str = "terrain_contours",
    value_key: str = "elevation",
    level_count: int = 12,
) -> FeatureCollection:
    """Contour a single-band raster into iso-value lines.

    Band-agnostic: elevation produces terrain contours, nighttime radiance
    produces iso-radiance lines. ``value_layer``/``value_key`` name the output
    so the caller is not forced to mislabel non-terrain data as terrain.
    """
    import numpy as np
    import rasterio  # type: ignore
    from rasterio.warp import transform as transform_coords  # type: ignore
    from rasterio.warp import transform_bounds  # type: ignore
    from rasterio.windows import from_bounds  # type: ignore
    from skimage import measure

    features_by_layer = _empty_layers()
    query_wgs84_bounds = (query.min_lon, query.min_lat, query.max_lon, query.max_lat)
    with rasterio.open(path) as dataset:
        raster_bounds = query_wgs84_bounds
        needs_transform = bool(dataset.crs and str(dataset.crs).upper() not in {"EPSG:4326", "OGC:CRS84"})
        if needs_transform:
            raster_bounds = transform_bounds("EPSG:4326", dataset.crs, *query_wgs84_bounds, densify_pts=21)
        window = from_bounds(*raster_bounds, dataset.transform).round_offsets().round_lengths()
        data = dataset.read(1, window=window, masked=True)
        if data.size == 0:
            return _collection_from_layers(features_by_layer, metadata={"source": provider_id, "format": "dem", "path": str(path)}, bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat))
        transform = dataset.window_transform(window)
        filled = np.asarray(data.astype(float).filled(np.nan), dtype=float)
        valid = filled[np.isfinite(filled)]
        if valid.size == 0:
            return _collection_from_layers(features_by_layer, metadata={"source": provider_id, "format": "dem", "path": str(path)}, bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat))
        levels = _contour_levels(float(valid.min()), float(valid.max()), count=level_count)
        for level in levels:
            for contour in measure.find_contours(filled, level=level):
                coords: list[tuple[float, float]] = []
                for row, col in contour:
                    x, y = transform * (float(col), float(row))
                    coords.append((x, y))
                if len(coords) < 2:
                    continue
                if needs_transform and dataset.crs:
                    xs, ys = zip(*coords)
                    lon_values, lat_values = transform_coords(dataset.crs, "EPSG:4326", list(xs), list(ys))
                    coords = list(zip(lon_values, lat_values))
                line = LineString(coords)
                if line.is_empty:
                    continue
                _append_feature(
                    features_by_layer,
                    value_layer,
                    f"contour/{level:.2f}/{len(features_by_layer[value_layer])}",
                    mapping(line),
                    {value_key: float(level), "hipparchus_layer": value_layer},
                    box(query.min_lon, query.min_lat, query.max_lon, query.max_lat),
                    provider_id,
                )

    return _collection_from_layers(
        features_by_layer,
        metadata={"source": provider_id, "format": "raster", "path": str(path), "value_key": value_key},
        bbox=(query.min_lon, query.min_lat, query.max_lon, query.max_lat),
    )


def _select_tile_zoom(path: Path, preferred: int = 14) -> int:
    with sqlite3.connect(path) as conn:
        row = conn.execute("select max(zoom_level) from tiles").fetchone()
    if row is None or row[0] is None:
        return preferred
    return int(min(max(0, int(row[0])), preferred))


def _mbtiles_metadata(conn: sqlite3.Connection) -> dict[str, str]:
    try:
        rows = conn.execute("select name, value from metadata").fetchall()
    except sqlite3.Error:
        return {}
    return {str(name): str(value) for name, value in rows}


def _tiles_for_bbox(query: BBoxQuery, zoom: int) -> list[tuple[int, int, int]]:
    x1, y1 = _lonlat_to_tile(query.min_lon, query.max_lat, zoom)
    x2, y2 = _lonlat_to_tile(query.max_lon, query.min_lat, zoom)
    n = 2**zoom
    min_x, max_x = max(0, min(x1, x2)), min(n - 1, max(x1, x2))
    min_y, max_y = max(0, min(y1, y2)), min(n - 1, max(y1, y2))
    return [(zoom, x, y) for x in range(min_x, max_x + 1) for y in range(min_y, max_y + 1)]


def _lonlat_to_tile(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    lat = max(-85.05112878, min(85.05112878, lat))
    n = 2**zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return (max(0, min(n - 1, x)), max(0, min(n - 1, y)))


def _tile_point_to_lonlat(z: int, x: int, y: int, px: float, py: float, extent: float) -> tuple[float, float]:
    n = 2**z
    world_x = (x + px / extent) / n
    world_y = (y + py / extent) / n
    lon = world_x * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * world_y)))
    return (lon, math.degrees(lat_rad))


def _append_decoded_tile(
    features_by_layer: dict[str, list[GeoJSONMapping]],
    decoded: dict[str, Any],
    *,
    z: int,
    x: int,
    y: int,
    query_box: BaseGeometry,
    provider_id: str,
) -> None:
    for source_layer, layer_payload in decoded.items():
        extent = float(layer_payload.get("extent", 4096))
        for feature in layer_payload.get("features", []):
            properties = dict(feature.get("properties") or {})
            properties.setdefault("tile_layer", source_layer)
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict):
                continue
            transformed = _transform_tile_geometry(geometry, z=z, x=x, y=y, extent=extent)
            layer = _layer_for_properties(properties, provider_id=provider_id, geometry=shape(transformed))
            if layer is not None and layer in features_by_layer:
                _append_feature(
                    features_by_layer,
                    layer,
                    f"{source_layer}/{z}/{x}/{y}/{len(features_by_layer[layer])}",
                    transformed,
                    properties,
                    query_box,
                    provider_id,
                )


def _transform_tile_geometry(geometry: GeoJSONMapping, *, z: int, x: int, y: int, extent: float) -> GeoJSONMapping:
    geom_type = str(geometry.get("type", ""))

    def convert_coord(coord: Any) -> list[float]:
        lon, lat = _tile_point_to_lonlat(z, x, y, float(coord[0]), float(coord[1]), extent)
        return [lon, lat]

    def convert_nested(coords: Any, depth: int) -> Any:
        if depth == 0:
            return convert_coord(coords)
        return [convert_nested(item, depth - 1) for item in coords]

    depth_by_type = {
        "Point": 0,
        "LineString": 1,
        "Polygon": 2,
        "MultiPoint": 1,
        "MultiLineString": 2,
        "MultiPolygon": 3,
    }
    depth = depth_by_type.get(geom_type)
    if depth is None:
        return geometry
    return {"type": geom_type, "coordinates": convert_nested(geometry.get("coordinates", []), depth)}


def _decompress_tile(tile_data: bytes) -> bytes:
    data = bytes(tile_data)
    if data.startswith(b"\x1f\x8b"):
        return gzip.decompress(data)
    try:
        return zlib.decompress(data)
    except zlib.error:
        return data


def _contour_levels(min_value: float, max_value: float, *, count: int) -> list[float]:
    if max_value <= min_value:
        return []
    step = (max_value - min_value) / max(1, count + 1)
    return [min_value + step * idx for idx in range(1, count + 1)]


def _vector_paths(path: Path, *, suffixes: set[str]) -> list[Path]:
    if path.is_dir():
        return sorted(child for child in path.rglob("*") if child.suffix.lower() in suffixes)
    return [path] if path.suffix.lower() in suffixes else []


def _layer_for_properties(properties: dict[str, Any], *, provider_id: str, geometry: BaseGeometry) -> str | None:
    explicit = _property_value(properties, "hipparchus_layer") or _property_value(properties, "layer") or _property_value(properties, "layer_name")
    if explicit:
        layer = str(explicit)
        if layer in ALL_OPTIONAL_LAYERS:
            return layer
    subdivision = _subdivision_layer(properties)
    if subdivision is not None:
        return subdivision
    if provider_id == "terrain_dem":
        return "terrain_contours" if geometry.geom_type in {"LineString", "MultiLineString"} else "elevation_bands"
    if provider_id == "natural_earth":
        feature_class = str(_property_value(properties, "featurecla") or _property_value(properties, "type") or "").lower()
        if geometry.geom_type in {"Point", "MultiPoint"} and (
            "capital" in feature_class or "populated" in feature_class or _property_value(properties, "name")
        ):
            return "places"
        if (
            "admin" in feature_class
            or "country" in feature_class
            # `ne_110m_admin_0_boundary_lines_land` says "International
            # boundary (verify)" and nothing else: no `admin` property, no
            # `NAME`. It classified into nothing and was dropped, which is a
            # quiet way to lose every border on a sheet drawn from the
            # boundary-line files rather than the country polygons.
            or "boundary" in feature_class
            or _property_value(properties, "admin")
        ):
            return "admin_boundaries"
        if "populated place" in feature_class or "populated_places" in feature_class:
            return "places"
        if "river" in feature_class:
            return "water"
        if "lake" in feature_class or "ocean" in feature_class or "coastline" in feature_class:
            return "water"
    if provider_id == "overture":
        overture_type = str(_property_value(properties, "theme") or _property_value(properties, "type") or "").lower()
        if "building" in overture_type:
            return "buildings"
        if "place" in overture_type:
            return "places"
    return _classify_layer(properties)


def _subdivision_layer(properties: dict[str, Any]) -> str | None:
    """A state or a county, recognised before anything that would file it as a country.

    Natural Earth names the level in `featurecla` ("Admin-1 states provinces",
    "Admin-2 ..."), and its admin-1 rows also carry `admin`, the country's name,
    which is what the country rule keys on. The US Census cartographic boundary
    files carry no class at all, only their FIPS columns: a county has
    `COUNTYFP`, a state `STATEFP` and `STUSPS` without one. Any source may hold
    either, so this does not ask which provider it is.
    """
    feature_class = str(_property_value(properties, "featurecla") or "").lower()
    if feature_class.startswith("admin-2"):
        return "county_boundaries"
    if feature_class.startswith("admin-1"):
        return "state_boundaries"
    # A tract or block group carries `COUNTYFP` as well, and is not a county.
    if _property_value(properties, "TRACTCE") or _property_value(properties, "BLKGRPCE"):
        return None
    if _property_value(properties, "COUNTYFP"):
        return "county_boundaries"
    if _property_value(properties, "STATEFP") and _property_value(properties, "STUSPS"):
        return "state_boundaries"
    return None


#: Spellings for a name, in order of preference, matched case-insensitively.
#:
#: `name` first so a file already speaking the right vocabulary is untouched;
#: `admin` last because a country polygon whose only name is its administrative
#: one is still better labelled than not. Case-insensitive matching is what
#: makes `NAME` and `NAMEASCII` work without listing every source's
#: capitalisation.
NAME_ALIASES: tuple[str, ...] = ("name", "name_en", "nameascii", "name_long", "admin")


def named_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Translate a file's own vocabulary for a name into the one above it.

    `_layer_for_properties` already does this for *which layer* a feature
    belongs to -- Natural Earth's `featurecla`, Overture's `theme`. This is the
    same translation for the one property the renderer reads off a feature by
    name: a label comes from `name`, spelled exactly that way, and a source
    that spells it `NAME` gets its cities classified correctly and then
    silently dropped at the point where they would have been drawn.

    Additive on purpose, and a new dict either way: the source's own spelling
    stays, because the exported SVG carries a feature's properties and
    rewriting them would lose the provenance of the word.
    """
    existing = properties.get("name")
    if isinstance(existing, str) and existing.strip():
        return properties
    for alias in NAME_ALIASES:
        for key, value in properties.items():
            if str(key).lower() != alias:
                continue
            # A blank name is no name: Natural Earth's boundary lines carry
            # `NAME` set to null, and an empty label draws an empty box.
            text = str(value).strip() if value is not None else ""
            if not text:
                continue
            return properties | {"name": text}
    return properties


def _property_value(properties: dict[str, Any], key: str) -> Any:
    if key in properties:
        return properties[key]
    lowered = key.lower()
    for item_key, value in properties.items():
        if str(item_key).lower() == lowered:
            return value
    return None


def _append_feature(
    features_by_layer: dict[str, list[GeoJSONMapping]],
    layer: str,
    feature_id: str,
    geometry: GeoJSONMapping,
    properties: dict[str, Any],
    query_box: BaseGeometry,
    provider_id: str,
) -> None:
    try:
        geom = shape(geometry)
    except Exception:
        return
    if geom.is_empty or not geom.intersects(query_box):
        return
    features_by_layer[layer].append(
        {
            "type": "Feature",
            "id": feature_id,
            "geometry": mapping(geom),
            # Translated here, at the boundary, because this is the one funnel
            # every file-backed feature passes through -- shapefile, GeoParquet,
            # vector tile and raster alike. See `named_properties`.
            "properties": named_properties(properties) | {"hipparchus_source": provider_id},
        }
    )


def _empty_layers() -> dict[str, list[GeoJSONMapping]]:
    return {layer: [] for layer in ALL_OPTIONAL_LAYERS}


def _collection_from_layers(
    features_by_layer: dict[str, list[GeoJSONMapping]],
    *,
    metadata: dict[str, Any],
    bbox: tuple[float, float, float, float],
) -> FeatureCollection:
    geojson_by_layer = {
        layer: {"type": "FeatureCollection", "name": layer, "features": features}
        for layer, features in features_by_layer.items()
    }
    return FeatureCollection(
        features_by_layer=features_by_layer,
        geojson_by_layer=geojson_by_layer,
        metadata=metadata | {"feature_count": sum(len(items) for items in features_by_layer.values())},
        bbox=bbox,
    )
