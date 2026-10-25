"""Clean Atlas roads carry a whole-pixel edge in a darker shade of their own colour."""

from __future__ import annotations

import unittest

from hipparchus.application.presets import _clean_atlas_styles, _soft_urban_styles
from hipparchus.rendering.models import RGBAColor

CLASSED = ("roads_motorway", "roads_trunk", "roads_primary", "roads_secondary", "roads_tertiary")


def shade(colour: RGBAColor) -> tuple[int, int, int]:
    return (round(colour.r * 0.78), round(colour.g * 0.78), round(colour.b * 0.78))


class CleanAtlasRoadEdgeTests(unittest.TestCase):
    def test_each_coloured_road_has_a_one_pixel_edge_in_its_own_darker_shade(self):
        for styles in (_clean_atlas_styles(), _soft_urban_styles()):
            for name in CLASSED:
                style = styles[name]
                with self.subTest(name=name):
                    self.assertAlmostEqual(style.casing_width, style.stroke_width + 2.0)
                    c = style.casing_color
                    self.assertEqual((c.r, c.g, c.b), shade(style.stroke_color))

    def test_service_road_is_white_with_a_grey_edge(self):
        service = _clean_atlas_styles()["roads_service"]
        self.assertEqual(service.stroke_width, 1.3)
        self.assertEqual(service.casing_width, 2.9)
        self.assertEqual(service.stroke_color, RGBAColor(250, 249, 245))
        self.assertEqual(service.casing_color, RGBAColor(205, 200, 190))
