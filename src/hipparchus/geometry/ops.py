"""Backward-compatible geometry operation wrappers."""

from __future__ import annotations

from shapely.geometry.base import BaseGeometry

from hipparchus.geometry.simplification import SimplificationOptions, simplify_geometry as _simplify_geometry


def simplify_geometry(geometry: BaseGeometry, tolerance: float) -> BaseGeometry:
    """Simplify geometry via Douglas-Peucker algorithm."""
    return _simplify_geometry(geometry, SimplificationOptions(tolerance=tolerance))


def smooth_streets(geometry: BaseGeometry, iterations: int = 1) -> BaseGeometry:
    """Basic smoothing placeholder using low-tolerance simplification."""
    tolerance = max(0.01, float(iterations) * 0.25)
    return _simplify_geometry(geometry, SimplificationOptions(tolerance=tolerance, preserve_topology=True))
