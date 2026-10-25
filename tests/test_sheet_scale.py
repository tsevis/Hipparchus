"""Lines and labels keep their proportions on a bigger sheet."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from shapely.geometry import LineString

from hipparchus.application.sheet_scale import scaled_for_sheet, sheet_scale
from hipparchus.export.service import PNGExporter
from hipparchus.rendering.models import LayerStyle, RGBAColor, RenderLayer, RenderScene


class SheetScaleTests(unittest.TestCase):
    def test_the_default_canvas_and_anything_smaller_draw_as_before(self):
        self.assertEqual(sheet_scale(1024, 1024), 1.0)
        self.assertEqual(sheet_scale(800, 600), 1.0)
        self.assertEqual(sheet_scale(1, 1), 1.0)

    def test_three_times_the_canvas_edge_is_three_times_the_weight(self):
        self.assertAlmostEqual(sheet_scale(3072, 3072), 3.0)
        # Another shape is weighed by area, not by its long edge.
        self.assertAlmostEqual(sheet_scale(4096, 1024), 2.0)

    def test_nonsense_sizes_change_nothing(self):
        self.assertEqual(sheet_scale(0, 500), 1.0)
        self.assertEqual(sheet_scale(float("nan"), 500), 1.0)

    def test_scaled_scene_carries_strokes_casings_halos_and_type_scale(self):
        layer = RenderLayer(
            name="roads_primary",
            style=LayerStyle(stroke_width=3.0, casing_width=5.0, label_halo_width=2.0),
        )
        scene = RenderScene(layers=[layer])
        big = scaled_for_sheet(scene, 3072, 3072)
        style = big.layers[0].style
        self.assertEqual((style.stroke_width, style.casing_width, style.label_halo_width), (9.0, 15.0, 6.0))
        self.assertEqual(big.label_scale, 3.0)
        # The original is untouched: the window keeps drawing at its own size.
        self.assertEqual(scene.layers[0].style.stroke_width, 3.0)
        self.assertEqual(scene.label_scale, 1.0)


def road_width_in_png(size: int) -> int:
    from PIL import Image

    layer = RenderLayer(
        name="roads_primary",
        geometries=[LineString([(0, -50), (0, 50)]), LineString([(-50, 0), (50, 0)])],
        style=LayerStyle(stroke_width=4.0, stroke_color=RGBAColor(255, 0, 0), fill_enabled=False),
    )
    scene = RenderScene(layers=[layer], background=RGBAColor(255, 255, 255))
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "a.png"
        PNGExporter(scene=scene, width=size, height=size).export(target)
        image = Image.open(target).convert("RGB")
    row = size // 4  # crosses only the vertical road
    return sum(1 for x in range(size) if image.getpixel((x, row)) != (255, 255, 255)
               and image.getpixel((x, row))[1] < 128)


class ExportedWeightTests(unittest.TestCase):
    def test_a_png_three_times_the_canvas_draws_roads_three_times_as_wide(self):
        small = road_width_in_png(1024)
        large = road_width_in_png(3072)
        self.assertGreaterEqual(large, small * 3 - 2)
