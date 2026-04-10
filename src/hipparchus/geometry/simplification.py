"""Geometry simplification tools for map preprocessing."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
import os
from typing import Iterable

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.wkb import dumps as wkb_dumps
from shapely.wkb import loads as wkb_loads


@dataclass(slots=True, frozen=True)
class SimplificationOptions:
    """Controls for geometry cleanup and simplification."""

    tolerance: float = 1.0
    preserve_topology: bool = True
    remove_redundant_nodes: bool = True


def simplify_geometry(geometry: BaseGeometry, options: SimplificationOptions) -> BaseGeometry:
    """Simplify one geometry while preserving map-safe topology by default."""
    if geometry.is_empty:
        return geometry

    simplified = geometry.simplify(options.tolerance, preserve_topology=options.preserve_topology)
    if options.remove_redundant_nodes:
        simplified = _remove_redundant_nodes(simplified)

    if not simplified.is_valid:
        fixed = simplified.buffer(0)
        if not fixed.is_empty:
            simplified = fixed

    return simplified


def simplify_geometries(
    geometries: Iterable[BaseGeometry],
    options: SimplificationOptions,
    workers: int | None = None,
) -> list[BaseGeometry]:
    """Simplify multiple geometries and skip empties from outputs.

    Set `workers` > 1 to parallelize on multi-core systems (Apple Silicon optimized).
    """
    items = list(geometries)
    if not items:
        return []

    worker_count = _resolve_workers(workers)
    if worker_count <= 1 or len(items) < 64:
        return _simplify_serial(items, options)

    payload = [wkb_dumps(geom) for geom in items]
    try:
        with ProcessPoolExecutor(max_workers=worker_count) as pool:
            packed = list(pool.map(_simplify_wkb_worker, ((blob, options) for blob in payload)))
    except (PermissionError, OSError):
        # Environments with restricted semaphore/process primitives fall back safely.
        return _simplify_serial(items, options)

    return [wkb_loads(blob) for blob in packed if blob is not None]


def _simplify_serial(geometries: list[BaseGeometry], options: SimplificationOptions) -> list[BaseGeometry]:
    """Simplify geometries in-process."""
    result: list[BaseGeometry] = []
    for geometry in geometries:
        optimized = simplify_geometry(geometry, options)
        if not optimized.is_empty:
            result.append(optimized)
    return result


def _simplify_wkb_worker(payload: tuple[bytes, SimplificationOptions]) -> bytes | None:
    blob, options = payload
    geometry = wkb_loads(blob)
    simplified = simplify_geometry(geometry, options)
    if simplified.is_empty:
        return None
    return wkb_dumps(simplified)


def _resolve_workers(requested: int | None) -> int:
    if requested is not None:
        return max(1, requested)
    cpu_count = os.cpu_count() or 1
    # Leave one core for UI/event loop responsiveness.
    return max(1, cpu_count - 1)


def _remove_redundant_nodes(geometry: BaseGeometry) -> BaseGeometry:
    if isinstance(geometry, LineString):
        coords = _simplify_coords(list(geometry.coords), closed=False)
        return LineString(coords) if len(coords) >= 2 else geometry

    if isinstance(geometry, Polygon):
        ext = _simplify_coords(list(geometry.exterior.coords), closed=True)
        holes = [_simplify_coords(list(ring.coords), closed=True) for ring in geometry.interiors]
        holes = [ring for ring in holes if len(ring) >= 4]
        return Polygon(ext, holes=holes) if len(ext) >= 4 else geometry

    if isinstance(geometry, MultiLineString):
        return MultiLineString([_remove_redundant_nodes(line) for line in geometry.geoms])

    if isinstance(geometry, MultiPolygon):
        return MultiPolygon([_remove_redundant_nodes(poly) for poly in geometry.geoms])

    if isinstance(geometry, GeometryCollection):
        return GeometryCollection([_remove_redundant_nodes(g) for g in geometry.geoms])

    return geometry


def _simplify_coords(coords: list[tuple[float, float]], closed: bool) -> list[tuple[float, float]]:
    if len(coords) <= (4 if closed else 2):
        return coords

    pts = coords[:]
    if closed and pts[0] != pts[-1]:
        pts.append(pts[0])

    out: list[tuple[float, float]] = [pts[0]]
    for idx in range(1, len(pts) - 1):
        a = out[-1]
        b = pts[idx]
        c = pts[idx + 1]
        if _is_collinear_and_forward(a, b, c):
            continue
        out.append(b)
    out.append(pts[-1])

    if closed and out[0] != out[-1]:
        out.append(out[0])

    return out


def _is_collinear_and_forward(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
) -> bool:
    abx = b[0] - a[0]
    aby = b[1] - a[1]
    bcx = c[0] - b[0]
    bcy = c[1] - b[1]

    cross = abx * bcy - aby * bcx
    if abs(cross) > 1e-9:
        return False

    dot = abx * bcx + aby * bcy
    return dot >= 0.0
