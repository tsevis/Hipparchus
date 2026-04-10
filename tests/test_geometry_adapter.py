from __future__ import annotations

import unittest

from shapely.geometry import LineString, MultiLineString, Polygon

from hipparchus.rendering.geometry_adapter import geometry_to_svg_path_data


class GeometryAdapterTests(unittest.TestCase):
    def test_linestring_to_svg_path(self) -> None:
        geom = LineString([(0.0, 0.0), (10.5, 10.25)])
        paths = geometry_to_svg_path_data(geom, precision=2)
        self.assertEqual(paths, ["M 0 0 L 10.5 10.25"])

    def test_polygon_to_closed_path(self) -> None:
        geom = Polygon([(0, 0), (5, 0), (5, 5), (0, 0)])
        paths = geometry_to_svg_path_data(geom)
        self.assertTrue(paths[0].startswith("M 0 0"))
        self.assertTrue(paths[0].endswith("Z"))

    def test_multiline_splits_paths(self) -> None:
        geom = MultiLineString([[(0, 0), (1, 1)], [(2, 2), (3, 3)]])
        paths = geometry_to_svg_path_data(geom)
        self.assertEqual(len(paths), 2)


if __name__ == "__main__":
    unittest.main()
