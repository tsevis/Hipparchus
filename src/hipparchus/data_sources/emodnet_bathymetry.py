"""EMODnet bathymetry: fetching the surveyed sea floor and saying how much of a depth is measured."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hipparchus.geometry.bands import DepthBandMode, ElevationBand

if TYPE_CHECKING:
    from hipparchus.data_sources.terrain_tiles import HttpGetBytes, TerrainTileSettings

#: EMODnet Bathymetry's own coverage extent (its GetCapabilities), confirmed
#: live 2026-08-03. A query outside it returns nothing useful, so a frame
#: entirely outside it should cost no round trip at all.
EMODNET_COVERAGE_EXTENT: tuple[float, float, float, float] = (-70.5, 11.0, 43.0, 90.0)
DEFAULT_EMODNET_ENDPOINT = "https://ows.emodnet-bathymetry.eu/wcs"
DEFAULT_EMODNET_COVERAGE = "emodnet:mean"
#: How much wider than the frame to request. The feather has to fall outside
#: the drawing: it ramps from the edge of whatever coverage comes back, and a
#: frame sitting entirely inside EMODnet's coverage has nothing genuine to
#: feather against if the request was only ever the frame itself -- a real
#: area once measured 89% surveyed against a true figure of 100% for exactly
#: this reason.
EMODNET_REQUEST_MARGIN = 0.09


# -- EMODnet: a finer sea floor, where one exists -----------------------------


def _emodnet_covers(bounds: tuple[float, float, float, float]) -> bool:
    """Whether it is worth asking EMODnet at all.

    A frame entirely outside European waters gets nothing, and this is how it
    costs nothing rather than a round trip and a parse failure.
    """
    min_lon, min_lat, max_lon, max_lat = bounds
    cov_min_lon, cov_min_lat, cov_max_lon, cov_max_lat = EMODNET_COVERAGE_EXTENT
    return max_lon > cov_min_lon and min_lon < cov_max_lon and max_lat > cov_min_lat and min_lat < cov_max_lat


def _emodnet_widened_bounds(
    bounds: tuple[float, float, float, float], margin: float
) -> tuple[float, float, float, float]:
    """The frame plus the margin the feather needs, clamped to the service's
    own extent -- asking outside it returns a complaint rather than a
    coverage."""
    min_lon, min_lat, max_lon, max_lat = bounds
    lon_margin = (max_lon - min_lon) * margin
    lat_margin = (max_lat - min_lat) * margin
    cov_min_lon, cov_min_lat, cov_max_lon, cov_max_lat = EMODNET_COVERAGE_EXTENT
    return (
        max(cov_min_lon, min_lon - lon_margin),
        max(cov_min_lat, min_lat - lat_margin),
        min(cov_max_lon, max_lon + lon_margin),
        min(cov_max_lat, max_lat + lat_margin),
    )


def _emodnet_url(
    bounds: tuple[float, float, float, float], width: int, height: int, settings: TerrainTileSettings
) -> str:
    min_lon, min_lat, max_lon, max_lat = bounds
    return (
        f"{settings.emodnet_endpoint}?service=WCS&version=1.0.0&request=GetCoverage"
        f"&coverage={settings.emodnet_coverage}&crs=EPSG:4326"
        # WCS 1.0.0 states a bbox as minx,miny,maxx,maxy -- longitude first,
        # the opposite of the Overpass convention elsewhere in this codebase.
        f"&bbox={min_lon},{min_lat},{max_lon},{max_lat}"
        f"&width={width}&height={height}&format=GeoTIFF"
    )


def _fetch_emodnet_grid(
    bounds: tuple[float, float, float, float],
    rows: int,
    columns: int,
    settings: TerrainTileSettings,
    http_get: HttpGetBytes,
) -> tuple[np.ndarray, tuple[float, float, float, float]] | None:
    """The EMODnet coverage over an area, at roughly the given grid size.

    Returns ``None`` rather than raising when the service declines, cannot be
    reached, or answers with something unreadable: this is an *improvement*
    to a map that already works, and a sheet is better drawn from the global
    mosaic than not drawn at all.
    """
    if not _emodnet_covers(bounds):
        return None
    wide_bounds = _emodnet_widened_bounds(bounds, EMODNET_REQUEST_MARGIN)
    width = max(2, min(columns, settings.emodnet_max_pixels))
    height = max(2, min(rows, settings.emodnet_max_pixels))
    url = _emodnet_url(wide_bounds, width, height, settings)

    attempts = max(1, int(settings.emodnet_max_attempts))
    for attempt in range(attempts):
        try:
            data = http_get(url, settings.emodnet_timeout_seconds)
        except Exception:  # noqa: BLE001 - an unreachable service is a hole, not a failure
            if attempt + 1 < attempts:
                continue
            return None
        # A WCS reports a bad request as an XML document with a 200, so the
        # first two bytes decide whether this is a coverage or a complaint.
        if len(data) < 8 or data[:2] not in (b"II", b"MM"):
            return None
        try:
            return _read_emodnet_tiff(data)
        except Exception:  # noqa: BLE001 - an unreadable response is a hole, not a failure
            return None
    return None


def _read_emodnet_tiff(data: bytes) -> tuple[np.ndarray, tuple[float, float, float, float]] | None:
    """Read a GeoTIFF depth grid, using rasterio rather than a hand-written
    parser -- unlike the Swift sibling this was ported from, this codebase
    already declares the dependency that reads arbitrary GeoTIFF for free."""
    try:
        from rasterio.io import MemoryFile
    except ImportError:
        return None
    with MemoryFile(data) as memfile, memfile.open() as dataset:
        values = dataset.read(1).astype(float)
        nodata = dataset.nodata
        if nodata is not None:
            values = np.where(np.isclose(values, nodata, atol=1e-6), np.nan, values)
        # Beyond the deepest trench and the highest summit by a wide margin.
        # Services differ about their sentinel and some state none at all.
        values = np.where((values > -12_000.0) & (values < 9_500.0), values, np.nan)
        left, bottom, right, top = dataset.bounds
    return values, (left, bottom, right, top)


def _blend_sea_floor(
    base: np.ndarray,
    row_lats: np.ndarray,
    col_lons: np.ndarray,
    finer: np.ndarray,
    finer_bounds: tuple[float, float, float, float],
    *,
    feather_fraction: float,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Put a finer sea floor under a coarser one, without a seam.

    The two grids are the same ground at different resolutions and rarely the
    same size, so the finer one is sampled at each of the coarser one's cells
    rather than either being resampled wholesale.

    Three rules, and each is there because of a way this goes wrong:

    - **Sea only.** EMODnet carries land too, and coarser land than SRTM's --
      the guard is on the *base* grid's own sign, not the finer one's, or a
      coastline where the two disagree would drag the sea up the beach.
    - **Only where it has something to say.** A hole in the finer coverage
      keeps whatever was in the base grid, rather than punching a hole in it.
    - **Feathered at the edge of coverage.** A hard switch between two grids
      that disagree by a few metres draws a straight line across open water,
      and a straight line on a bathymetric sheet reads as a fault or a survey
      track -- which is to say, as data. The blend ramps over a margin.
    """
    if base.size == 0 or finer.size == 0:
        return base, np.zeros_like(base, dtype=float), 0

    f_min_lon, f_min_lat, f_max_lon, f_max_lat = finer_bounds
    lon_span = f_max_lon - f_min_lon
    lat_span = f_max_lat - f_min_lat
    if lon_span <= 0.0 or lat_span <= 0.0:
        return base, np.zeros_like(base, dtype=float), 0

    finer_rows, finer_cols = finer.shape
    lat_grid, lon_grid = np.meshgrid(row_lats, col_lons, indexing="ij")

    inside_bounds = (
        (lon_grid >= f_min_lon) & (lon_grid <= f_max_lon) & (lat_grid >= f_min_lat) & (lat_grid <= f_max_lat)
    )
    # Fractional position in the finer grid's own regular lat/lon index space
    # -- row 0 is north, matching this file's convention throughout.
    sample_x = (lon_grid - f_min_lon) / lon_span * finer_cols
    sample_y = (f_max_lat - lat_grid) / lat_span * finer_rows
    sample_col = np.clip(sample_x.astype(int), 0, finer_cols - 1)
    sample_row = np.clip(sample_y.astype(int), 0, finer_rows - 1)
    depth = np.where(inside_bounds, finer[sample_row, sample_col], np.nan)

    has_depth = np.isfinite(depth) & (depth < 0.0)
    is_hole = ~np.isfinite(base)
    is_sea = np.isfinite(base) & (base < 0.0)

    feather = max(1e-9, min(lon_span, lat_span) * max(0.0, feather_fraction))
    inside_distance = np.minimum(
        np.minimum(lon_grid - f_min_lon, f_max_lon - lon_grid),
        np.minimum(lat_grid - f_min_lat, f_max_lat - lat_grid),
    )
    weight = np.clip(inside_distance / feather, 0.0, 1.0)

    values = base.copy()
    surveyed = np.zeros_like(base, dtype=float)

    # Nothing to disagree with: a hole in the mosaic is filled outright,
    # because something is better than nothing.
    fill_mask = has_depth & is_hole
    values = np.where(fill_mask, depth, values)
    surveyed = np.where(fill_mask, 1.0, surveyed)

    blend_mask = has_depth & is_sea & (weight > 0.0)
    values = np.where(blend_mask, base + (depth - base) * weight, values)
    surveyed = np.where(blend_mask, weight, surveyed)

    replaced = int(np.count_nonzero(fill_mask | blend_mask))
    return values, surveyed, replaced


def _surveyed_share_of_sea(grid: np.ndarray, surveyed: np.ndarray) -> float:
    """What share of a frame's *sea floor* anybody surveyed.

    Sea only, and that is the point: averaging the mask over the whole grid
    would dilute the answer with land, which is not what the number is about
    and would read lower the more coast a sheet contains.
    """
    if grid.shape != surveyed.shape or grid.size == 0:
        return 0.0
    sea = np.isfinite(grid) & (grid < 0.0)
    if not np.any(sea):
        return 0.0
    return float(np.mean(surveyed[sea]))


def _effective_measured_grid(blended: np.ndarray, surveyed: np.ndarray) -> np.ndarray:
    """`surveyed`, with land folded in as fully measured.

    `surveyed` only ever describes the sea floor -- land is never touched by
    the blend and stays `0` there by construction, which is correct for the
    sea-only aggregate in `_surveyed_share_of_sea` but wrong for a
    per-feature check: land is always measured ground (SRTM and friends),
    so it should never count against a feature that happens to touch it.
    Computed once, here, against the grid at blend time -- a later smoothing
    pass can shift a coastal cell's value across zero, and a feature built
    downstream of that has no way back to which side it started on.
    """
    is_sea = np.isfinite(blended) & (blended < 0.0)
    return np.where(is_sea, surveyed, 1.0)


#: Below this, a cell counts as still sitting on the coarse global grid
#: rather than EMODnet's own survey -- matching the Mac's own
#: `BlendedSeaFloor.claim(forSamples:)`, not a threshold invented here.
MEASURED_THRESHOLD = 0.999


def _measured_along_polyline(measured: np.ndarray, polyline: list[tuple[float, float]]) -> bool:
    """Whether a traced line reads as measured ground -- all of it.

    Sampled at each vertex rather than integrated along the path -- a
    contour is already densely vertexed enough that the two agree, and this
    is simpler to test. Every sampled cell has to clear `MEASURED_THRESHOLD`;
    one still sitting on the coarse global grid is enough to call the whole
    line approximate, the same way the Mac's port target does -- not a
    majority vote, and not "nearly all."
    """
    if not polyline:
        return True
    rows, cols = measured.shape
    if rows == 0 or cols == 0:
        return True
    for row, col in polyline:
        sample_row = min(max(int(round(row)), 0), rows - 1)
        sample_col = min(max(int(round(col)), 0), cols - 1)
        if measured[sample_row, sample_col] < MEASURED_THRESHOLD:
            return False
    return True


def _band_is_measured(
    coarse: np.ndarray, coarse_measured: np.ndarray | None, band: ElevationBand
) -> bool:
    """Whether a band reads as measured ground overall -- every cell in it,
    not most of them; see `_measured_along_polyline`.

    `coarse_measured` already has land folded in as fully measured (see
    `_effective_measured_grid`); this only has to find which cells belong to
    the band.
    """
    if coarse_measured is None:
        return True
    mask = (coarse >= band.lower) & (coarse <= band.upper)
    if not np.any(mask):
        return True
    return bool(np.all(coarse_measured[mask] >= MEASURED_THRESHOLD))


def _surveyed_share_along_polyline(measured: np.ndarray, polyline: list[tuple[float, float]]) -> float:
    """The mean survey-grid value along a traced line's own vertices -- the
    same sampling `_measured_along_polyline` walks, kept alongside it rather
    than folded into it because a sub-sea contour's provenance is graded,
    not only pass or fail: a line that is half on EMODnet's survey and half
    on the coarse global grid is neither `measured` nor simply "not", and a
    reader deciding how much to trust it wants the fraction.
    """
    if not polyline:
        return 1.0
    rows, cols = measured.shape
    if rows == 0 or cols == 0:
        return 1.0
    samples = [
        measured[min(max(int(round(row)), 0), rows - 1), min(max(int(round(col)), 0), cols - 1)]
        for row, col in polyline
    ]
    return float(np.mean(samples))


def _band_surveyed_share(
    coarse: np.ndarray, coarse_measured: np.ndarray | None, band: ElevationBand
) -> float:
    """The mean survey-grid value over a band's own cells -- the same mask
    `_band_is_measured` tests, kept apart for the same reason
    `_surveyed_share_along_polyline` is kept apart from
    `_measured_along_polyline`.
    """
    if coarse_measured is None:
        return 1.0
    mask = (coarse >= band.lower) & (coarse <= band.upper)
    if not np.any(mask):
        return 1.0
    return float(np.mean(coarse_measured[mask]))


def _depth_source(share: float) -> str:
    """Which grid a sub-sea feature's depth came from, in words -- matching
    the Mac's own thresholds (`BlendedSeaFloor.claim(forSamples:)`'s
    siblings), not ones invented here.
    """
    if share >= MEASURED_THRESHOLD:
        return "survey"
    if share <= 0.001:
        return "global_grid"
    return "mixed"


def _depth_band_mode(value: str) -> DepthBandMode:
    """A settings string, read back as a mode.

    Settings travel as plain values through the session file and the source
    panel, so an unknown one is a stale file rather than a reason to refuse to
    draw: it falls back to even rather than raising.
    """
    try:
        return DepthBandMode(str(value).strip().lower())
    except ValueError:
        return DepthBandMode.EVEN
