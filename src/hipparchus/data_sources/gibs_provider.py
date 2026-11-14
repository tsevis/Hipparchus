"""Satellite imagery from NASA GIBS, contoured into vector iso-lines.

Turns the night-lights model from "download a GeoTIFF first" into a live one:
GIBS serves NASA's imagery over open WMS with no account and no key, so any AOI
can be asked for its own nighttime illumination and get back editable contours.

**What the numbers mean.** GIBS returns a *rendered* image, not a calibrated
product, so the contoured quantity is picture brightness -- not radiance in
nW/cm2/sr. It is faithful about where a place is lit and how that compares with
its neighbours; it is not a measurement, and it saturates over city cores, where
the render clips to white and a bright centre can come back with no contours at
all. For calibrated work the file-based `Night Lights (VIIRS)` model still takes
a single-band VNP46A or VNL GeoTIFF.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from pathlib import Path
import time
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np

from hipparchus.data_sources.map_models import ProviderStatus
from hipparchus.data_sources.provider_layers import _collection_from_layers, _empty_layers
from hipparchus.data_sources.provider import BBoxQuery, FeatureCollection
from hipparchus.geometry.contours import (
    contour_polylines,
    orient_uphill_left,
    polyline_to_lonlat,
)


GIBS_PROVIDER_ID = "gibs_imagery"
GIBS_PROVIDER_LABEL = "Night Lights Online (GIBS)"
DEFAULT_GIBS_ENDPOINT = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
DEFAULT_GIBS_LAYER = "VIIRS_Black_Marble"
NIGHT_LIGHTS_LAYER = "night_lights"

# Rec. 709 luminance weights: the render is greyscale-ish already, but a
# weighted sum keeps coloured overlays from reading as brightness.
_LUMA = (0.2126, 0.7152, 0.0722)

HttpGetBytes = Callable[[str, float], bytes]


class SatelliteImageryError(RuntimeError):
    """Raised when GIBS cannot be reached, or returns something undecodable."""


@dataclass(slots=True, frozen=True)
class SatelliteImagerySettings:
    """Which GIBS layer to sample, and how finely."""

    endpoint: str = DEFAULT_GIBS_ENDPOINT
    layer: str = DEFAULT_GIBS_LAYER
    # Empty asks GIBS for its default epoch, which is what a static composite
    # such as Black Marble wants.
    date: str = ""
    max_pixels: int = 1024
    timeout_seconds: float = 45.0
    # GIBS answers a repeated request fine after returning 500 on the first,
    # observed in testing, so one failure must not end the fetch.
    max_attempts: int = 3
    retry_delay_seconds: float = 1.0
    levels: int = 14
    min_contour_length_cells: float = 3.0
    # GIBS upsamples its imagery to whatever size is asked for, so the returned
    # PNG carries large blocks of one value and raw contours staircase along the
    # source pixel edges. A couple of box-blur passes restore smooth iso-lines
    # without inventing detail the imagery does not have.
    smoothing_passes: int = 2
    output_layer: str = NIGHT_LIGHTS_LAYER
    value_key: str = "brightness"


@dataclass(slots=True)
class GIBSImageryProvider:
    """Fetches a GIBS image for the AOI and contours its brightness."""

    settings: SatelliteImagerySettings = field(default_factory=SatelliteImagerySettings)
    http_get: HttpGetBytes | None = None
    provider_id: str = GIBS_PROVIDER_ID
    label: str = GIBS_PROVIDER_LABEL
    # Accepted so every optional provider configures alike; unused.
    source_path: Path | None = None

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            provider_id=self.provider_id,
            label=self.label,
            available=True,
            detail=f"Live NASA GIBS WMS, layer {self.settings.layer} - rendered brightness, not calibrated radiance",
        )

    def fetch_bbox(self, query: BBoxQuery) -> FeatureCollection:
        bounds = (query.min_lon, query.min_lat, query.max_lon, query.max_lat)
        width, height = _image_size(bounds, self.settings.max_pixels)
        payload = self._request(bounds, width, height)
        grid = _smooth_grid(_luminance_grid(payload), self.settings.smoothing_passes)

        finite = grid[np.isfinite(grid)]
        lowest = float(finite.min()) if finite.size else 0.0
        highest = float(finite.max()) if finite.size else 0.0
        distinct = int(np.unique(finite).size) if finite.size else 0

        features: list[dict[str, Any]] = []
        levels = _levels_between(lowest, highest, self.settings.levels)
        if levels:
            sample = _grid_sampler(grid, bounds)
            probe = _probe_step(grid, bounds)
            for level in levels:
                for polyline in contour_polylines(grid, level):
                    if _polyline_length(polyline) < self.settings.min_contour_length_cells:
                        continue
                    coordinates = polyline_to_lonlat(polyline, bounds=bounds, shape=grid.shape)
                    if len(coordinates) < 2:
                        continue
                    coordinates = orient_uphill_left(coordinates, sample=sample, level=level, probe=probe)
                    features.append(
                        {
                            "type": "Feature",
                            "id": f"{self.provider_id}/{self.settings.output_layer}/{level:.2f}/{len(features)}",
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[lon, lat] for lon, lat in coordinates],
                            },
                            "properties": {
                                self.settings.value_key: float(level),
                                "gibs_layer": self.settings.layer,
                                "hipparchus_layer": self.settings.output_layer,
                                "hipparchus_source": self.provider_id,
                                # The single most important caveat, carried on
                                # the data itself rather than left in the docs.
                                "calibrated": False,
                            },
                        }
                    )

        features_by_layer = _empty_layers()
        features_by_layer[self.settings.output_layer] = features

        return _collection_from_layers(
            features_by_layer,
            metadata={
                "source": self.provider_id,
                "format": "gibs_wms_png",
                "gibs_layer": self.settings.layer,
                "calibrated": False,
                "image_size": [width, height],
                "brightness_min": lowest,
                "brightness_max": highest,
                "distinct_values": distinct,
                # A window that clips to white has nothing left to contour --
                # exactly what happens over a bright city core.
                "saturated": distinct < 3,
            },
            bbox=bounds,
        )

    def _request(self, bounds: tuple[float, float, float, float], width: int, height: int) -> bytes:
        min_lon, min_lat, max_lon, max_lat = bounds
        parameters = {
            "SERVICE": "WMS",
            "REQUEST": "GetMap",
            "VERSION": "1.3.0",
            "LAYERS": self.settings.layer,
            "CRS": "EPSG:4326",
            # WMS 1.3.0 orders EPSG:4326 as latitude, longitude. Getting this
            # backwards silently returns imagery of somewhere else entirely.
            "BBOX": f"{min_lat},{min_lon},{max_lat},{max_lon}",
            "WIDTH": str(width),
            "HEIGHT": str(height),
            "FORMAT": "image/png",
        }
        if self.settings.date:
            parameters["TIME"] = self.settings.date
        url = f"{self.settings.endpoint}?{urlencode(parameters)}"
        getter = self.http_get or _default_http_get_bytes
        attempts = max(1, int(self.settings.max_attempts))
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                return getter(url, self.settings.timeout_seconds)
            except Exception as exc:  # noqa: BLE001 - retried, then surfaced as provider status
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(self.settings.retry_delay_seconds * (attempt + 1))
        raise SatelliteImageryError(
            f"GIBS request failed after {attempts} attempts: {last_error}"
        ) from last_error


def gibs_imagery_provider(
    settings: SatelliteImagerySettings | None = None,
    http_get: HttpGetBytes | None = None,
) -> GIBSImageryProvider:
    return GIBSImageryProvider(settings=settings or SatelliteImagerySettings(), http_get=http_get)


def _image_size(bounds: tuple[float, float, float, float], max_pixels: int) -> tuple[int, int]:
    """Pixel size matching the AOI's aspect, capped on the long side."""
    min_lon, min_lat, max_lon, max_lat = bounds
    lon_span = abs(max_lon - min_lon)
    lat_span = abs(max_lat - min_lat)
    if lon_span <= 0.0 or lat_span <= 0.0:
        return (max_pixels, max_pixels)
    if lon_span >= lat_span:
        width = max_pixels
        height = max(2, int(round(max_pixels * lat_span / lon_span)))
    else:
        height = max_pixels
        width = max(2, int(round(max_pixels * lon_span / lat_span)))
    return (width, height)


def _luminance_grid(png_bytes: bytes) -> np.ndarray:
    """Decode a PNG into a float luminance grid, row 0 at the north edge."""
    try:
        import skia  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise SatelliteImageryError(f"Decoding GIBS imagery needs skia-python: {exc}") from exc

    image = skia.Image.MakeFromEncoded(skia.Data.MakeWithCopy(png_bytes))
    if image is None:
        raise SatelliteImageryError("GIBS returned a response that is not a decodable image")
    # Stated rather than inherited, as in `terrain_tiles._decode_terrarium`:
    # `toarray()` defaults to `kUnknown_ColorType` and skia may then answer in
    # the platform's native layout, which is BGRA on some. The luma weights
    # below are Rec. 601 and are not symmetric -- red carries 0.299 and blue
    # 0.114 -- so a swapped pair does not fail, it just makes the wrong picture
    # dark in the wrong places.
    pixels = np.asarray(
        image.toarray(colorType=skia.kRGBA_8888_ColorType), dtype=float
    )
    if pixels.ndim != 3 or pixels.shape[2] < 3:
        raise SatelliteImageryError(f"Unexpected image shape from GIBS: {pixels.shape}")

    luminance = pixels[:, :, 0] * _LUMA[0] + pixels[:, :, 1] * _LUMA[1] + pixels[:, :, 2] * _LUMA[2]
    if pixels.shape[2] >= 4:
        # Transparent pixels are "no data", not "black ground".
        luminance = np.where(pixels[:, :, 3] > 0, luminance, np.nan)
    return luminance


def _smooth_grid(grid: np.ndarray, passes: int) -> np.ndarray:
    """Box-blur the field, preserving non-finite gaps as gaps."""
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
    """3x3 mean with edge replication, in two separable passes."""
    padded = np.pad(values, 1, mode="edge")
    horizontal = (padded[:, :-2] + padded[:, 1:-1] + padded[:, 2:]) / 3.0
    return (horizontal[:-2, :] + horizontal[1:-1, :] + horizontal[2:, :]) / 3.0


def _levels_between(lowest: float, highest: float, count: int) -> list[float]:
    """Equal steps across the observed brightness.

    Brightness has no units, so a fixed interval would mean nothing; splitting
    the observed range keeps the same number of lines whatever the window holds.
    """
    if not math.isfinite(lowest) or not math.isfinite(highest) or highest <= lowest:
        return []
    step = (highest - lowest) / (max(1, count) + 1)
    return [lowest + step * index for index in range(1, max(1, count) + 1)]


def _grid_sampler(grid: np.ndarray, bounds: tuple[float, float, float, float]):
    min_lon, min_lat, max_lon, max_lat = bounds
    height, width = grid.shape
    lon_span = max_lon - min_lon
    lat_span = max_lat - min_lat

    def sample(lon: float, lat: float) -> float:
        col = (lon - min_lon) / lon_span * (width - 1) if lon_span else 0.0
        row = (max_lat - lat) / lat_span * (height - 1) if lat_span else 0.0
        col = int(min(max(round(col), 0), width - 1))
        row = int(min(max(round(row), 0), height - 1))
        return float(grid[row, col])

    return sample


def _probe_step(grid: np.ndarray, bounds: tuple[float, float, float, float]) -> float:
    min_lon, min_lat, max_lon, max_lat = bounds
    height, width = grid.shape
    lon_step = abs(max_lon - min_lon) / max(1, width - 1)
    lat_step = abs(max_lat - min_lat) / max(1, height - 1)
    return max(1e-12, min(lon_step, lat_step) * 0.75)


def _polyline_length(polyline: list[tuple[float, float]]) -> float:
    return sum(
        math.hypot(next_row - row, next_col - col)
        for (row, col), (next_row, next_col) in zip(polyline, polyline[1:])
    )


def _default_http_get_bytes(url: str, timeout_seconds: float) -> bytes:
    request = Request(url, method="GET")
    request.add_header("User-Agent", "Hipparchus/0.3 (online map generator)")
    with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
        return response.read()
