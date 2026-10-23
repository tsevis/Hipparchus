"""The sea, inferred from a coastline that only describes its edge.

Ported back from HipparchusMac's ``SeaInferenceTests``: the Swift engine found
both faults on Miami's waterfront, where Biscayne Bay came out as land.
"""

from __future__ import annotations

import unittest

from shapely.geometry import LineString, Point, Polygon, box

from hipparchus.application.scene_builder import _derive_sea_polygons

FRAME = box(0.0, 0.0, 1.0, 1.0)
# A coast running north-south through the middle of the frame.
COAST = LineString([(0.5, -0.1), (0.5, 1.1)])


def _buildings_on_the_east() -> list[Polygon]:
    return [box(0.6 + index * 0.05, 0.4, 0.62 + index * 0.05, 0.6) for index in range(6)]


class SeaInferenceTests(unittest.TestCase):
    def test_features_straddling_the_coast_are_counted_on_one_side_only(self) -> None:
        # Piers reaching from the land into the water: counted on every face
        # they touched, they tied the sea with the land.
        piers = [box(0.48, 0.05 + index * 0.09, 0.6, 0.07 + index * 0.09) for index in range(10)]

        sea = _derive_sea_polygons({"coastline": [COAST], "buildings": piers}, FRAME)

        self.assertEqual(len(sea), 1, "the shoreline features tied the sea with the land")
        self.assertLess(sea[0].centroid.x, 0.5, "the sea was drawn over the land")

    def test_an_island_in_the_sea_is_not_painted_over(self) -> None:
        # OSM closes an island's coastline into a ring, which arrives as a polygon.
        island = box(0.1, 0.4, 0.3, 0.6)

        sea = _derive_sea_polygons(
            {"coastline": [COAST, island], "buildings": _buildings_on_the_east()}, FRAME
        )

        self.assertTrue(sea, "no sea was inferred at all")
        for polygon in sea:
            self.assertFalse(polygon.covers(Point(0.2, 0.5)), "the sea was painted over the island")

    def test_an_island_does_not_break_a_tie_between_the_other_faces(self) -> None:
        # An island is land whatever it scores. Scored as land, it broke the tie
        # between two halves with no evidence, and both became sea, town included.
        island = box(0.1, 0.4, 0.3, 0.6)
        hut = box(0.15, 0.45, 0.2, 0.5)

        sea = _derive_sea_polygons({"coastline": [COAST, island], "buildings": [hut]}, FRAME)

        self.assertEqual(sea, [], "a sea was invented from a tie")

    def test_an_empty_lagoon_does_not_take_the_place_of_the_bay(self) -> None:
        # Bridges stand in the bay; a lagoon cut off by a second coast has nothing
        # in it. The lowest score alone made the lagoon the only sea.
        lagoon_shore = LineString([(-0.1, 0.2), (0.2, -0.1)])
        bridges = [LineString([(0.15, 0.3 + index * 0.1), (0.4, 0.3 + index * 0.1)]) for index in range(5)]
        # A city as dense against its bridges as Miami's is against Biscayne Bay's.
        city = [box(0.55 + (i % 10) * 0.04, 0.05 + (i // 10) * 0.09, 0.57 + (i % 10) * 0.04, 0.07 + (i // 10) * 0.09) for i in range(100)]

        sea = _derive_sea_polygons(
            {
                "coastline": [COAST, lagoon_shore],
                "buildings": city,
                "roads": bridges,
            },
            FRAME,
        )

        self.assertTrue(
            any(polygon.covers(Point(0.3, 0.8)) for polygon in sea), "the bay was left as land"
        )


if __name__ == "__main__":
    unittest.main()
