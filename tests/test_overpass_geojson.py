from __future__ import annotations

import unittest

from hipparchus.data_sources.overpass_geojson import convert_overpass_to_feature_collection


class OverpassGeoJSONTests(unittest.TestCase):
    def test_converts_and_splits_layers(self) -> None:
        payload = {
            "elements": [
                {
                    "type": "way",
                    "id": 1,
                    "tags": {"highway": "residential"},
                    "geometry": [
                        {"lon": 10.0, "lat": 20.0},
                        {"lon": 10.1, "lat": 20.1},
                    ],
                },
                {
                    "type": "way",
                    "id": 2,
                    "tags": {"building": "yes"},
                    "geometry": [
                        {"lon": 0.0, "lat": 0.0},
                        {"lon": 1.0, "lat": 0.0},
                        {"lon": 1.0, "lat": 1.0},
                        {"lon": 0.0, "lat": 0.0},
                    ],
                },
            ]
        }

        result = convert_overpass_to_feature_collection(payload).feature_collection

        self.assertEqual(len(result.features_by_layer["roads"]), 1)
        self.assertEqual(len(result.features_by_layer["buildings"]), 1)
        self.assertEqual(result.features_by_layer["roads"][0]["geometry"]["type"], "LineString")
        self.assertEqual(result.features_by_layer["buildings"][0]["geometry"]["type"], "Polygon")
        self.assertEqual(result.geojson_by_layer["roads"]["type"], "FeatureCollection")

    def test_classifies_named_sea_as_coastline_not_place_label(self) -> None:
        payload = {
            "elements": [
                {
                    "type": "way",
                    "id": 44,
                    "tags": {"place": "sea", "name": "Example Sea"},
                    "geometry": [
                        {"lon": 0.0, "lat": 0.0},
                        {"lon": 1.0, "lat": 0.0},
                        {"lon": 1.0, "lat": 1.0},
                        {"lon": 0.0, "lat": 0.0},
                    ],
                },
            ]
        }

        result = convert_overpass_to_feature_collection(payload).feature_collection

        self.assertEqual(len(result.features_by_layer["coastline"]), 1)
        self.assertEqual(len(result.features_by_layer["places"]), 0)


if __name__ == "__main__":
    unittest.main()
