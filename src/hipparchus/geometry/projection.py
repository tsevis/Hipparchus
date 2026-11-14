"""Projection helpers for cartographic rendering."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

import numpy as np
import shapely
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from hipparchus.geometry import equal_earth
from hipparchus.geometry.densify import densified


ProjectionMode = Literal["wgs84_raw", "web_mercator", "local_azimuthal", "equal_earth"]
PROJECTION_MODES: tuple[str, ...] = (
    "wgs84_raw",
    "web_mercator",
    "local_azimuthal",
    "equal_earth",
)
EARTH_RADIUS_M = 6_378_137.0
MAX_MERCATOR_LAT = 85.05112878

#: How far the meridians may converge across a frame before a flat projection
#: has stopped telling the truth about it.
#:
#: Both small-frame projections scale east-west by a single cosine:
#: ``local_azimuthal`` by the cosine of the frame's centre, Web Mercator by
#: stretching north-south with the secant of each latitude. Either way the error
#: across a frame is the ratio between the cosine at its centre and the cosine
#: at its furthest edge, and this is how far that ratio may fall from 1.
#:
#: 0.12 is where the worked examples land either side of the line. Santorini is
#: 0.001 and Greece 0.05, so an island and a small country keep the projection
#: written for them; France is 0.086 and keeps it too. The contiguous United
#: States is 0.18, Europe 0.49 and the world 0.91 -- frames where a reader would
#: see the stretch without being told to look for it. The numbers are measured
#: by `convergence_departure` in `tests/test_equal_earth.py`, not remembered.
CONVERGENCE_TOLERANCE = 0.12

#: The projections that map longitude to x and latitude to y independently. A
#: segment straight in degrees stays straight on the sheet in these, and does
#: not in `equal_earth`, whose meridians converge. What turns on it is whether
#: geometry has to be densified before projecting, and whether a frame's bounds
#: can be read off its corners.
_STRAIGHT_MERIDIAN_MODES = frozenset({"wgs84_raw", "web_mercator", "local_azimuthal"})

#: Sides sampled when bounding a frame in a curved projection. Sixteen is far
#: more than the curve needs and costs nothing: this runs once per render, not
#: once per feature.
_BOUNDS_SAMPLES = 16


def convergence_departure(bbox: tuple[float, float, float, float] | None) -> float:
    """How far a flat projection's single cosine is out across this frame.

    Zero for a frame with no north-south extent, and it grows towards 1 as the
    frame reaches a pole, where the meridians have converged to a point.
    """
    if bbox is None:
        return 0.0
    _min_lon, min_lat, _max_lon, max_lat = bbox
    centre = (min_lat + max_lat) * 0.5
    edge = min(max(abs(min_lat), abs(max_lat)), 90.0)
    centre_cosine = math.cos(math.radians(centre))
    if centre_cosine <= 1e-9:
        # A frame centred on a pole: nothing flat can carry it.
        return 1.0
    return abs(1.0 - math.cos(math.radians(edge)) / centre_cosine)


def honest_mode(mode: str, bbox: tuple[float, float, float, float] | None) -> ProjectionMode:
    """The projection a frame this size should actually be drawn in.

    An improvement, not an override. ``wgs84_raw`` means "give me degrees" and
    is left alone; a frame small enough for the projection it asked for keeps
    it; only a frame that has outgrown its projection is moved, and it is moved
    to the one mode here with no size at which it stops working.

    There is deliberately no projection picker in the interface. Every render
    already asks for a projection through its quality profile, and a person
    choosing between four names is being asked a question the frame has already
    answered. Applied to previews as well as exports: the two tiers differ in
    how much work they spend, not in what the map is, and a preview that cannot
    be trusted to show the shape of the exported sheet is not a preview.
    """
    resolved = _projection_mode(mode)
    if bbox is None or resolved not in {"web_mercator", "local_azimuthal"}:
        return resolved
    return "equal_earth" if convergence_departure(bbox) > CONVERGENCE_TOLERANCE else resolved


@dataclass(slots=True, frozen=True)
class ProjectionProfile:
    """Projection settings for scene-building and export."""

    mode: ProjectionMode = "web_mercator"
    center_lon: float = 0.0
    center_lat: float = 0.0

    @classmethod
    def from_bbox(
        cls,
        bbox: tuple[float, float, float, float] | None,
        mode: str = "web_mercator",
        *,
        honest: bool = False,
    ) -> "ProjectionProfile":
        """The profile for this frame.

        ``honest`` asks for the projection the frame can actually carry rather
        than the one it named -- see `honest_mode`. Off by default so a caller
        that wants a particular projection, a test or a diagnostic among them,
        gets the one it asked for.
        """
        resolved = honest_mode(mode, bbox) if honest else _projection_mode(mode)
        if bbox is None:
            return cls(mode=resolved)
        min_lon, min_lat, max_lon, max_lat = bbox
        return cls(
            mode=resolved,
            center_lon=(min_lon + max_lon) * 0.5,
            center_lat=(min_lat + max_lat) * 0.5,
        )

    @property
    def source_crs(self) -> str:
        return "EPSG:4326"

    @property
    def render_crs(self) -> str:
        if self.mode == "wgs84_raw":
            return "EPSG:4326"
        if self.mode == "web_mercator":
            return "EPSG:3857"
        if self.mode == "equal_earth":
            return "EQUAL_EARTH"
        return "LOCAL_AZIMUTHAL_EQUIRECTANGULAR"

    def project_point(self, lon: float, lat: float) -> tuple[float, float]:
        if self.mode == "wgs84_raw":
            return (lon, lat)
        if self.mode == "web_mercator":
            bounded_lat = max(-MAX_MERCATOR_LAT, min(MAX_MERCATOR_LAT, lat))
            x = EARTH_RADIUS_M * math.radians(lon)
            y = EARTH_RADIUS_M * math.log(math.tan(math.pi / 4.0 + math.radians(bounded_lat) / 2.0))
            return (x, y)
        if self.mode == "equal_earth":
            return equal_earth.project(
                lon, lat, central_meridian=self.center_lon, radius=EARTH_RADIUS_M
            )

        center_lat_rad = math.radians(self.center_lat)
        x = EARTH_RADIUS_M * math.radians(lon - self.center_lon) * math.cos(center_lat_rad)
        y = EARTH_RADIUS_M * math.radians(lat - self.center_lat)
        return (x, y)

    def unproject_point(self, x: float, y: float) -> tuple[float, float]:
        if self.mode == "wgs84_raw":
            return (x, y)
        if self.mode == "web_mercator":
            lon = math.degrees(x / EARTH_RADIUS_M)
            lat = math.degrees(2.0 * math.atan(math.exp(y / EARTH_RADIUS_M)) - math.pi / 2.0)
            return (lon, lat)
        if self.mode == "equal_earth":
            return equal_earth.unproject(
                x, y, central_meridian=self.center_lon, radius=EARTH_RADIUS_M
            )

        center_lat_rad = math.radians(self.center_lat)
        lon = self.center_lon + math.degrees(x / (EARTH_RADIUS_M * max(math.cos(center_lat_rad), 1e-9)))
        lat = self.center_lat + math.degrees(y / EARTH_RADIUS_M)
        return (lon, lat)

    @property
    def bends_meridians(self) -> bool:
        """Whether a straight line in degrees comes out curved on the sheet."""
        return self.mode not in _STRAIGHT_MERIDIAN_MODES

    def project_geometry(self, geometry: BaseGeometry) -> BaseGeometry:
        if geometry.is_empty:
            return geometry
        if self.bends_meridians:
            # A straight run in degrees is a curve on an Equal Earth sheet, and
            # a projection applied vertex by vertex cannot know that. See
            # `densify` for the rectangle that appeared over the Pacific
            # without this.
            geometry = densified(geometry)

        def _project(coords: np.ndarray) -> np.ndarray:
            projected = [self.project_point(float(x), float(y)) for x, y in coords]
            return np.array(projected, dtype=float).reshape(-1, 2)

        return shapely.transform(geometry, _project)

    def project_bbox(self, bbox: tuple[float, float, float, float] | None) -> tuple[float, float, float, float] | None:
        if bbox is None:
            return None
        min_lon, min_lat, max_lon, max_lat = bbox
        if not self.bends_meridians:
            corners = (
                self.project_point(min_lon, min_lat),
                self.project_point(min_lon, max_lat),
                self.project_point(max_lon, min_lat),
                self.project_point(max_lon, max_lat),
            )
        else:
            # The whole outline, not the four corners. Corners were enough
            # while every mode mapped longitude to x and latitude to y
            # independently; `equal_earth` bends the meridians, so a world
            # frame is at its widest **on the equator** -- between two corners,
            # not at either of them -- and the corners understate its width by
            # about two fifths. Bounding it by them cropped the equator off the
            # sheet.
            outline = []
            for step in range(_BOUNDS_SAMPLES + 1):
                fraction = step / _BOUNDS_SAMPLES
                lon = min_lon + (max_lon - min_lon) * fraction
                lat = min_lat + (max_lat - min_lat) * fraction
                outline.append(self.project_point(lon, min_lat))
                outline.append(self.project_point(lon, max_lat))
                outline.append(self.project_point(min_lon, lat))
                outline.append(self.project_point(max_lon, lat))
            corners = tuple(outline)
        xs = [point[0] for point in corners]
        ys = [point[1] for point in corners]
        return (min(xs), min(ys), max(xs), max(ys))

    def project_bbox_geometry(self, bbox: tuple[float, float, float, float] | None) -> BaseGeometry | None:
        projected = self.project_bbox(bbox)
        if projected is None:
            return None
        return box(*projected)

    def metadata(self, bbox: tuple[float, float, float, float] | None) -> dict[str, object]:
        return {
            "mode": self.mode,
            "source_crs": self.source_crs,
            "render_crs": self.render_crs,
            "center": (self.center_lon, self.center_lat),
            "source_bbox": bbox,
            "projected_bbox": self.project_bbox(bbox),
        }


def _projection_mode(value: str) -> ProjectionMode:
    if value in PROJECTION_MODES:
        return value  # type: ignore[return-value]
    return "web_mercator"
