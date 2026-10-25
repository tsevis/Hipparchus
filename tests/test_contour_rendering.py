"""Contour linework must survive the scene and export path, not just the provider."""

from __future__ import annotations

import unittest

from pathlib import Path
import tempfile

from hipparchus.application.presets import default_preset, preset_names
from hipparchus.application.scene_builder import RenderSceneBuilder, _ordered_layers
from shapely.geometry import LineString

from hipparchus.data_sources.provider import BBoxQuery, FeatureCollection
from dataclasses import replace

from hipparchus.data_sources.simulated_field import (
    DENSE_RELIEF_SETTINGS,
    TerrainFieldSettings,
    simulated_terrain_provider,
)
from hipparchus.export.svg_clean import CleanSVGExporter
from hipparchus.geometry.smoothing import smoothing_rule_for_layer
from hipparchus.rendering.models import RGBAColor, RenderLayer


CONTOUR_PRESET = "Contour Study"
ATHENS = BBoxQuery(min_lon=23.70, min_lat=37.95, max_lon=23.80, max_lat=38.02)


def _scene(preset_name: str = CONTOUR_PRESET):
    provider = simulated_terrain_provider(TerrainFieldSettings(grid_size=96, seed=7))
    collection = provider.fetch_bbox(ATHENS)
    preset = default_preset(preset_name)
    return RenderSceneBuilder().build(
        collection,
        preset.geometry_profile,
        preset.style_profile,
        "preview",
    )


class ContourPresetTests(unittest.TestCase):
    def test_contour_study_is_registered(self) -> None:
        self.assertIn(CONTOUR_PRESET, preset_names())

    def test_contour_study_styles_both_contour_layers(self) -> None:
        styles = default_preset(CONTOUR_PRESET).style_profile.layer_styles
        self.assertIn("terrain_contours", styles)
        self.assertIn("terrain_index_contours", styles)

    def test_index_contours_are_heavier_than_minor_ones(self) -> None:
        for preset_name in (CONTOUR_PRESET, "Terrain Study"):
            styles = default_preset(preset_name).style_profile.layer_styles
            with self.subTest(preset=preset_name):
                self.assertGreater(
                    styles["terrain_index_contours"].stroke_width,
                    styles["terrain_contours"].stroke_width,
                )


class ReliefSheetPresetTests(unittest.TestCase):
    """The dense sheet carries depth in line density, not in weight or accent."""

    def test_the_preset_is_registered(self) -> None:
        self.assertIn("Relief Sheet", preset_names())

    def test_every_contour_line_is_drawn_the_same(self) -> None:
        styles = default_preset("Relief Sheet").style_profile.layer_styles
        self.assertEqual(
            styles["terrain_contours"].stroke_width,
            styles["terrain_index_contours"].stroke_width,
        )
        self.assertEqual(styles["terrain_contours"].stroke_color, styles["terrain_index_contours"].stroke_color)

    def test_illumination_is_off(self) -> None:
        """Varying weight and varying density are two different depth cues."""
        styles = default_preset("Relief Sheet").style_profile.layer_styles
        self.assertEqual(styles["terrain_contours"].illumination, 0.0)

    def test_the_dense_profile_asks_for_far_more_lines(self) -> None:
        self.assertGreater(DENSE_RELIEF_SETTINGS.target_line_count, TerrainFieldSettings().target_line_count * 3)
        self.assertGreater(DENSE_RELIEF_SETTINGS.grid_size, TerrainFieldSettings().grid_size)

    def test_the_dense_profile_accents_nothing(self) -> None:
        collection = simulated_terrain_provider(
            replace(DENSE_RELIEF_SETTINGS, grid_size=96, target_line_count=40)
        ).fetch_bbox(ATHENS)
        self.assertTrue(collection.features_by_layer["terrain_contours"])
        self.assertEqual(collection.features_by_layer["terrain_index_contours"], [])


class MonochromeFigureGroundTests(unittest.TestCase):
    """Relief in this preset carries weight along the line, not one flat width.

    A blanket rule sets every layer to a single stroke and a third opacity;
    contours must be lifted back out of it or relief reads as grey haze.
    """

    PRESET = "Monochrome Figure Ground"

    def _styles(self):
        return default_preset(self.PRESET).style_profile.layer_styles

    def test_contours_are_illuminated(self) -> None:
        for layer in ("terrain_contours", "terrain_index_contours"):
            with self.subTest(layer=layer):
                self.assertGreater(self._styles()[layer].illumination, 0.0)

    def test_the_weight_range_is_wide_enough_to_see(self) -> None:
        for layer in ("terrain_contours", "terrain_index_contours"):
            with self.subTest(layer=layer):
                style = self._styles()[layer]
                self.assertGreater(style.illumination_shadow_scale, style.illumination_lit_scale * 3)

    def test_contours_are_not_left_at_the_blanket_opacity(self) -> None:
        for layer in ("terrain_contours", "terrain_index_contours"):
            with self.subTest(layer=layer):
                self.assertGreater(self._styles()[layer].opacity, 0.8)

    def test_a_rendered_scene_carries_varied_weights(self) -> None:
        scene = _scene(self.PRESET)
        by_name = {layer.name: layer for layer in scene.layers}
        for layer in ("terrain_contours", "terrain_index_contours"):
            with self.subTest(layer=layer):
                weights = by_name[layer].weights
                self.assertEqual(len(weights), len(by_name[layer].geometries))
                self.assertGreater(len(set(weights)), 2, "relief drawn at one flat weight")

    def test_the_figure_ground_character_is_intact(self) -> None:
        """Buildings still read as solid figure against open ground."""
        styles = self._styles()
        self.assertTrue(styles["buildings"].fill_enabled)
        self.assertEqual(styles["roads_residential"].stroke_color, RGBAColor(255, 255, 255))


class ContourSceneTests(unittest.TestCase):
    def test_contours_reach_the_scene_as_drawable_layers(self) -> None:
        scene = _scene()
        by_name = {layer.name: layer for layer in scene.layers}
        self.assertTrue(by_name["terrain_contours"].geometries)
        self.assertTrue(by_name["terrain_index_contours"].geometries)

    def test_contours_draw_under_the_built_environment(self) -> None:
        order = _ordered_layers({"buildings", "terrain_contours", "terrain_index_contours", "water", "roads"})
        self.assertLess(order.index("water"), order.index("terrain_contours"))
        self.assertLess(order.index("terrain_contours"), order.index("terrain_index_contours"))
        self.assertLess(order.index("terrain_index_contours"), order.index("buildings"))

    def test_contours_are_smoothed_like_other_linework(self) -> None:
        for layer in ("terrain_contours", "terrain_index_contours"):
            with self.subTest(layer=layer):
                rule = smoothing_rule_for_layer(layer, 2)
                self.assertEqual(rule.iterations, 2)
                self.assertFalse(rule.smooth_polygons)

    def test_scene_declares_the_map_as_synthetic(self) -> None:
        self.assertTrue(_scene().metadata["synthetic"])


class IlluminatedSceneTests(unittest.TestCase):
    def test_contour_layers_carry_per_geometry_weights(self) -> None:
        scene = _scene()
        by_name = {layer.name: layer for layer in scene.layers}
        for name in ("terrain_contours", "terrain_index_contours"):
            with self.subTest(layer=name):
                layer = by_name[name]
                self.assertEqual(len(layer.weights), len(layer.geometries))
                self.assertGreater(len(set(layer.weights)), 1, "an unlit sheet reads flat")

    def test_weight_lookup_falls_back_to_uniform(self) -> None:
        plain = RenderLayer(name="roads", geometries=[LineString([(0, 0), (1, 1)])])
        self.assertEqual(plain.weight_at(0), 1.0)
        self.assertEqual(plain.weight_at(99), 1.0)

    def test_an_unlit_preset_leaves_weights_empty(self) -> None:
        scene = _scene("Terrain Study")
        by_name = {layer.name: layer for layer in scene.layers}
        self.assertEqual(by_name["terrain_contours"].weights, [])

    def test_illuminated_layers_are_reported_in_diagnostics(self) -> None:
        self.assertIn("terrain_contours", _scene().diagnostics["illuminated_layers"])


class StreetLabelTests(unittest.TestCase):
    @staticmethod
    def _roads(*named: tuple[str, list[tuple[float, float]]]) -> FeatureCollection:
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": [list(point) for point in coordinates]},
                "properties": {"name": name, "highway": "residential"},
            }
            for name, coordinates in named
        ]
        return FeatureCollection(
            features_by_layer={"roads": features},
            geojson_by_layer={"roads": {"type": "FeatureCollection", "features": features}},
            metadata={"source": "test"},
            bbox=(0.0, 0.0, 1.0, 1.0),
        )

    def _scene_for(self, collection: FeatureCollection):
        preset = default_preset("Urban Structure")
        return RenderSceneBuilder().build(collection, preset.geometry_profile, preset.style_profile, "preview")

    def test_named_streets_become_labels(self) -> None:
        scene = self._scene_for(self._roads(("Odos Ermou", [(0.1, 0.1), (0.4, 0.4)])))
        labels = {layer.name: layer.labels for layer in scene.layers}
        self.assertEqual([label.name for label in labels["street_names"]], ["Odos Ermou"])
        self.assertEqual(labels["street_names"][0].place_type, "street")

    def test_a_street_split_into_blocks_is_labelled_once(self) -> None:
        """OSM splits a street per block; labelling each one carpets the map."""
        scene = self._scene_for(
            self._roads(
                ("High Street", [(0.1, 0.1), (0.2, 0.1)]),
                ("High Street", [(0.2, 0.1), (0.8, 0.1)]),
                ("High Street", [(0.8, 0.1), (0.9, 0.1)]),
            )
        )
        labels = [layer.labels for layer in scene.layers if layer.name == "street_names"][0]
        self.assertEqual(len(labels), 1)

    def _only_street_label(self, collection: FeatureCollection):
        layers = [layer for layer in self._scene_for(collection).layers if layer.name == "street_names"]
        return layers[0].labels[0]

    def test_the_label_sits_on_the_longest_run_of_that_street(self) -> None:
        short_north = ("High Street", [(0.10, 0.90), (0.12, 0.90)])
        long_south = ("High Street", [(0.20, 0.10), (0.80, 0.10)])

        both = self._only_street_label(self._roads(short_north, long_south))
        south_only = self._only_street_label(self._roads(long_south))
        north_only = self._only_street_label(self._roads(short_north))

        # Same AOI in all three, so the projection is comparable: the label
        # lands on the long southern run, not the short northern one.
        self.assertAlmostEqual(both.y, south_only.y, places=6)
        self.assertNotAlmostEqual(both.y, north_only.y, places=6)

    def test_a_street_name_turns_with_its_street(self) -> None:
        rising = self._only_street_label(self._roads(("Odos A", [(0.2, 0.2), (0.6, 0.6)])))
        flat = self._only_street_label(self._roads(("Odos B", [(0.2, 0.5), (0.7, 0.5)])))
        self.assertAlmostEqual(flat.rotation, 0.0, places=3)
        # Up and to the right on the map is up and to the right on the canvas:
        # counter-clockwise, which is negative where angles run clockwise.
        self.assertLess(rising.rotation, -30.0)
        self.assertGreater(rising.rotation, -60.0)

    def test_unnamed_roads_produce_no_labels(self) -> None:
        collection = self._roads(("", [(0.1, 0.1), (0.4, 0.4)]))
        scene = self._scene_for(collection)
        self.assertNotIn("street_names", {layer.name for layer in scene.layers})

    def test_a_map_without_roads_has_no_street_layer(self) -> None:
        self.assertNotIn("street_names", {layer.name for layer in _scene().layers})


class HypsometricBandTests(unittest.TestCase):
    """Band colour comes from a property the geometry pipeline drops, so the
    pairing between a band and its colour is the thing worth testing."""

    @staticmethod
    def _bands(count: int = 4) -> FeatureCollection:
        features = []
        for index in range(count):
            inset = index * 0.05
            ring = [
                [0.1 + inset, 0.1 + inset],
                [0.9 - inset, 0.1 + inset],
                [0.9 - inset, 0.9 - inset],
                [0.1 + inset, 0.9 - inset],
                [0.1 + inset, 0.1 + inset],
            ]
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": [ring]},
                    "properties": {
                        "elevation_low": index * 100.0,
                        "elevation_high": (index + 1) * 100.0,
                        "band_index": index,
                        "band_count": count,
                        "hipparchus_layer": "elevation_bands",
                    },
                }
            )
        return FeatureCollection(
            features_by_layer={"elevation_bands": features},
            geojson_by_layer={"elevation_bands": {"type": "FeatureCollection", "features": features}},
            metadata={"source": "test"},
            bbox=(0.0, 0.0, 1.0, 1.0),
        )

    def _scene(self, preset_name: str = "Hypsometric Relief", count: int = 4):
        preset = default_preset(preset_name)
        return RenderSceneBuilder().build(
            self._bands(count), preset.geometry_profile, preset.style_profile, "preview"
        )

    @staticmethod
    def _band_layer(scene):
        return next(layer for layer in scene.layers if layer.name == "elevation_bands")

    def test_the_preset_is_registered_with_a_ramp(self) -> None:
        self.assertIn("Hypsometric Relief", preset_names())
        style = default_preset("Hypsometric Relief").style_profile.layer_styles["elevation_bands"]
        self.assertIsNotNone(style.fill_color_high)
        self.assertNotEqual(style.fill_color, style.fill_color_high)

    def test_every_band_gets_its_own_fill(self) -> None:
        layer = self._band_layer(self._scene())
        self.assertEqual(len(layer.fill_colors), len(layer.geometries))
        self.assertGreater(len(set(layer.fill_colors)), 1)

    def test_the_ramp_runs_low_to_high(self) -> None:
        layer = self._band_layer(self._scene())
        style = layer.style
        self.assertEqual(layer.fill_colors[0], style.fill_color)
        self.assertEqual(layer.fill_colors[-1], style.fill_color_high)

    def test_a_layer_without_bands_keeps_one_fill(self) -> None:
        plain = RenderLayer(name="water", geometries=[LineString([(0, 0), (1, 1)])])
        self.assertEqual(plain.fill_color_at(0), plain.style.fill_color)

    def test_a_single_band_does_not_divide_by_zero(self) -> None:
        layer = self._band_layer(self._scene(count=1))
        self.assertEqual(len(layer.fill_colors), len(layer.geometries))

    def test_bands_export_with_their_own_fills(self) -> None:
        scene = self._scene()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bands.svg"
            CleanSVGExporter(precision=2).export_scene(scene, out, width=400, height=400)
            data = out.read_text(encoding="utf-8")
        self.assertIn('<g id="elevation_bands"', data)
        style = default_preset("Hypsometric Relief").style_profile.layer_styles["elevation_bands"]
        low = f"#{style.fill_color.r:02x}{style.fill_color.g:02x}{style.fill_color.b:02x}"
        high = f"#{style.fill_color_high.r:02x}{style.fill_color_high.g:02x}{style.fill_color_high.b:02x}"
        self.assertIn(low, data)
        self.assertIn(high, data)


class ContourExportTests(unittest.TestCase):
    def test_svg_export_groups_the_contour_layers_separately(self) -> None:
        """Minor and index lines must land in their own Illustrator groups."""
        scene = _scene()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "contours.svg"
            diagnostics = CleanSVGExporter(precision=2).export_scene(scene, out, width=800, height=800)
            data = out.read_text(encoding="utf-8")

        self.assertIn('<g id="terrain_contours"', data)
        self.assertIn('<g id="terrain_index_contours"', data)
        self.assertTrue(diagnostics.source_metadata["synthetic"])


if __name__ == "__main__":
    unittest.main()
