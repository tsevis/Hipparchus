from __future__ import annotations

import unittest

from hipparchus.data_sources.overpass_query import build_overpass_query
from hipparchus.data_sources.provider import BBoxQuery


class OverpassQueryTests(unittest.TestCase):
    def test_builds_bbox_query_for_selected_layers(self) -> None:
        query = BBoxQuery(min_lon=10.0, min_lat=20.0, max_lon=11.0, max_lat=21.0, layers=("roads", "water"))
        ql = build_overpass_query(query)

        self.assertIn("20.0,10.0,21.0,11.0", ql)
        self.assertIn('way["highway"]', ql)
        self.assertIn('way["natural"="water"]', ql)
        self.assertNotIn('way["building"]', ql)


if __name__ == "__main__":
    unittest.main()
