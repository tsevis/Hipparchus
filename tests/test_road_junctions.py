"""Roads meet as one network: minor to major, every casing before any line."""

from __future__ import annotations

import io
import unittest

from shapely.geometry import LineString

from hipparchus.application.scene_builder import _ordered_layers
from hipparchus.rendering.models import LayerStyle, RGBAColor, RenderLayer, RenderScene
from hipparchus.rendering.skia_renderer import SkiaRenderer

EDGE = RGBAColor(10, 10, 10)
ORANGE = RGBAColor(240, 140, 40)
WHITE = RGBAColor(255, 255, 255)


def road(name, line, colour, width, casing_width):
    return RenderLayer(
        name=name,
        geometries=[line],
        style=LayerStyle(
            stroke_width=width, stroke_color=colour, fill_enabled=False,
            casing_width=casing_width, casing_color=EDGE, line_cap="round",
        ),
    )


def pixel_near(scene: RenderScene, dx: float, dy: float, size: int = 400):
    """The pixel dx, dy screen pixels from the world origin."""
    from PIL import Image

    renderer = SkiaRenderer()
    renderer.set_scene(scene)
    data = renderer.render_png(size, size)
    sx, sy = renderer.world_to_screen(0, 0, size, size)
    image = Image.open(io.BytesIO(data)).convert("RGB")
    return image.getpixel((round(sx + dx), round(sy + dy)))


class RoadOrderTests(unittest.TestCase):
    def test_roads_draw_minor_to_major(self):
        names = ["roads_motorway", "roads_residential", "roads", "roads_secondary", "roads_service"]
        self.assertEqual(
            _ordered_layers(names),
            ["roads", "roads_service", "roads_residential", "roads_secondary", "roads_motorway"],
        )


class JunctionTests(unittest.TestCase):
    def scene(self) -> RenderScene:
        major = road("roads_secondary", LineString([(-50, 0), (50, 0)]), ORANGE, 12, 20)
        minor = road("roads_residential", LineString([(0, -50), (0, 50)]), WHITE, 4, 8)
        # The order the scene builder now produces: minor first.
        return RenderScene(layers=[minor, major], background=RGBAColor(200, 200, 200))

    def test_minor_line_meets_the_major_line_through_its_casing(self):
        """The residential line has to reach the secondary road's line.

        Drawn layer by layer, the secondary casing lands on top of the
        residential line and cuts it. Eight pixels above the junction centre
        lies between the secondary line's edge (6) and its casing's edge (10),
        exactly on the residential line: it must read white, not casing.
        """
        self.assertEqual(pixel_near(self.scene(), 0, -8), (255, 255, 255))


class SvgJunctionTests(unittest.TestCase):
    def test_every_casing_group_precedes_every_road_line_group(self):
        import tempfile
        from pathlib import Path
        from xml.etree import ElementTree

        from hipparchus.export.svg_clean import CleanSVGExporter

        minor = road("roads_residential", LineString([(0, -50), (0, 50)]), WHITE, 4, 8)
        major = road("roads_secondary", LineString([(-50, 0), (50, 0)]), ORANGE, 12, 20)
        major.style.opacity = 0.5
        hidden = road("roads_service", LineString([(5, 5), (9, 9)]), WHITE, 2, 4)
        hidden.style.visible = False
        scene = RenderScene(layers=[hidden, minor, major])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "a.svg"
            CleanSVGExporter().export_scene(scene, target, width=400, height=400)
            root = ElementTree.parse(target).getroot()
        ns = "{http://www.w3.org/2000/svg}"
        group = next(g for g in root.iter(f"{ns}g") if g.get("id") == "map_layers")
        ids = [g.get("id") for g in group.findall(f"{ns}g")]
        self.assertEqual(
            ids,
            ["roads_service_casing", "roads_residential_casing", "roads_secondary_casing",
             "roads_service", "roads_residential", "roads_secondary"],
        )
        by_id = {g.get("id"): g for g in group.findall(f"{ns}g")}
        self.assertEqual(by_id["roads_secondary_casing"].get("opacity"), "0.5")
        self.assertEqual(by_id["roads_service_casing"].get("display"), "none")
