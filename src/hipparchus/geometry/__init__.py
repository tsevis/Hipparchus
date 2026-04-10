"""Geometry processing subsystem package."""

from hipparchus.geometry.circle_packing import CirclePackingOptions, pack_circles_in_boundary
from hipparchus.geometry.hex_grid import HexGridOptions, generate_hex_grid
from hipparchus.geometry.simplification import SimplificationOptions, simplify_geometries, simplify_geometry
from hipparchus.geometry.triangulation import (
    TriangleMesh,
    delaunay_from_points,
    delaunay_from_road_intersections,
    road_intersections,
)
from hipparchus.geometry.voronoi import (
    VoronoiCell,
    points_from_geometry_vertices,
    voronoi_from_building_centroids,
    voronoi_from_geometry_vertices,
    voronoi_from_points,
)

__all__ = [
    "SimplificationOptions",
    "simplify_geometry",
    "simplify_geometries",
    "VoronoiCell",
    "voronoi_from_points",
    "voronoi_from_building_centroids",
    "points_from_geometry_vertices",
    "voronoi_from_geometry_vertices",
    "HexGridOptions",
    "generate_hex_grid",
    "TriangleMesh",
    "road_intersections",
    "delaunay_from_points",
    "delaunay_from_road_intersections",
    "CirclePackingOptions",
    "pack_circles_in_boundary",
]
