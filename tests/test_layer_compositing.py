"""How a layer's parts reach the canvas, and how its opacity is applied.

Two bugs, one visible symptom. Rendering Cyprus from both apps with the same
preset and the same sheet gave a warm tan island on the macOS port and a pale
grey one here, with byte-identical band colours in both.

1. `_clip_geometries` flattened every MultiPolygon into its parts. The terrain
   provider emits **one** feature per elevation band; clipping turned ten bands
   into 248 loose polygons.
2. `skia_renderer` folded the layer's opacity into each part's alpha, so those
   248 parts composited against *each other* rather than as one layer.

The port does neither: it keeps ten multipolygons and puts `opacity="0.9"` on
the SVG group, which is what "this layer is 90% opaque" means, and what SVG and
PDF do. These tests hold this app to the same two rules.
"""

from __future__ import annotations

import unittest

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    box,
)

from hipparchus.application.scene_sea import _clip_geometries


def _square(x: float, y: float, size: float = 1.0) -> Polygon:
    return box(x, y, x + size, y + size)


class ClipKeepsPartsTogetherTests(unittest.TestCase):
    """A multi-part geometry is one geometry, and must survive clipping as one."""

    def test_a_multipolygon_inside_the_box_stays_one_geometry(self) -> None:
        bands = MultiPolygon([_square(0, 0), _square(3, 3)])
        clipped = _clip_geometries([bands], box(-10, -10, 10, 10))
        self.assertEqual(len(clipped), 1)
        self.assertIsInstance(clipped[0], MultiPolygon)

    def test_a_multipolygon_clipped_in_half_is_still_one_geometry(self) -> None:
        """Losing a part must not promote the survivors to separate layers."""
        bands = MultiPolygon([_square(0, 0), _square(20, 20)])
        clipped = _clip_geometries([bands], box(-10, -10, 10, 10))
        self.assertEqual(len(clipped), 1)

    def test_the_geometry_that_survives_is_the_clipped_one(self) -> None:
        big = MultiPolygon([_square(0, 0, size=100)])
        clipped = _clip_geometries([big], box(0, 0, 10, 10))
        self.assertLess(clipped[0].area, big.area)
        self.assertAlmostEqual(clipped[0].area, 100.0)

    def test_ten_bands_stay_ten_geometries(self) -> None:
        """The case that started this: 10 elevation bands became 248 parts."""
        bands = [
            MultiPolygon([_square(i, j) for j in range(5)])
            for i in range(10)
        ]
        clipped = _clip_geometries(bands, box(-10, -10, 100, 100))
        self.assertEqual(len(clipped), 10)

    def test_a_multilinestring_stays_together_too(self) -> None:
        lines = MultiLineString([[(0, 0), (1, 1)], [(3, 3), (4, 4)]])
        clipped = _clip_geometries([lines], box(-10, -10, 10, 10))
        self.assertEqual(len(clipped), 1)

    def test_a_plain_polygon_is_unaffected(self) -> None:
        clipped = _clip_geometries([_square(0, 0)], box(-10, -10, 10, 10))
        self.assertEqual(len(clipped), 1)
        self.assertIsInstance(clipped[0], Polygon)

    def test_a_geometry_entirely_outside_the_box_is_dropped(self) -> None:
        self.assertEqual(_clip_geometries([_square(50, 50)], box(0, 0, 10, 10)), [])

    def test_an_empty_geometry_is_dropped(self) -> None:
        self.assertEqual(_clip_geometries([Polygon()], box(0, 0, 10, 10)), [])


class ClipDiscardsTheWrongDimensionTests(unittest.TestCase):
    """Clipping a polygon against a box can hand back a point or a line where the
    two only touch. Those are artefacts of the cut, not content: drawing them
    puts specks along the frame edge."""

    def test_a_collection_keeps_only_the_dimension_that_was_asked_for(self) -> None:
        touching = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        clipped = _clip_geometries([touching], box(-5, -5, 5, 5))
        for geom in clipped:
            self.assertIn(geom.geom_type, ("Polygon", "MultiPolygon"))

    def test_a_polygon_touching_the_box_at_one_edge_yields_nothing(self) -> None:
        """The intersection is a line, which is not a polygon and not drawable."""
        adjacent = box(10, 0, 20, 10)
        clipped = _clip_geometries([adjacent], box(0, 0, 10, 10))
        self.assertEqual([g for g in clipped if g.area > 0], [])

    def test_a_line_layer_keeps_its_lines(self) -> None:
        line = LineString([(-5, 5), (15, 5)])
        clipped = _clip_geometries([line], box(0, 0, 10, 10))
        self.assertEqual(len(clipped), 1)
        self.assertIn(clipped[0].geom_type, ("LineString", "MultiLineString"))

    def test_a_point_layer_keeps_its_points(self) -> None:
        clipped = _clip_geometries([Point(5, 5)], box(0, 0, 10, 10))
        self.assertEqual(len(clipped), 1)
        self.assertEqual(clipped[0].geom_type, "Point")

    def test_a_geometry_collection_input_is_still_handled(self) -> None:
        mixed = GeometryCollection([_square(1, 1), LineString([(2, 2), (3, 3)])])
        clipped = _clip_geometries([mixed], box(0, 0, 10, 10))
        self.assertTrue(clipped)


class LayerOpacityIsAGroupTests(unittest.TestCase):
    """Opacity belongs to the layer, not to each part of it.

    Folded into per-feature alpha, two overlapping parts of one layer blend
    against each other and the seam between them reads darker than either. The
    port composites the group once, which is what SVG and PDF do and what the
    word means.
    """

    def test_the_renderer_no_longer_folds_opacity_into_feature_colours(self) -> None:
        """`with_opacity` on a layer's own stroke/fill is the bug's signature."""
        import inspect

        from hipparchus.rendering import skia_renderer

        source = inspect.getsource(skia_renderer.SkiaRenderer._draw_vector_layers)
        self.assertNotIn("stroke_color.with_opacity(layer.style.opacity)", source)
        self.assertNotIn("fill_color.with_opacity(layer.style.opacity)", source)

    def test_the_renderer_composites_each_layer_as_a_group(self) -> None:
        import inspect

        from hipparchus.rendering import skia_renderer

        source = inspect.getsource(skia_renderer.SkiaRenderer._draw_vector_layers)
        self.assertIn("saveLayerAlpha", source)


if __name__ == "__main__":
    unittest.main()
