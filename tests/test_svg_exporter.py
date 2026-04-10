from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shapely.geometry import LineString, Polygon

from hipparchus.export.svg_clean import CleanSVGExporter
from hipparchus.rendering.models import LayerStyle, RGBAColor, RenderLayer, RenderScene


class SVGExporterTests(unittest.TestCase):
    def test_exports_layered_svg_paths(self) -> None:
        roads = RenderLayer(
            name="roads",
            geometries=[LineString([(0, 0), (10, 10)])],
            style=LayerStyle(stroke_width=2.0, stroke_color=RGBAColor(255, 0, 0), fill_enabled=False),
        )
        parks = RenderLayer(
            name="parks",
            geometries=[Polygon([(0, 0), (10, 0), (10, 10), (0, 0)])],
            style=LayerStyle(fill_enabled=True, fill_color=RGBAColor(0, 255, 0), opacity=0.6),
        )
        scene = RenderScene(layers=[roads, parks])

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "map.svg"
            CleanSVGExporter(precision=2).export_scene(scene, out, width=100, height=100)
            data = out.read_text(encoding="utf-8")

        self.assertIn('<g id="roads"', data)
        self.assertIn('<g id="parks"', data)
        self.assertIn("vector-effect=\"non-scaling-stroke\"", data)
        self.assertIn("#ff0000", data)
        self.assertIn("#00ff00", data)


if __name__ == "__main__":
    unittest.main()
