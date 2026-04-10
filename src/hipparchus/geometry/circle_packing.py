"""Circle packing utilities inside map boundaries."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from shapely.geometry import Point, Polygon
from shapely.geometry.base import BaseGeometry


@dataclass(slots=True, frozen=True)
class CirclePackingOptions:
    """Controls circle size, spacing, and output count."""

    min_radius: float = 4.0
    max_radius: float = 24.0
    radius_step: float = 2.0
    sample_step: float = 6.0
    max_circles: int = 250
    clearance: float = 1.5


def pack_circles_in_boundary(boundary: BaseGeometry, options: CirclePackingOptions) -> list[Polygon]:
    """Greedy circle packing constrained by boundary geometry."""
    if boundary.is_empty:
        return []
    if options.min_radius <= 0 or options.max_radius <= 0:
        raise ValueError("Circle radii must be > 0")
    if options.min_radius > options.max_radius:
        raise ValueError("min_radius cannot be greater than max_radius")

    minx, miny, maxx, maxy = boundary.bounds
    circles: list[Polygon] = []

    y = miny
    while y <= maxy and len(circles) < options.max_circles:
        x = minx
        while x <= maxx and len(circles) < options.max_circles:
            center = Point(x, y)
            radius = _largest_fit_radius(center, boundary, circles, options)
            if radius >= options.min_radius:
                circles.append(center.buffer(radius, quad_segs=32))
            x += options.sample_step
        y += options.sample_step

    return circles


def _largest_fit_radius(
    center: Point,
    boundary: BaseGeometry,
    placed: Iterable[Polygon],
    options: CirclePackingOptions,
) -> float:
    if not boundary.contains(center):
        return 0.0

    best = 0.0
    radius = options.min_radius
    while radius <= options.max_radius + 1e-9:
        circle = center.buffer(radius, quad_segs=24)
        if not boundary.contains(circle):
            break

        blocked = False
        for existing in placed:
            if circle.distance(existing) < options.clearance:
                blocked = True
                break
        if blocked:
            break

        best = radius
        radius += options.radius_step

    return best
