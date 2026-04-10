from __future__ import annotations

import unittest

from shapely.geometry import LineString, Point, Polygon

from hipparchus.geometry.circle_packing import CirclePackingOptions, pack_circles_in_boundary
from hipparchus.geometry.hex_grid import HexGridOptions, generate_hex_grid
from hipparchus.geometry.simplification import SimplificationOptions, simplify_geometry
from hipparchus.geometry.triangulation import delaunay_from_points, delaunay_from_road_intersections, road_intersections
from hipparchus.geometry.voronoi import voronoi_from_building_centroids


class GeometryToolsTests(unittest.TestCase):
    def test_simplification_reduces_redundant_nodes(self) -> None:
        line = LineString([(0, 0), (1, 0), (2, 0), (2, 2)])
        simplified = simplify_geometry(line, SimplificationOptions(tolerance=0.0, remove_redundant_nodes=True))
        self.assertLess(len(list(simplified.coords)), len(list(line.coords)))

    def test_voronoi_from_building_centroids(self) -> None:
        boundary = Polygon([(0, 0), (20, 0), (20, 20), (0, 20), (0, 0)])
        buildings = [
            Polygon([(2, 2), (3, 2), (3, 3), (2, 2)]),
            Polygon([(12, 3), (13, 3), (13, 4), (12, 3)]),
            Polygon([(6, 14), (7, 14), (7, 15), (6, 14)]),
        ]

        cells = voronoi_from_building_centroids(buildings, boundary)

        self.assertGreaterEqual(len(cells), 3)
        self.assertTrue(all(boundary.contains(cell.polygon) or boundary.touches(cell.polygon) for cell in cells))

    def test_hex_grid_over_boundary(self) -> None:
        boundary = Polygon([(0, 0), (50, 0), (50, 50), (0, 50), (0, 0)])
        hexes = generate_hex_grid(boundary, HexGridOptions(radius=6.0, clip_to_boundary=True))

        self.assertGreater(len(hexes), 10)
        self.assertTrue(all(hexagon.is_valid and not hexagon.is_empty for hexagon in hexes))

    def test_delaunay_from_road_intersections(self) -> None:
        roads = [
            LineString([(0, 0), (10, 10)]),
            LineString([(0, 10), (10, 0)]),
            LineString([(2, 0), (2, 10)]),
            LineString([(8, 0), (8, 10)]),
        ]
        intersections = road_intersections(roads)
        mesh = delaunay_from_road_intersections(roads)

        self.assertGreaterEqual(len(intersections), 4)
        self.assertGreater(len(mesh.triangles), 0)

    def test_delaunay_from_points(self) -> None:
        pts = [Point(0, 0), Point(10, 0), Point(5, 8), Point(3, 3)]
        mesh = delaunay_from_points(pts)
        self.assertGreater(len(mesh.triangles), 0)

    def test_circle_packing_within_boundary(self) -> None:
        boundary = Polygon([(0, 0), (60, 0), (60, 60), (0, 60), (0, 0)])
        circles = pack_circles_in_boundary(
            boundary,
            CirclePackingOptions(
                min_radius=3.0,
                max_radius=6.0,
                radius_step=1.0,
                sample_step=6.0,
                max_circles=40,
                clearance=0.2,
            ),
        )

        self.assertGreater(len(circles), 5)
        self.assertTrue(all(boundary.contains(circle) or boundary.touches(circle) for circle in circles))

        for i, first in enumerate(circles):
            for second in circles[i + 1 :]:
                self.assertGreaterEqual(first.distance(second), 0.0)


if __name__ == "__main__":
    unittest.main()
