"""Hexagonal grid generation over map boundaries."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry


@dataclass(slots=True, frozen=True)
class HexGridOptions:
    """Controls hex size and clipping behavior."""

    radius: float
    clip_to_boundary: bool = True


def generate_hex_grid(boundary: BaseGeometry, options: HexGridOptions) -> list[Polygon]:
    """Create a pointy-top hex grid covering a boundary geometry."""
    if boundary.is_empty:
        return []
    if options.radius <= 0:
        raise ValueError("radius must be > 0")

    minx, miny, maxx, maxy = boundary.bounds
    radius = options.radius
    width = math.sqrt(3.0) * radius
    vertical_step = 1.5 * radius

    hexes: list[Polygon] = []
    row = 0
    y = miny - radius
    while y <= maxy + radius:
        x_offset = width / 2.0 if row % 2 else 0.0
        x = minx - width + x_offset
        while x <= maxx + width:
            hexagon = _make_hexagon(x, y, radius)
            if options.clip_to_boundary:
                clipped = hexagon.intersection(boundary)
                if clipped.is_empty:
                    x += width
                    continue
                if clipped.geom_type == "Polygon":
                    hexes.append(clipped)
                else:
                    hexes.extend([g for g in getattr(clipped, "geoms", []) if g.geom_type == "Polygon"])
            else:
                if hexagon.intersects(boundary):
                    hexes.append(hexagon)
            x += width
        y += vertical_step
        row += 1

    return hexes


def _make_hexagon(cx: float, cy: float, radius: float) -> Polygon:
    points: list[tuple[float, float]] = []
    for i in range(6):
        angle = math.radians(60 * i - 30)
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    points.append(points[0])
    return Polygon(points)
