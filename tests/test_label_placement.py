"""Which labels a sheet gets: ranked, measured, turned, and kept on the canvas."""

from __future__ import annotations

import unittest

from hipparchus.application.label_placement import LabelSpec, place_labels


def spec(key, layer="street_names", place_type="", x=100.0, y=100.0, width=80.0, size=10.0,
         halo=2.0, rotation=0.0):
    return LabelSpec(key, layer, place_type, x, y, width, size, halo, rotation)


class PlacementTests(unittest.TestCase):
    def test_a_label_touching_a_placed_one_is_dropped(self):
        # 80 wide + 2 halo: boxes at x=100 and x=182 touch exactly at 141..141.
        kept = place_labels([spec("a", x=100), spec("b", x=182)], 400, 200)
        self.assertEqual(kept, ["a"])

    def test_a_label_clear_of_the_others_is_kept(self):
        kept = place_labels([spec("a", x=100), spec("b", x=190)], 400, 200)
        self.assertEqual(kept, ["a", "b"])

    def test_the_more_important_label_wins_whatever_the_layer_order(self):
        specs = [
            spec("shop", layer="shops", x=100),
            spec("street", layer="street_names", x=100),
            spec("town", layer="places", place_type="town", x=100),
            spec("city", layer="places", place_type="city", x=100),
        ]
        self.assertEqual(place_labels(specs, 400, 200), ["city"])

    def test_rank_runs_places_summits_streets_amenities_shops_rest(self):
        names = ["other", "shops", "amenities", "street_names", "summits", "places"]
        specs = [spec(n, layer=n, x=60 + 100 * i) for i, n in enumerate(names)]
        # All clear of each other: order of the result is the rank order.
        self.assertEqual(
            place_labels(specs, 1000, 200),
            ["places", "summits", "street_names", "amenities", "shops", "other"],
        )

    def test_a_label_the_canvas_edge_would_cut_is_dropped(self):
        self.assertEqual(place_labels([spec("a", x=20), spec("b", x=200)], 400, 200), ["b"])
        self.assertEqual(place_labels([spec("a", y=395), spec("b", y=100)], 400, 400), ["b"])

    def test_two_names_along_a_diagonal_street_do_not_claim_each_others_square(self):
        # Upright, these two boxes overlap; turned with their street (45 degrees)
        # the second lies a whole street-width beside the first.
        a = spec("a", x=150, y=150, width=100, rotation=45)
        b = spec("b", x=210, y=155, width=100, rotation=45)
        self.assertEqual(place_labels([a, b], 400, 400), ["a", "b"])

    def test_turned_boxes_that_do_cross_still_collide(self):
        a = spec("a", x=150, y=150, width=100, rotation=45)
        b = spec("b", x=150 + 30, y=150 + 30, width=100, rotation=45)
        self.assertEqual(place_labels([a, b], 400, 400), ["a"])
