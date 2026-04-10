from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from shapely.geometry import LineString

from hipparchus.export.profiles import SVGExportProfile
from hipparchus.export.service import SVGExporter
from hipparchus.rendering.models import LayerStyle, RenderLayer, RenderScene


class ExportProfileTests(unittest.TestCase):
    def test_writes_diagnostics(self) -> None:
        scene = RenderScene(
            layers=[RenderLayer(name="roads", geometries=[LineString([(0, 0), (1, 1)])], style=LayerStyle(fill_enabled=False))]
        )
        exporter = SVGExporter(scene=scene, width=128, height=128)

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "out.svg"
            diagnostics = exporter.export_with_profile(path, SVGExportProfile(mode="clean", include_diagnostics=True))
            diag_path = Path(str(path) + ".diagnostics.json")

            self.assertTrue(path.exists())
            self.assertTrue(diag_path.exists())
            self.assertGreaterEqual(diagnostics.total_paths, 1)


if __name__ == "__main__":
    unittest.main()
