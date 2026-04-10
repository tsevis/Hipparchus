from __future__ import annotations

import unittest

from shapely.geometry import LineString

from hipparchus.geometry.simplification import SimplificationOptions, simplify_geometries


class SimplificationParallelTests(unittest.TestCase):
    def test_parallel_and_serial_match(self) -> None:
        geoms = [LineString([(0, 0), (1, 0), (2, 0), (3, 1), (4, 2)]) for _ in range(80)]
        options = SimplificationOptions(tolerance=0.0, remove_redundant_nodes=True)

        serial = simplify_geometries(geoms, options, workers=1)
        parallel = simplify_geometries(geoms, options, workers=2)

        self.assertEqual(len(serial), len(parallel))
        for a, b in zip(serial, parallel, strict=False):
            self.assertTrue(a.equals_exact(b, tolerance=1e-9))


if __name__ == "__main__":
    unittest.main()
