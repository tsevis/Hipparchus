"""Tile and pixel arithmetic for elevation tiles: decoding, cropping, sampling, smoothing."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING, Callable

import numpy as np

from hipparchus.geometry.projection import EARTH_RADIUS_M, MAX_MERCATOR_LAT

if TYPE_CHECKING:
    from hipparchus.data_sources.terrain_tiles import TerrainTileSettings

TILE_PIXELS = 256
# The mosaic's own limit; asking beyond it returns nothing useful.
MAX_SOURCE_ZOOM = 15


class TerrainTileError(RuntimeError):
    """Raised when elevation tiles cannot be fetched or decoded."""


def _decode_terrarium(png_bytes: bytes) -> np.ndarray:
    """Unpack terrarium RGB into metres."""
    try:
        import skia  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise TerrainTileError(f"Decoding elevation tiles needs skia-python: {exc}") from exc

    image = skia.Image.MakeFromEncoded(skia.Data.MakeWithCopy(png_bytes))
    if image is None:
        raise TerrainTileError("Elevation tile is not a decodable image")
    # **The colour type is stated, not inherited.** `toarray()` defaults to
    # `kUnknown_ColorType`, which leaves skia free to hand back the image's own
    # native layout -- and `kN32` is BGRA on some platforms and RGBA on others.
    # The three lines below read channel 0 as red, so a platform that answers
    # BGRA decodes every elevation from the wrong byte: not an error, just a
    # terrain model of somewhere that does not exist. It is what made this
    # tile's round-trip test fail on every element under Linux CI while passing
    # on macOS. `gibs_provider._luminance_grid` says the same thing for the same
    # reason.
    pixels = np.asarray(
        image.toarray(colorType=skia.kRGBA_8888_ColorType), dtype=float
    )
    if pixels.ndim != 3 or pixels.shape[2] < 3:
        raise TerrainTileError(f"Unexpected elevation tile shape: {pixels.shape}")
    return pixels[:, :, 0] * 256.0 + pixels[:, :, 1] + pixels[:, :, 2] / 256.0 - 32768.0


def _choose_zoom(bounds: tuple[float, float, float, float], settings: TerrainTileSettings) -> int:
    """Highest zoom that samples the area finely without over-fetching tiles."""
    min_lon, min_lat, max_lon, max_lat = bounds
    lon_span = max(1e-9, abs(max_lon - min_lon))
    for zoom in range(min(settings.max_zoom, MAX_SOURCE_ZOOM), -1, -1):
        pixels_across = lon_span / 360.0 * (2**zoom) * TILE_PIXELS
        if pixels_across > settings.target_pixels:
            continue
        min_x, min_y = _tile_for(min_lon, max_lat, zoom)
        max_x, max_y = _tile_for(max_lon, min_lat, zoom)
        if (max_x - min_x + 1) * (max_y - min_y + 1) <= settings.max_tiles:
            return zoom
    return 0


def _tile_for(lon: float, lat: float, zoom: int) -> tuple[int, int]:
    n = 2**zoom
    lat = max(-85.05112878, min(85.05112878, lat))
    x = int((lon + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return (max(0, min(n - 1, x)), max(0, min(n - 1, y)))


def _pixel_for(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Global pixel coordinates, fractional."""
    world = (2**zoom) * TILE_PIXELS
    lat = max(-85.05112878, min(85.05112878, lat))
    x = (lon + 180.0) / 360.0 * world
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * world
    return (x, y)


def _lonlat_for_pixel(x: float, y: float, zoom: int) -> tuple[float, float]:
    world = (2**zoom) * TILE_PIXELS
    lon = x / world * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / world))))
    return (lon, lat)


def _row_latitudes(window: "_Window", zoom: int, rows: int) -> np.ndarray:
    """Each row's true latitude, vectorised -- `_lonlat_for_pixel`'s own
    formula, not linear interpolation across the grid's bounds.

    The grid is Web Mercator pixel space, so only its columns are evenly
    spaced in longitude; a blend that assumed rows were evenly spaced in
    latitude too would displace itself further from where it belongs the
    further north or south the frame sits -- the same distortion this file's
    own module docstring warns a contour tracer against.
    """
    world = (2**zoom) * TILE_PIXELS
    y = window.top + np.arange(rows, dtype=float) + 0.5
    return np.degrees(np.arctan(np.sinh(np.pi * (1.0 - 2.0 * y / world))))


def _column_longitudes(window: "_Window", zoom: int, columns: int) -> np.ndarray:
    """Each column's longitude, vectorised. Linear, unlike the rows: Mercator
    x *is* proportional to longitude, which is the one direction this grid
    does not need inverting."""
    world = (2**zoom) * TILE_PIXELS
    x = window.left + np.arange(columns, dtype=float) + 0.5
    return x / world * 360.0 - 180.0


@dataclass(slots=True, frozen=True)
class _Window:
    """Where the cropped grid sits in the mosaic's global pixel space."""

    left: int
    top: int
    width: int
    height: int


def _crop_to_bounds(
    mosaic: np.ndarray,
    origin: tuple[int, int],
    zoom: int,
    bounds: tuple[float, float, float, float],
) -> tuple[np.ndarray, _Window]:
    min_lon, min_lat, max_lon, max_lat = bounds
    origin_x = origin[0] * TILE_PIXELS
    origin_y = origin[1] * TILE_PIXELS

    left_global, top_global = _pixel_for(min_lon, max_lat, zoom)
    right_global, bottom_global = _pixel_for(max_lon, min_lat, zoom)

    left = max(0, int(math.floor(left_global - origin_x)))
    top = max(0, int(math.floor(top_global - origin_y)))
    right = min(mosaic.shape[1], int(math.ceil(right_global - origin_x)))
    bottom = min(mosaic.shape[0], int(math.ceil(bottom_global - origin_y)))
    if right - left < 2 or bottom - top < 2:
        return (np.empty((0, 0)), _Window(0, 0, 0, 0))

    grid = mosaic[top:bottom, left:right]
    window = _Window(left=origin_x + left, top=origin_y + top, width=grid.shape[1], height=grid.shape[0])
    return (grid, window)


def _lonlat_mapper(window: _Window, zoom: int) -> Callable[[float, float], tuple[float, float]]:
    def to_lonlat(row: float, col: float) -> tuple[float, float]:
        return _lonlat_for_pixel(window.left + col, window.top + row, zoom)

    return to_lonlat


def _lonlat_sampler(grid: np.ndarray, window: _Window, zoom: int) -> Callable[[float, float], float]:
    height, width = grid.shape

    def sample(lon: float, lat: float) -> float:
        x, y = _pixel_for(lon, lat, zoom)
        col = int(min(max(round(x - window.left), 0), width - 1))
        row = int(min(max(round(y - window.top), 0), height - 1))
        value = grid[row, col]
        return float(value) if math.isfinite(value) else float("nan")

    return sample


def _probe_step(window: _Window, zoom: int) -> float:
    """One pixel, expressed in degrees of longitude."""
    world = (2**zoom) * TILE_PIXELS
    return max(1e-12, 360.0 / world)


def _ground_resolution_metres(lat_degrees: float, zoom: int) -> float:
    """Metres a single tile pixel spans at this latitude and zoom.

    Web Mercator stretches east-west scale by ``1 / cos(latitude)`` to stay
    conformal, so a pixel near a pole covers less ground than one at the
    equator. Hillshade needs the real spacing to get slope right -- a fixed
    metres-per-pixel hardens the same mountain every time the zoom steps up.
    """
    world = (2**zoom) * TILE_PIXELS
    lat = max(-MAX_MERCATOR_LAT, min(MAX_MERCATOR_LAT, lat_degrees))
    return math.cos(math.radians(lat)) * (2.0 * math.pi * EARTH_RADIUS_M) / world


def _smooth(grid: np.ndarray, passes: int) -> np.ndarray:
    if passes <= 0 or grid.size == 0:
        return grid
    valid = np.isfinite(grid)
    filled = np.where(valid, grid, 0.0)
    weight = valid.astype(float)
    for _ in range(int(passes)):
        filled = _box_blur(filled)
        weight = _box_blur(weight)
    with np.errstate(divide="ignore", invalid="ignore"):
        blurred = np.where(weight > 0.0, filled / weight, np.nan)
    return np.where(valid, blurred, np.nan)


def _box_blur(values: np.ndarray) -> np.ndarray:
    padded = np.pad(values, 1, mode="edge")
    horizontal = (padded[:, :-2] + padded[:, 1:-1] + padded[:, 2:]) / 3.0
    return (horizontal[:-2, :] + horizontal[1:-1, :] + horizontal[2:, :]) / 3.0
