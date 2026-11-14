"""A simulated terrain field: procedural relief contoured as editable linework.

Every other rich source in Hipparchus reads data someone downloaded first. This
one generates it, so contour work is reachable on a bare install with no file,
no account, and no network. The field is deterministic in the seed and anchored
to geography rather than to the window: panning shows more of the same
landscape instead of re-rolling a new one, which is what makes the result usable
as a map rather than as wallpaper.

The elevations are **invented**. Everything this module emits is tagged
``synthetic`` so a generated map is never mistaken for measured ground.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
from typing import Any

import numpy as np

from hipparchus.data_sources.map_models import ProviderStatus
from hipparchus.data_sources.provider_layers import _collection_from_layers, _empty_layers
from hipparchus.data_sources.provider import BBoxQuery, FeatureCollection
from hipparchus.geometry.contours import (
    contour_levels,
    contour_polylines,
    orient_uphill_left,
    polyline_to_lonlat,
)


SIMULATED_PROVIDER_ID = "simulated_terrain"
SIMULATED_PROVIDER_LABEL = "Simulated Terrain (synthetic)"
SYNTHETIC_DETAIL = "Generated field - synthetic relief, not measured data"

MINOR_CONTOUR_LAYER = "terrain_contours"
INDEX_CONTOUR_LAYER = "terrain_index_contours"

# A slotted dataclass exposes no readable class-level defaults, so the seed
# default lives here where callers (and the launch settings) can reach it.
DEFAULT_TERRAIN_SEED = 1729

# Fixed offsets that decorrelate the warp fields from the base field. Constants
# rather than seed arithmetic so a seed always names the same landscape.
_WARP_OFFSET_X = (5.2, 1.3)
_WARP_OFFSET_Y = (9.7, 3.4)


@dataclass(slots=True, frozen=True)
class TerrainFieldSettings:
    """Shape of the generated landscape."""

    seed: int = DEFAULT_TERRAIN_SEED
    grid_size: int = 320
    relief_metres: float = 1200.0
    sea_level_metres: float = 0.0
    # Degrees spanned by the largest landform at the reference zoom. AOIs range
    # over two orders of magnitude, and a landform size that suits one end suits
    # neither the other: too large and every window is one flank of one hill,
    # drawn as parallel wood grain; too small and a wide window silts up into
    # undifferentiated mush. The working size is derived from the window (see
    # ``field_wavelength_deg``) and this is the anchor of that ladder.
    base_wavelength_deg: float = 0.3
    # Largest landform as a fraction of the window, before quantisation.
    landform_span_ratio: float = 1.2
    # Relief grows with landform size, near-linearly as real terrain does: a
    # 1 km-wide window with a kilometre of relief would be a cliff, not a hill.
    relief_exponent: float = 0.85
    # Ceiling on the octave ladder, not a fixed count -- how many are actually
    # summed depends on what the sampling grid can resolve.
    max_octaves: int = 12
    warp_octaves: int = 4
    # Octaves finer than this many grid cells are dropped: they cannot be
    # resolved, and summing them only adds speckle. Zooming in lowers the cell
    # size, so finer detail appears the way it does on a real DEM.
    min_cells_per_feature: float = 8.0
    lacunarity: float = 2.0
    gain: float = 0.42
    warp_strength: float = 0.45
    ridge_weight: float = 0.45
    # Slope contrast. Above 1 the low ground flattens and the high ground
    # steepens, which is what opens empty basins next to dense faces -- the
    # density contrast a printed relief sheet reads as depth.
    shaping_exponent: float = 2.4
    # 0.0 means "choose a round interval that keeps the window readable".
    contour_interval_metres: float = 0.0
    index_every: int = 5
    target_line_count: int = 44
    # Where the field is steep, contours crowd closer than the sampling grid can
    # resolve and break into sub-cell specks. Measured in grid cells.
    min_contour_length_cells: float = 3.0


# The dense hairline sheet: hundreds of levels on a fine grid, no accented
# lines, so depth is carried entirely by how tightly the lines crowd. Costs a
# few seconds per fetch rather than a few hundred milliseconds, which is the
# trade for a sheet meant to be printed rather than panned around.
DENSE_RELIEF_SETTINGS = TerrainFieldSettings(
    grid_size=512,
    target_line_count=160,
    index_every=0,
)


def nice_interval(value_range: float, *, target_lines: int = 44) -> float:
    """Round ``value_range / target_lines`` to the nearest 1/2/5 x 10^n step.

    Contour intervals are read off a map, so they have to be numbers a person
    would write down: 5 m, 20 m, 100 m. Never 23.7 m.
    """
    if not math.isfinite(value_range) or value_range <= 0.0 or target_lines <= 0:
        return 1.0
    raw = value_range / target_lines
    exponent = math.floor(math.log10(raw))
    candidates = [step * (10.0**exponent) for step in (1.0, 2.0, 5.0, 10.0)]
    return min(candidates, key=lambda candidate: abs(math.log(candidate / raw)))


def window_span_deg(bounds: tuple[float, float, float, float]) -> float:
    """Shorter side of the window in degrees, corrected for latitude."""
    min_lon, min_lat, max_lon, max_lat = bounds
    mean_lat = max(-89.9, min(89.9, (min_lat + max_lat) / 2.0))
    lon_span = abs(max_lon - min_lon) * math.cos(math.radians(mean_lat))
    lat_span = abs(max_lat - min_lat)
    spans = [span for span in (lon_span, lat_span) if span > 0.0]
    return min(spans) if spans else 0.0


def field_wavelength_deg(
    bounds: tuple[float, float, float, float],
    *,
    settings: TerrainFieldSettings | None = None,
) -> float:
    """Size of the largest landform for this window, on a power-of-two ladder.

    Quantising rather than tracking the window exactly is what keeps the result
    usable: the wavelength depends only on how wide the window is, never on
    where it is, so panning at one zoom walks across one continuous landscape.
    Nudging the AOI's size by a few percent lands on the same rung and changes
    nothing. Zooming far enough crosses a rung, and the landscape rescales --
    which is the deliberate trade for every zoom looking like terrain.
    """
    settings = settings or TerrainFieldSettings()
    anchor = max(1e-6, settings.base_wavelength_deg)
    span = window_span_deg(bounds)
    if span <= 0.0:
        return anchor
    target = span * max(1e-6, settings.landform_span_ratio)
    return anchor * (2.0 ** round(math.log2(target / anchor)))


def relief_metres_for_window(
    bounds: tuple[float, float, float, float],
    *,
    settings: TerrainFieldSettings | None = None,
) -> float:
    """Full relief of the landform this window is looking at.

    ``relief_metres`` is the relief at the reference landform size, not a global
    ceiling: bigger landforms carry more relief, near-linearly, as real ones do.
    """
    settings = settings or TerrainFieldSettings()
    anchor = max(1e-6, settings.base_wavelength_deg)
    wavelength = field_wavelength_deg(bounds, settings=settings)
    return settings.relief_metres * (wavelength / anchor) ** settings.relief_exponent


def resolvable_octaves(
    bounds: tuple[float, float, float, float],
    *,
    settings: TerrainFieldSettings | None = None,
) -> int:
    """How many octaves this window's sampling grid can actually carry.

    Band-limiting to the grid keeps a wide window from summing detail it has no
    pixels to draw, which would only arrive as speckle. Amplitudes stay absolute
    (see ``_fbm``), so dropping an octave removes detail rather than rescaling
    what remains.
    """
    settings = settings or TerrainFieldSettings()
    span = window_span_deg(bounds)
    if span <= 0.0:
        return max(1, settings.max_octaves)

    cell_deg = span / (max(2, int(settings.grid_size)) - 1)
    finest_deg = max(1e-9, settings.min_cells_per_feature * cell_deg)
    wavelength = field_wavelength_deg(bounds, settings=settings)
    lacunarity = max(1.0001, settings.lacunarity)

    octaves = 1
    while octaves < settings.max_octaves and wavelength / (lacunarity**octaves) >= finest_deg:
        octaves += 1
    return octaves


def elevation_grid(
    bounds: tuple[float, float, float, float],
    *,
    settings: TerrainFieldSettings | None = None,
) -> np.ndarray:
    """Sample the synthetic elevation field over ``(min_lon, min_lat, max_lon, max_lat)``.

    Row 0 is the north edge. The returned metres are a pure function of the
    sampled coordinates and the seed -- no per-window normalisation, which is
    what keeps neighbouring windows continuous with each other.
    """
    settings = settings or TerrainFieldSettings()
    min_lon, min_lat, max_lon, max_lat = bounds
    size = max(2, int(settings.grid_size))

    lons = np.linspace(min_lon, max_lon, size)
    lats = np.linspace(max_lat, min_lat, size)
    lon_grid, lat_grid = np.meshgrid(lons, lats)

    # Sinusoidal-equal-area-style coordinates: one (lon, lat) always maps to one
    # noise coordinate, worldwide, and features do not stretch towards the poles.
    wavelength = field_wavelength_deg(bounds, settings=settings)
    x = lon_grid * np.cos(np.radians(lat_grid)) / wavelength
    y = lat_grid / wavelength

    octaves = resolvable_octaves(bounds, settings=settings)
    warp_octaves = min(settings.warp_octaves, octaves)
    warp_x = _fbm(x + _WARP_OFFSET_X[0], y + _WARP_OFFSET_X[1], settings, octaves=warp_octaves, salt=101)
    warp_y = _fbm(x + _WARP_OFFSET_Y[0], y + _WARP_OFFSET_Y[1], settings, octaves=warp_octaves, salt=211)
    strength = settings.warp_strength
    warped_x = x + strength * (2.0 * warp_x - 1.0)
    warped_y = y + strength * (2.0 * warp_y - 1.0)

    base = _fbm(warped_x, warped_y, settings, octaves=octaves, salt=0)
    # Ridged noise carves the valley/crest structure that makes contour spacing
    # read as slope; plain fBm alone gives soft, undifferentiated blobs.
    ridged = 1.0 - np.abs(2.0 * base - 1.0)
    shaped = (1.0 - settings.ridge_weight) * base + settings.ridge_weight * ridged**1.5
    shaped = np.clip(shaped, 0.0, 1.0) ** settings.shaping_exponent
    return shaped * relief_metres_for_window(bounds, settings=settings) - settings.sea_level_metres


@dataclass(slots=True)
class SimulatedFieldProvider:
    """Provider that generates its own field instead of reading one."""

    settings: TerrainFieldSettings = field(default_factory=TerrainFieldSettings)
    provider_id: str = SIMULATED_PROVIDER_ID
    label: str = SIMULATED_PROVIDER_LABEL
    # Accepted so the manager and the UI can treat every optional provider
    # alike. Nothing is read from it.
    source_path: Path | None = None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            label=self.label,
            available=True,
            detail=SYNTHETIC_DETAIL,
        )

    def fetch_bbox(self, query: BBoxQuery) -> FeatureCollection:
        bounds = (query.min_lon, query.min_lat, query.max_lon, query.max_lat)
        grid = elevation_grid(bounds, settings=self.settings)
        lowest = float(np.nanmin(grid))
        highest = float(np.nanmax(grid))

        interval = self.settings.contour_interval_metres
        if interval <= 0.0:
            # Auto: a fixed metre interval empties a small window and floods a
            # large one, so the interval follows the relief actually in view.
            interval = nice_interval(highest - lowest, target_lines=self.settings.target_line_count)
        levels = contour_levels(lowest, highest, interval=interval, index_every=self.settings.index_every)

        sample = _lonlat_sampler(grid, bounds)
        probe = _probe_step(grid, bounds)

        features_by_layer = _empty_layers()
        for layer, layer_levels in (
            (MINOR_CONTOUR_LAYER, levels.minor),
            (INDEX_CONTOUR_LAYER, levels.index),
        ):
            for level in layer_levels:
                for polyline in contour_polylines(grid, level):
                    if _polyline_length(polyline) < self.settings.min_contour_length_cells:
                        continue
                    coordinates = polyline_to_lonlat(polyline, bounds=bounds, shape=grid.shape)
                    if len(coordinates) < 2:
                        continue
                    # Wind every contour with the high ground on its left. That
                    # is what lets the renderer light the sheet without having
                    # to carry the field alongside the geometry.
                    coordinates = orient_uphill_left(coordinates, sample=sample, level=level, probe=probe)
                    features_by_layer[layer].append(
                        _contour_feature(
                            layer=layer,
                            index=len(features_by_layer[layer]),
                            level=level,
                            interval=interval,
                            coordinates=coordinates,
                        )
                    )

        return _collection_from_layers(
            features_by_layer,
            metadata={
                "source": self.provider_id,
                "format": "synthetic",
                "synthetic": True,
                "seed": self.settings.seed,
                "contour_interval_metres": interval,
                "index_every": self.settings.index_every,
                "elevation_min_metres": lowest,
                "elevation_max_metres": highest,
                "grid_size": int(self.settings.grid_size),
            },
            bbox=bounds,
        )


def simulated_terrain_provider(settings: TerrainFieldSettings | None = None) -> SimulatedFieldProvider:
    return SimulatedFieldProvider(settings=settings or TerrainFieldSettings())


def _contour_feature(
    *,
    layer: str,
    index: int,
    level: float,
    interval: float,
    coordinates: list[tuple[float, float]],
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": f"{SIMULATED_PROVIDER_ID}/{layer}/{level:.3f}/{index}",
        "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lon, lat in coordinates]},
        "properties": {
            "elevation": float(level),
            "contour_interval": float(interval),
            "index_contour": layer == INDEX_CONTOUR_LAYER,
            "hipparchus_layer": layer,
            "hipparchus_source": SIMULATED_PROVIDER_ID,
            "synthetic": True,
        },
    }


def _lonlat_sampler(grid: np.ndarray, bounds: tuple[float, float, float, float]):
    """Bilinear read of the field at a (lon, lat), for side-of-the-line tests."""
    min_lon, min_lat, max_lon, max_lat = bounds
    height, width = grid.shape
    lon_span = max_lon - min_lon
    lat_span = max_lat - min_lat

    def sample(lon: float, lat: float) -> float:
        col = (lon - min_lon) / lon_span * (width - 1) if lon_span else 0.0
        row = (max_lat - lat) / lat_span * (height - 1) if lat_span else 0.0
        col = min(max(col, 0.0), width - 1.0)
        row = min(max(row, 0.0), height - 1.0)
        col0, row0 = int(col), int(row)
        col1 = min(col0 + 1, width - 1)
        row1 = min(row0 + 1, height - 1)
        fx, fy = col - col0, row - row0
        top = grid[row0, col0] * (1.0 - fx) + grid[row0, col1] * fx
        bottom = grid[row1, col0] * (1.0 - fx) + grid[row1, col1] * fx
        return float(top * (1.0 - fy) + bottom * fy)

    return sample


def _probe_step(grid: np.ndarray, bounds: tuple[float, float, float, float]) -> float:
    """Half a grid cell, in degrees -- far enough to leave the contour, close
    enough to stay on the same slope."""
    min_lon, min_lat, max_lon, max_lat = bounds
    height, width = grid.shape
    lon_step = abs(max_lon - min_lon) / max(1, width - 1)
    lat_step = abs(max_lat - min_lat) / max(1, height - 1)
    return max(1e-12, min(lon_step, lat_step) * 0.5)


def _polyline_length(polyline: list[tuple[float, float]]) -> float:
    """Path length in grid cells."""
    return sum(
        math.hypot(next_row - row, next_col - col)
        for (row, col), (next_row, next_col) in zip(polyline, polyline[1:])
    )


def _fbm(
    x: np.ndarray,
    y: np.ndarray,
    settings: TerrainFieldSettings,
    *,
    octaves: int,
    salt: int,
) -> np.ndarray:
    """Fractal sum of value noise, normalised to [0, 1].

    The normaliser covers the whole octave ladder, not just the octaves summed
    here. Normalising by the octaves actually used would rescale the field every
    time the window changed how many are resolvable -- zooming in would inflate
    small ripples into mountains instead of revealing them.
    """
    total = np.zeros_like(x, dtype=float)
    amplitude = 1.0
    frequency = 1.0
    for octave in range(max(1, int(octaves))):
        total += amplitude * _value_noise(x * frequency, y * frequency, settings.seed + salt + octave * 7919)
        amplitude *= settings.gain
        frequency *= settings.lacunarity

    normaliser = sum(settings.gain**octave for octave in range(max(1, settings.max_octaves)))
    return total / normaliser if normaliser else total


def _value_noise(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    """Lattice value noise with quintic interpolation, in [0, 1]."""
    x0 = np.floor(x)
    y0 = np.floor(y)
    fx = _quintic(x - x0)
    fy = _quintic(y - y0)
    ix = x0.astype(np.int64)
    iy = y0.astype(np.int64)

    c00 = _hash_unit(ix, iy, seed)
    c10 = _hash_unit(ix + 1, iy, seed)
    c01 = _hash_unit(ix, iy + 1, seed)
    c11 = _hash_unit(ix + 1, iy + 1, seed)

    top = c00 + (c10 - c00) * fx
    bottom = c01 + (c11 - c01) * fx
    return top + (bottom - top) * fy


def _quintic(t: np.ndarray) -> np.ndarray:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _hash_unit(ix: np.ndarray, iy: np.ndarray, seed: int) -> np.ndarray:
    """Deterministic [0, 1) value per integer lattice point.

    An integer hash rather than a seeded RNG array: the value at a lattice point
    must depend only on that point and the seed, so that a window sampled
    anywhere agrees with its neighbours.
    """
    x = ix.astype(np.uint64)
    y = iy.astype(np.uint64)
    key = np.uint64(seed) & np.uint64(0xFFFFFFFFFFFFFFFF)
    with np.errstate(over="ignore"):
        h = x * np.uint64(0x9E3779B97F4A7C15)
        h ^= y * np.uint64(0xC2B2AE3D27D4EB4F)
        h ^= key * np.uint64(0x165667B19E3779F9)
        h ^= h >> np.uint64(30)
        h *= np.uint64(0xBF58476D1CE4E5B9)
        h ^= h >> np.uint64(27)
        h *= np.uint64(0x94D049BB133111EB)
        h ^= h >> np.uint64(31)
    return (h >> np.uint64(11)).astype(np.float64) / float(1 << 53)
