from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hipparchus.core.project_state import AOIState, ProjectState


class ProjectStateTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        project = ProjectState(
            project_name="demo",
            aoi=AOIState(min_lon=1.0, min_lat=2.0, max_lon=3.0, max_lat=4.0),
            active_layers=["roads", "buildings"],
            preset_name="Urban Structure",
            quality_mode="preview",
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "demo.hipparchus.json"
            project.save(path)
            loaded = ProjectState.load(path)

        self.assertEqual(loaded.project_name, project.project_name)
        self.assertEqual(loaded.aoi.max_lon, 3.0)
        self.assertEqual(loaded.preset_name, "Urban Structure")

    def test_loads_legacy_preset_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.hipparchus.json"
            path.write_text(
                """
{
  "project_name": "legacy",
  "aoi": {"min_lon": 1.0, "min_lat": 2.0, "max_lon": 3.0, "max_lat": 4.0},
  "active_layers": ["roads"],
  "preset_name": "Mask Structural",
  "quality_mode": "preview",
  "export_mode": "cgmcreator_mask"
}
""".strip(),
                encoding="utf-8",
            )

            loaded = ProjectState.load(path)

        self.assertEqual(loaded.preset_name, "Urban Structure")


if __name__ == "__main__":
    unittest.main()
