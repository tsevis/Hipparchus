"""Real elevation for any area on Earth, from public terrain tiles.

Measured ground, not a generated field: AWS's `elevation-tiles-prod` mosaic
(SRTM, NED, GMTED and friends) served as terrarium-encoded PNG over plain HTTPS
with no key and no account. Tiles for the area are fetched, stitched, cropped
and contoured through the same pipeline the rest of the app uses, so a real
mountain arrives as editable vector linework.

Terrarium packs elevation into colour: ``metres = R * 256 + G + B / 256 -
32768``, which covers the whole range from ocean floor to summit at 1/256 m.

Tiles are Web Mercator, so the grid rows are *not* evenly spaced in latitude --
they are evenly spaced in mercator y. Converting a contour vertex back to
lat/lon has to invert that projection rather than interpolate linearly, or every
contour lands slightly north of where it belongs, increasingly so towards the
poles.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
import math
from pathlib import Path
import time
from typing import Any, Callable

import numpy as np

from hipparchus.core.fetch_progress import FetchCancelled
from hipparchus.data_sources.map_models import ProviderStatus
from hipparchus.data_sources.provider_layers import _collection_from_layers, _empty_layers
from hipparchus.data_sources.emodnet_bathymetry import (
    DEFAULT_EMODNET_COVERAGE,
    DEFAULT_EMODNET_ENDPOINT,
    _band_is_measured,
    _band_surveyed_share,
    _blend_sea_floor,
    _depth_band_mode,
    _depth_source,
    _effective_measured_grid,
    _fetch_emodnet_grid,
    _measured_along_polyline,
    _surveyed_share_along_polyline,
    _surveyed_share_of_sea,
)
from hipparchus.data_sources.provider import BBoxQuery, FeatureCollection
from hipparchus.data_sources.terrain_grid import (
    MAX_SOURCE_ZOOM,
    TILE_PIXELS,
    TerrainTileError,
    _choose_zoom,
    _column_longitudes,
    _crop_to_bounds,
    _decode_terrarium,
    _ground_resolution_metres,
    _lonlat_for_pixel,
    _lonlat_mapper,
    _lonlat_sampler,
    _probe_step,
    _row_latitudes,
    _smooth,
    _tile_for,
    _Window,
)
from shapely.geometry import mapping

from hipparchus.geometry.bands import (
    DepthBandMode,
    band_boundaries,
    depth_band_boundaries,
    elevation_bands,
    land_band_boundaries,
    map_coordinates,
)
from hipparchus.geometry.contours import contour_levels, contour_polylines, orient_uphill_left
from hipparchus.geometry.hillshade import SunPosition, hillshade
from hipparchus.data_sources.simulated_field import nice_interval


TERRAIN_TILES_PROVIDER_ID = "terrain_tiles"
TERRAIN_TILES_PROVIDER_LABEL = "Terrain Tiles (real elevation)"
DEFAULT_TERRAIN_TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"

MINOR_CONTOUR_LAYER = "terrain_contours"
INDEX_CONTOUR_LAYER = "terrain_index_contours"
# Terrarium carries bathymetry in the same band as land, so the sea floor comes
# free with the coast -- but it is a different thing and reads as a different
# thing, so it gets its own layer rather than being drawn as if it were land.
BATHYMETRY_LAYER = "bathymetry"
SUMMIT_LAYER = "summits"
ELEVATION_BANDS_LAYER = "elevation_bands"
# The sea floor's own mass. `elevation_bands` always spanned the whole measured
# range, so a coastal sheet banded its sea floor in the land's ramp -- a trench
# drawn as a kind of valley. The sea got contours where the land got mass, and
# what mass it did get was wearing the wrong clothes.
DEPTH_BANDS_LAYER = "depth_bands"
HILLSHADE_LAYER = "terrain_hillshade"

HttpGetBytes = Callable[[str, float], bytes]


@dataclass(slots=True, frozen=True)
class TerrainTileSettings:
    """How much real elevation to fetch, and how to contour it."""

    url_template: str = DEFAULT_TERRAIN_TILE_URL
    # Sampling width to aim for across the area -- a *request*, in ground
    # samples, not a limit. More pixels means finer contours and more tiles to
    # fetch. 1200 is two metres a pixel over a city and thirty kilometres over
    # the world.
    target_pixels: int = 1200
    # The ceiling on what that request may cost, which is a different thing and
    # was being confused for the same one.
    #
    # 64 tiles is eight across, or 2048 px of mosaic: plenty for a city and,
    # it turned out, a silent cap on everything larger. A world frame asked to
    # be sampled 4096 px across came back at 2048 and said nothing, because the
    # budget ran out a zoom level before `target_pixels` did.
    #
    # 256 tiles is sixteen across, or 4096 px, and it sits there because that
    # is where the machine gives out rather than because it is a round number.
    # Measured here, on a world frame with relief and Natural Earth on -- see
    # the README table: 1200 px is zoom 2 and a minute; 4096 px is zoom 4,
    # around 8 GB of peak resident memory, and most of that is not the mosaic
    # (16.7 million cells at eight bytes is 134 MB) but the copies taken
    # through cropping, smoothing and banding plus the traced geometry. Past
    # this an 8 GB machine would be swapping, so the answer is a smaller frame
    # rather than a bigger fetch.
    #
    # Nothing reaches it by accident: `target_pixels` still governs, and its
    # default puts a world frame at zoom 2.
    max_tiles: int = 256
    max_zoom: int = MAX_SOURCE_ZOOM
    timeout_seconds: float = 30.0
    max_attempts: int = 3
    retry_delay_seconds: float = 0.7
    max_parallel_requests: int = 8
    # 0.0 chooses a round interval from the relief actually in view.
    contour_interval_metres: float = 0.0
    target_line_count: int = 60
    index_every: int = 5
    min_contour_length_cells: float = 2.0
    # Sub-sea contours are split off so the sea floor can be styled apart from
    # the land, or switched off entirely.
    separate_bathymetry: bool = True
    # Summits are labelled with their real height. A block this wide has to
    # contain the peak for it to count, which keeps a rough slope from
    # sprouting a label on every bump.
    summit_block_pixels: int = 96
    max_summits: int = 24
    min_summit_prominence_metres: float = 40.0
    # A high point on the sea floor is not a summit. Without this an ocean area
    # gets two dozen labelled "peaks" nobody can stand on.
    min_summit_elevation_metres: float = 1.0
    # Filled hypsometric bands. Broad areas, so they are traced on a decimated
    # copy of the grid: full resolution costs time and adds detail no fill can
    # show.
    emit_elevation_bands: bool = True
    elevation_band_count: int = 10
    band_grid_max_pixels: int = 520
    # The sea floor gets its own ramp rather than borrowing the land's. Off
    # gives the single ramp across the whole range that every sheet had before,
    # kept so an old render and a new one can be compared.
    separate_depth_bands: bool = True
    depth_band_count: int = 6
    depth_band_mode: str = DepthBandMode.EVEN.value
    # Real DEMs carry step noise from their source resolution; one light pass
    # settles it without moving the landforms.
    smoothing_passes: int = 1
    # Relief shading, banded the same way elevation is. Off by default: it
    # changes the look of every sheet, which is a choice about the drawing
    # rather than a fact about the ground.
    emit_hillshade: bool = False
    hillshade_band_count: int = 7
    hillshade_grid_max_pixels: int = 420
    # A derivative carries several times the noise of the elevation it comes
    # from; smoothed after shading rather than before, or the bands speckle
    # into hundreds of one-cell polygons.
    hillshade_smoothing_passes: int = 2
    hillshade_sun_azimuth_degrees: float = 315.0
    hillshade_sun_altitude_degrees: float = 45.0
    hillshade_exaggeration: float = 1.0
    # A finer sea floor, where EMODnet has one -- blended into the grid the
    # contours, bands, hillshade and summits all read, so all four improve at
    # once. On by default: a straight accuracy improvement over the AWS
    # mosaic's own kilometre-scale ocean grid, not a new look.
    use_emodnet_bathymetry: bool = True
    emodnet_endpoint: str = DEFAULT_EMODNET_ENDPOINT
    emodnet_coverage: str = DEFAULT_EMODNET_COVERAGE
    emodnet_max_pixels: int = 1200
    emodnet_timeout_seconds: float = 30.0
    emodnet_max_attempts: int = 2
    # How far in from the true edge of what EMODnet returned the blend ramps,
    # as a fraction of the response's own shorter span.
    emodnet_feather_fraction: float = 0.06


@dataclass(slots=True)
class TerrainTileProvider:
    """Fetches and contours real elevation for the area."""

    settings: TerrainTileSettings = field(default_factory=TerrainTileSettings)
    http_get: HttpGetBytes | None = None
    # Set by the manager for a fetch that can be cancelled. Checked between
    # tiles, which is the only place this provider ever waits.
    cancel_check: Callable[[], bool] | None = None
    provider_id: str = TERRAIN_TILES_PROVIDER_ID
    label: str = TERRAIN_TILES_PROVIDER_LABEL
    source_path: Path | None = None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            label=self.label,
            available=True,
            detail="Live public elevation tiles - real measured ground, no key needed",
        )

    def fetch_bbox(self, query: BBoxQuery) -> FeatureCollection:
        bounds = (query.min_lon, query.min_lat, query.max_lon, query.max_lat)
        zoom = _choose_zoom(bounds, self.settings)
        mosaic, origin = self._mosaic(bounds, zoom)
        grid, window = _crop_to_bounds(mosaic, origin, zoom, bounds)
        if grid.size == 0:
            raise TerrainTileError("Elevation tiles covered no part of the area")

        emodnet_cells = 0
        sea_floor_surveyed_share = 0.0
        # Per-cell "does this read as measured ground" (`None` when EMODnet
        # wasn't used or had nothing to add), carried through the smoothing
        # pass below -- it doesn't change shape -- so bathymetry contours and
        # elevation bands can tell measured ground from the coarse global
        # grid they replaced. Land is already folded in as measured; see
        # `_effective_measured_grid`.
        surveyed_grid: np.ndarray | None = None
        if self.settings.use_emodnet_bathymetry:
            grid, surveyed_grid, emodnet_cells, sea_floor_surveyed_share = self._blend_emodnet(
                grid, window, zoom, bounds
            )

        grid = _smooth(grid, self.settings.smoothing_passes)

        finite = grid[np.isfinite(grid)]
        lowest = float(finite.min()) if finite.size else 0.0
        highest = float(finite.max()) if finite.size else 0.0

        interval = self.settings.contour_interval_metres
        if interval <= 0.0:
            interval = nice_interval(highest - lowest, target_lines=self.settings.target_line_count)
        levels = contour_levels(lowest, highest, interval=interval, index_every=self.settings.index_every)

        to_lonlat = _lonlat_mapper(window, zoom)
        sample = _lonlat_sampler(grid, window, zoom)
        probe = _probe_step(window, zoom)

        features_by_layer = _empty_layers()
        for layer, layer_levels in (
            (MINOR_CONTOUR_LAYER, levels.minor),
            (INDEX_CONTOUR_LAYER, levels.index),
        ):
            for level in layer_levels:
                for polyline in contour_polylines(grid, level):
                    if _polyline_length(polyline) < self.settings.min_contour_length_cells:
                        continue
                    coordinates = [to_lonlat(row, col) for row, col in polyline]
                    if len(coordinates) < 2:
                        continue
                    coordinates = orient_uphill_left(coordinates, sample=sample, level=level, probe=probe)
                    target = layer
                    # Land contours are always measured ground (SRTM and
                    # friends); only a bathymetry contour can cross from
                    # EMODnet's real survey back onto the coarse global grid.
                    measured = True
                    properties = {
                        "elevation": float(level),
                        "contour_interval": float(interval),
                        "index_contour": layer == INDEX_CONTOUR_LAYER,
                        "hipparchus_layer": target,
                        "hipparchus_source": self.provider_id,
                    }
                    if self.settings.separate_bathymetry and level < 0.0:
                        target = BATHYMETRY_LAYER
                        properties["hipparchus_layer"] = target
                        if surveyed_grid is not None:
                            measured = _measured_along_polyline(surveyed_grid, polyline)
                            share = _surveyed_share_along_polyline(surveyed_grid, polyline)
                            properties["surveyed_share"] = share
                            properties["depth_source"] = _depth_source(share)
                    properties["measured"] = measured
                    features_by_layer[target].append(
                        {
                            "type": "Feature",
                            "id": f"{self.provider_id}/{target}/{level:.1f}/{len(features_by_layer[target])}",
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[lon, lat] for lon, lat in coordinates],
                            },
                            "properties": properties,
                        }
                    )

        if self.settings.emit_elevation_bands:
            finite = grid[np.isfinite(grid)]
            low = float(finite.min()) if finite.size else 0.0
            high = float(finite.max()) if finite.size else 0.0
            # `surveyed` goes only to the depth bands below, not to this one --
            # a land band is never on the sea floor, so a survey/global-grid
            # claim about it says nothing real.
            common = dict(
                provider_id=self.provider_id,
                max_pixels=self.settings.band_grid_max_pixels,
            )

            if not self.settings.separate_depth_bands:
                # One ramp across the whole range, sea floor included: what every
                # sheet did before the split, so no survey grid here either --
                # this is the old behaviour, not a new claim about it.
                features_by_layer[ELEVATION_BANDS_LAYER] = _band_features(
                    grid, window, zoom, count=self.settings.elevation_band_count, **common
                )
            else:
                features_by_layer[ELEVATION_BANDS_LAYER] = _band_features(
                    grid, window, zoom,
                    count=self.settings.elevation_band_count,
                    boundaries=land_band_boundaries(
                        low, high, self.settings.elevation_band_count
                    ),
                    **common,
                )
                features_by_layer[DEPTH_BANDS_LAYER] = _band_features(
                    grid, window, zoom,
                    count=self.settings.depth_band_count,
                    layer=DEPTH_BANDS_LAYER,
                    boundaries=depth_band_boundaries(
                        low, high, self.settings.depth_band_count,
                        _depth_band_mode(self.settings.depth_band_mode),
                    ),
                    surveyed=surveyed_grid,
                    **common,
                )

        if self.settings.emit_hillshade:
            features_by_layer[HILLSHADE_LAYER] = _hillshade_features(
                grid,
                window,
                zoom,
                provider_id=self.provider_id,
                count=self.settings.hillshade_band_count,
                max_pixels=self.settings.hillshade_grid_max_pixels,
                sun=SunPosition(
                    azimuth_degrees=self.settings.hillshade_sun_azimuth_degrees,
                    altitude_degrees=self.settings.hillshade_sun_altitude_degrees,
                ),
                exaggeration=self.settings.hillshade_exaggeration,
                smoothing_passes=self.settings.hillshade_smoothing_passes,
            )

        features_by_layer[SUMMIT_LAYER] = _summit_features(
            grid,
            to_lonlat,
            provider_id=self.provider_id,
            block=self.settings.summit_block_pixels,
            limit=self.settings.max_summits,
            prominence=self.settings.min_summit_prominence_metres,
            min_elevation=self.settings.min_summit_elevation_metres,
        )

        return _collection_from_layers(
            features_by_layer,
            metadata={
                "source": self.provider_id,
                "format": "terrarium_tiles",
                "summit_count": len(features_by_layer[SUMMIT_LAYER]),
                "elevation_band_count": len(features_by_layer[ELEVATION_BANDS_LAYER]),
                "hillshade_band_count": len(features_by_layer[HILLSHADE_LAYER]),
                "measured": True,
                "zoom": zoom,
                "grid_shape": [int(grid.shape[0]), int(grid.shape[1])],
                "elevation_min_metres": lowest,
                "elevation_max_metres": highest,
                "contour_interval_metres": interval,
                "index_every": self.settings.index_every,
                # How much of the sea floor on this sheet is EMODnet's ~115 m
                # rather than the mosaic's kilometre-scale ocean grid. A
                # reader is entitled to know which of the two they are
                # looking at, and a sheet that does not say cannot be told
                # apart afterwards.
                "bathymetry_source": "emodnet+terrarium" if emodnet_cells else "terrarium",
                "emodnet_cells": emodnet_cells,
                "sea_floor_surveyed_share": sea_floor_surveyed_share,
            },
            bbox=bounds,
        )

    def _blend_emodnet(
        self,
        grid: np.ndarray,
        window: "_Window",
        zoom: int,
        bounds: tuple[float, float, float, float],
    ) -> tuple[np.ndarray, np.ndarray | None, int, float]:
        """A finer sea floor, where EMODnet has one.

        Blended into the grid itself rather than emitted as a layer of its
        own: the contours, the bands, the hillshade and the summits are all
        downstream of this one array, so every one of them improves without
        knowing anything happened. A per-cell "measured ground" grid is
        handed back too (`None` when there was nothing to blend), so a
        bathymetry contour or elevation band can tell EMODnet's real survey
        apart from the coarse global grid it may still be sitting on in
        part.
        """
        finer = _fetch_emodnet_grid(
            bounds,
            grid.shape[0],
            grid.shape[1],
            self.settings,
            self.http_get or _default_http_get_bytes,
        )
        if finer is None:
            return grid, None, 0, 0.0
        finer_grid, finer_bounds = finer
        row_lats = _row_latitudes(window, zoom, grid.shape[0])
        col_lons = _column_longitudes(window, zoom, grid.shape[1])
        blended, surveyed, replaced = _blend_sea_floor(
            grid,
            row_lats,
            col_lons,
            finer_grid,
            finer_bounds,
            feather_fraction=self.settings.emodnet_feather_fraction,
        )
        # Folded against *this*, unsmoothed grid -- the smoothing pass still
        # ahead of it can blur a coastal cell's sign across zero, and a
        # feature built afterwards has no way back to which side of the
        # coast a cell started on.
        measured_grid = _effective_measured_grid(blended, surveyed)
        return blended, measured_grid, replaced, _surveyed_share_of_sea(blended, surveyed)

    def _mosaic(self, bounds: tuple[float, float, float, float], zoom: int) -> tuple[np.ndarray, tuple[int, int]]:
        min_lon, min_lat, max_lon, max_lat = bounds
        min_x, min_y = _tile_for(min_lon, max_lat, zoom)
        max_x, max_y = _tile_for(max_lon, min_lat, zoom)
        columns = max_x - min_x + 1
        rows = max_y - min_y + 1
        if columns * rows > self.settings.max_tiles:
            raise TerrainTileError(
                f"Area needs {columns * rows} elevation tiles at zoom {zoom}, over the {self.settings.max_tiles} limit"
            )

        mosaic = np.full((rows * TILE_PIXELS, columns * TILE_PIXELS), np.nan, dtype=float)
        # Tiles are independent network round trips, so fetching them one after
        # another spends the whole time waiting. A pool turns a 20-tile area
        # from half a minute into a few seconds.
        requests = [(row, column) for row in range(rows) for column in range(columns)]
        workers = max(1, min(self.settings.max_parallel_requests, len(requests)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._tile, zoom, min_x + column, min_y + row): (row, column)
                for row, column in requests
            }
            for future in as_completed(futures):
                if self.cancel_check is not None and self.cancel_check():
                    for pending in futures:
                        pending.cancel()
                    raise FetchCancelled("Elevation fetch cancelled")
                row, column = futures[future]
                tile = future.result()
                if tile is None:
                    continue
                mosaic[
                    row * TILE_PIXELS : (row + 1) * TILE_PIXELS,
                    column * TILE_PIXELS : (column + 1) * TILE_PIXELS,
                ] = tile
        if not np.isfinite(mosaic).any():
            raise TerrainTileError("No elevation tiles could be read for this area")
        return (mosaic, (min_x, min_y))

    def _tile(self, zoom: int, x: int, y: int) -> np.ndarray | None:
        url = self.settings.url_template.format(z=zoom, x=x, y=y)
        getter = self.http_get or _default_http_get_bytes
        attempts = max(1, int(self.settings.max_attempts))
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return _decode_terrarium(getter(url, self.settings.timeout_seconds))
            except Exception as exc:  # noqa: BLE001 - a missing tile is a hole, not a failure
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(self.settings.retry_delay_seconds * (attempt + 1))
        # One unavailable tile leaves a gap; the rest of the area still draws.
        _ = last_error
        return None


def terrain_tile_provider(
    settings: TerrainTileSettings | None = None,
    http_get: HttpGetBytes | None = None,
) -> TerrainTileProvider:
    return TerrainTileProvider(settings=settings or TerrainTileSettings(), http_get=http_get)


def _band_features(
    grid: np.ndarray,
    window: "_Window",
    zoom: int,
    *,
    provider_id: str,
    count: int,
    max_pixels: int,
    surveyed: np.ndarray | None = None,
    layer: str = ELEVATION_BANDS_LAYER,
    boundaries: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Filled hypsometric bands, low to high.

    ``boundaries`` overrides the even division of the whole range, which is how
    the land and the sea floor get their own ramps instead of sharing one.
    """
    if count < 2:
        return []

    step = max(1, int(math.ceil(max(grid.shape) / max(16, max_pixels))))
    coarse = grid[::step, ::step]
    coarse_surveyed = surveyed[::step, ::step] if surveyed is not None else None
    finite = coarse[np.isfinite(coarse)]
    if finite.size == 0:
        return []

    if boundaries is None:
        boundaries = band_boundaries(float(finite.min()), float(finite.max()), count)
    if len(boundaries) < 2:
        return []
    bands = elevation_bands(coarse, boundaries)
    if not bands:
        return []

    def to_lonlat(row: float, col: float) -> tuple[float, float]:
        # Decimation changes the index scale, not the geography.
        return _lonlat_for_pixel(window.left + col * step, window.top + row * step, zoom)

    features: list[dict[str, Any]] = []
    for index, band in enumerate(bands):
        geometry = map_coordinates(band.geometry, to_lonlat)
        if geometry.is_empty:
            continue
        properties: dict[str, Any] = {
            "elevation_low": band.lower,
            "elevation_high": band.upper,
            "band_index": index,
            "band_count": len(bands),
            "hipparchus_layer": layer,
            "hipparchus_source": provider_id,
            "measured": _band_is_measured(coarse, coarse_surveyed, band),
        }
        if coarse_surveyed is not None:
            share = _band_surveyed_share(coarse, coarse_surveyed, band)
            properties["surveyed_share"] = share
            properties["depth_source"] = _depth_source(share)
        features.append(
            {
                "type": "Feature",
                "id": f"{provider_id}/{layer}/{index}",
                "geometry": mapping(geometry),
                "properties": properties,
            }
        )
    return features


def _hillshade_features(
    grid: np.ndarray,
    window: "_Window",
    zoom: int,
    *,
    provider_id: str,
    count: int,
    max_pixels: int,
    sun: SunPosition,
    exaggeration: float,
    smoothing_passes: int,
) -> list[dict[str, Any]]:
    """Relief shading, filled and banded the way the elevation bands are.

    Banded on a **fixed** 0...1 scale, not the observed range of light and
    shadow actually in the tile. Stretching the observed range sounds right --
    gentle ground never reaches either extreme -- but it turns "how much
    relief is there" into "always maximum contrast", and flat or nearly flat
    ground mottles into a texture that reads as terrain and is not.
    """
    if count < 2:
        return []

    step = max(1, int(math.ceil(max(grid.shape) / max(16, max_pixels))))
    coarse = grid[::step, ::step]
    if coarse.size == 0 or not np.isfinite(coarse).any():
        return []

    centre_row = window.top + (coarse.shape[0] * step) / 2.0
    centre_col = window.left + (coarse.shape[1] * step) / 2.0
    _, centre_lat = _lonlat_for_pixel(centre_col, centre_row, zoom)
    cell_size_metres = _ground_resolution_metres(centre_lat, zoom) * step

    illumination = hillshade(coarse, sun=sun, cell_size_metres=cell_size_metres, exaggeration=exaggeration)
    illumination = _smooth(illumination, smoothing_passes)

    boundaries = band_boundaries(0.0, 1.0, count)
    bands = elevation_bands(illumination, boundaries)
    if not bands:
        return []

    def to_lonlat(row: float, col: float) -> tuple[float, float]:
        # Decimation changes the index scale, not the geography.
        return _lonlat_for_pixel(window.left + col * step, window.top + row * step, zoom)

    features: list[dict[str, Any]] = []
    for band in bands:
        geometry = map_coordinates(band.geometry, to_lonlat)
        if geometry.is_empty:
            continue
        # The band's place on the fixed scale, not in this (possibly
        # compacted) list: `elevation_bands` drops any band the illumination
        # never reaches, and a band index taken from list position would put
        # ground that only ever reaches two adjacent tones at the ramp's two
        # extremes -- the stretching above, moved one step downstream.
        index = int(round(band.lower * count))
        features.append(
            {
                "type": "Feature",
                "id": f"{provider_id}/{HILLSHADE_LAYER}/{index}",
                "geometry": mapping(geometry),
                "properties": {
                    "shade_low": band.lower,
                    "shade_high": band.upper,
                    "band_index": index,
                    "band_count": count,
                    "sun_azimuth": sun.azimuth_degrees,
                    "sun_altitude": sun.altitude_degrees,
                    "hipparchus_layer": HILLSHADE_LAYER,
                    "hipparchus_source": provider_id,
                    "measured": True,
                },
            }
        )
    return features


def _summit_features(
    grid: np.ndarray,
    to_lonlat: Callable[[float, float], tuple[float, float]],
    *,
    provider_id: str,
    block: int,
    limit: int,
    prominence: float,
    min_elevation: float,
) -> list[dict[str, Any]]:
    """Label the highest ground, with the height actually measured there.

    A contour sheet tells you the shape but never the number. Taking the maximum
    of each block, and keeping only blocks that stand clear of their own
    surroundings, puts a real height on the peaks without labelling every bump
    on a slope.
    """
    height, width = grid.shape
    if height < block or width < block or limit <= 0:
        return []

    candidates: list[tuple[float, int, int]] = []
    for top in range(0, height - block + 1, block):
        for left in range(0, width - block + 1, block):
            window = grid[top : top + block, left : left + block]
            finite = window[np.isfinite(window)]
            if finite.size == 0:
                continue
            peak = float(finite.max())
            if peak < min_elevation:
                continue
            # A block whose peak barely stands above its own floor is a slope,
            # not a summit.
            if peak - float(finite.min()) < prominence:
                continue
            row, col = np.unravel_index(int(np.nanargmax(window)), window.shape)
            candidates.append((peak, top + int(row), left + int(col)))

    candidates.sort(reverse=True)
    features: list[dict[str, Any]] = []
    for peak, row, col in candidates[:limit]:
        lon, lat = to_lonlat(float(row), float(col))
        features.append(
            {
                "type": "Feature",
                "id": f"{provider_id}/summit/{len(features)}",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "name": f"{peak:.0f} m",
                    "elevation": peak,
                    "hipparchus_layer": SUMMIT_LAYER,
                    "hipparchus_source": provider_id,
                    "measured": True,
                },
            }
        )
    return features


def _polyline_length(polyline: list[tuple[float, float]]) -> float:
    return sum(
        math.hypot(next_row - row, next_col - col)
        for (row, col), (next_row, next_col) in zip(polyline, polyline[1:])
    )


def _default_http_get_bytes(url: str, timeout_seconds: float) -> bytes:
    from urllib.request import Request, urlopen

    request = Request(url, method="GET")
    request.add_header("User-Agent", "Hipparchus/0.3 (online map generator)")
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        return response.read()


__all__ = [
    "DEFAULT_TERRAIN_TILE_URL",
    "TERRAIN_TILES_PROVIDER_ID",
    "ELEVATION_BANDS_LAYER",
    "HILLSHADE_LAYER",
    "TerrainTileError",
    "TerrainTileSettings",
    "TerrainTileProvider",
    "terrain_tile_provider",
]
