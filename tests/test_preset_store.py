from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hipparchus.application.presets import default_preset
from hipparchus.application.preset_store import PresetStore


class PresetStoreTests(unittest.TestCase):
    def test_roundtrip_custom_preset(self) -> None:
        preset = default_preset("OSM Standard")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "presets.json"
            store = PresetStore(path)
            store.save({preset.name: preset})
            loaded = store.load()

        self.assertIn("OSM Standard", loaded)
        loaded_preset = loaded["OSM Standard"]
        self.assertEqual(loaded_preset.geometry_profile.derive_voronoi, preset.geometry_profile.derive_voronoi)
        self.assertIn("water", loaded_preset.style_profile.layer_styles)
        self.assertEqual(
            loaded_preset.style_profile.layer_styles["water"].fill_color.b,
            preset.style_profile.layer_styles["water"].fill_color.b,
        )

    def test_empty_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = PresetStore(Path(tmp) / "missing.json")

            loaded = store.load()

        self.assertEqual(loaded, {})


if __name__ == "__main__":
    unittest.main()
