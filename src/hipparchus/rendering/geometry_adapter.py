"""Geometry adapters for rendering and SVG path generation."""

from __future__ import annotations

from typing import Iterable

from shapely.geometry import GeometryCollection, LineString, LinearRing, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry


def iter_atomic_geometries(geometry: BaseGeometry) -> Iterable[BaseGeometry]:
    """Yield atomic geometries from complex geometry containers."""
    if geometry.is_empty:
        return

    if isinstance(geometry, (MultiLineString, MultiPolygon, MultiPoint, GeometryCollection)):
        for geom in geometry.geoms:
            yield from iter_atomic_geometries(geom)
        return

    yield geometry


def geometry_to_svg_path_data(geometry: BaseGeometry, precision: int = 6) -> list[str]:
    """Convert a shapely geometry to one or more SVG path strings."""
    paths: list[str] = []
    for geom in iter_atomic_geometries(geometry):
        if isinstance(geom, Polygon):
            ext = _ring_to_path(geom.exterior.coords, close_path=True, precision=precision)
            paths.append(ext)
            for interior in geom.interiors:
                paths.append(_ring_to_path(interior.coords, close_path=True, precision=precision))
        elif isinstance(geom, (LineString, LinearRing)):
            paths.append(_ring_to_path(geom.coords, close_path=False, precision=precision))
        elif isinstance(geom, Point):
            x, y = geom.x, geom.y
            paths.append(_point_to_circle_path(x, y, radius=0.5, precision=precision))
    return [path for path in paths if path]


def _ring_to_path(coords: Iterable[tuple[float, float]], close_path: bool, precision: int) -> str:
    pts = list(coords)
    if len(pts) < 2:
        return ""

    start = pts[0]
    commands = [f"M {_fmt(start[0], precision)} {_fmt(start[1], precision)}"]
    for x, y in pts[1:]:
        commands.append(f"L {_fmt(x, precision)} {_fmt(y, precision)}")
    if close_path:
        commands.append("Z")
    return " ".join(commands)


def _point_to_circle_path(x: float, y: float, radius: float, precision: int) -> str:
    """Represent point as tiny closed path for vector exporters."""
    left = x - radius
    right = x + radius
    top = y - radius
    bottom = y + radius
    return (
        f"M {_fmt(left, precision)} {_fmt(y, precision)} "
        f"A {_fmt(radius, precision)} {_fmt(radius, precision)} 0 1 0 {_fmt(right, precision)} {_fmt(y, precision)} "
        f"A {_fmt(radius, precision)} {_fmt(radius, precision)} 0 1 0 {_fmt(left, precision)} {_fmt(y, precision)} "
        f"Z"
    )


def _fmt(value: float, precision: int) -> str:
    text = f"{value:.{precision}f}".rstrip("0").rstrip(".")
    return text if text else "0"
