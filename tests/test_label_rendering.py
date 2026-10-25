"""Both renderers draw the same labels, in one type, scaled with the sheet."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from shapely.geometry import LineString

from hipparchus.export.svg_clean import CleanSVGExporter
from hipparchus.rendering.models import LayerStyle, PlaceLabel, RGBAColor, RenderLayer, RenderScene
from hipparchus.rendering.skia_renderer import SkiaRenderer

BACKGROUND = RGBAColor(255, 255, 255)
NS = "{http://www.w3.org/2000/svg}"


def ground() -> RenderLayer:
    return RenderLayer(
        name="roads",
        geometries=[LineString([(0, 0), (100, 100)]), LineString([(0, 100), (100, 0)])],
        style=LayerStyle(stroke_width=0.5, stroke_color=RGBAColor(250, 250, 250), fill_enabled=False),
    )


def labelled(name: str, text: str, place_type: str = "", at=(50.0, 50.0), halo=2.0) -> RenderLayer:
    return RenderLayer(
        name=name,
        labels=[PlaceLabel(name=text, x=at[0], y=at[1], place_type=place_type)],
        style=LayerStyle(stroke_color=RGBAColor(0, 0, 0), label_halo_width=halo,
                         label_halo_color=RGBAColor(255, 255, 255)),
    )


def png(scene: RenderScene, size: int = 400) -> bytes:
    renderer = SkiaRenderer()
    renderer.set_scene(scene)
    return renderer.render_png(size, size)


def ink_box(data: bytes):
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("L")
    return image.point(lambda v: 255 if v < 100 else 0).getbbox()


def svg_root(scene: RenderScene, **kwargs):
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / "a.svg"
        CleanSVGExporter(**kwargs).export_scene(scene, target, width=400, height=400)
        return ElementTree.parse(target).getroot()


def label_texts(root, layer_id: str) -> list[str]:
    group = next((g for g in root.iter(f"{NS}g") if g.get("id") == f"{layer_id}_labels"), None)
    return [] if group is None else [t.text for t in group.findall(f"{NS}text") if t.get("stroke") == "none"]


class CanvasLabelTests(unittest.TestCase):
    def test_the_more_important_label_is_drawn_whatever_the_layer_order(self):
        both = RenderScene(
            layers=[ground(), labelled("shops", "Corner Shop"), labelled("places", "Miami", "city")],
            background=BACKGROUND,
        )
        city_only = RenderScene(layers=[ground(), labelled("places", "Miami", "city")], background=BACKGROUND)
        self.assertEqual(png(both), png(city_only))

    def test_label_type_scales_with_the_sheet(self):
        one = RenderScene(layers=[ground(), labelled("places", "Miami", "city", halo=0.0)], background=BACKGROUND)
        three = RenderScene(layers=[ground(), labelled("places", "Miami", "city", halo=0.0)],
                            background=BACKGROUND, label_scale=3.0)
        a, b = ink_box(png(one)), ink_box(png(three))
        self.assertGreater((b[2] - b[0]) / (a[2] - a[0]), 2.6)


class SvgLabelTests(unittest.TestCase):
    def test_overlapping_labels_are_not_both_written(self):
        scene = RenderScene(
            layers=[ground(), labelled("shops", "Corner Shop"), labelled("places", "Miami", "city")],
            background=BACKGROUND,
        )
        root = svg_root(scene)
        self.assertEqual(label_texts(root, "places"), ["Miami"])
        self.assertEqual(label_texts(root, "shops"), [])

    def test_svg_sets_the_configured_size_scaled_in_the_face_the_canvas_uses(self):
        from hipparchus.rendering.label_layout import LabelType

        scene = RenderScene(layers=[ground(), labelled("places", "Miami", "city", halo=2.5)],
                            background=BACKGROUND, label_scale=2.0)
        root = svg_root(scene)
        group = next(g for g in root.iter(f"{NS}g") if g.get("id") == "places_labels")
        halo, text = group.findall(f"{NS}text")
        self.assertEqual(float(text.get("font-size")), 20.0)
        self.assertEqual(float(halo.get("stroke-width")), 2.5)
        self.assertTrue(text.get("font-family").startswith(LabelType(10).face_name))
