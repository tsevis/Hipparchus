from __future__ import annotations

from dataclasses import replace
import unittest

from hipparchus.application.layer_inventory import LAYER_LABELS, _GROUPS
from hipparchus.application.presets import GeometryPipelineProfile, StyleProfile, default_preset
from hipparchus.application.scene_builder import (
    PREFERRED_LAYER_ORDER,
    RenderSceneBuilder,
    _ordered_layers,
    _raise_relief_over_the_built_environment,
)
from hipparchus.data_sources.provider import FeatureCollection
from hipparchus.rendering.models import RenderLayer


class RenderSceneBuilderTests(unittest.TestCase):
    def test_build_generates_base_layers_without_experimental_derivatives(self) -> None:
        fc = FeatureCollection(
            geojson_by_layer={
                "roads": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 10]]},
                            "properties": {},
                        },
                        {
                            "type": "Feature",
                            "geometry": {"type": "LineString", "coordinates": [[0, 10], [10, 0]]},
                            "properties": {},
                        },
                    ],
                },
                "buildings": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[[2, 2], [4, 2], [4, 4], [2, 2]]],
                            },
                            "properties": {},
                        },
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[[6, 6], [8, 6], [8, 8], [6, 6]]],
                            },
                            "properties": {},
                        },
                    ],
                },
                "water": {"type": "FeatureCollection", "features": []},
                "parks": {"type": "FeatureCollection", "features": []},
                "railways": {"type": "FeatureCollection", "features": []},
            }
        )

        preset = default_preset("Urban Structure")
        scene = RenderSceneBuilder().build(fc, preset.geometry_profile, preset.style_profile, "preview")
        names = [layer.name for layer in scene.layers]

        road_names = {"roads", "roads_motorway", "roads_trunk", "roads_primary", "roads_secondary",
                      "roads_tertiary", "roads_residential", "roads_service", "roads_other"}
        self.assertTrue(any(name in road_names for name in names), f"Expected road layer in {names}")
        self.assertIn("buildings", names)
        self.assertNotIn("voronoi_cells", names)

    def test_derived_layers_remain_available_for_future_experimental_mode(self) -> None:
        fc = FeatureCollection(
            geojson_by_layer={
                "roads": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 10]]},
                            "properties": {},
                        },
                        {
                            "type": "Feature",
                            "geometry": {"type": "LineString", "coordinates": [[0, 10], [10, 0]]},
                            "properties": {},
                        },
                    ],
                },
                "buildings": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[[2, 2], [4, 2], [4, 4], [2, 2]]],
                            },
                            "properties": {},
                        },
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[[6, 6], [8, 6], [8, 8], [6, 6]]],
                            },
                            "properties": {},
                        },
                    ],
                },
            },
            bbox=(0.0, 0.0, 10.0, 10.0),
        )

        preset = default_preset("Urban Structure")
        experimental_profile = GeometryPipelineProfile(
            simplify_tolerance_preview=preset.geometry_profile.simplify_tolerance_preview,
            simplify_tolerance_export=preset.geometry_profile.simplify_tolerance_export,
            derive_voronoi=True,
        )
        scene = RenderSceneBuilder().build(fc, experimental_profile, preset.style_profile, "preview")
        names = [layer.name for layer in scene.layers]

        self.assertIn("voronoi_cells", names)

    def test_small_buildings_do_not_collapse_under_preview_simplification(self) -> None:
        fc = FeatureCollection(
            geojson_by_layer={
                "buildings": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[
                                    [0.0, 0.0],
                                    [0.0003, 0.0],
                                    [0.0003, 0.0002],
                                    [0.0, 0.0002],
                                    [0.0, 0.0],
                                ]],
                            },
                            "properties": {},
                        },
                    ],
                },
            },
            bbox=(0.0, 0.0, 1.0, 1.0),
        )

        profile = GeometryPipelineProfile(
            simplify_tolerance_preview=2.8,
            simplify_tolerance_export=2.8,
            derive_voronoi=False,
            derive_delaunay=False,
            derive_hex_grid=False,
            derive_circle_packing=False,
        )
        scene = RenderSceneBuilder().build(fc, profile, StyleProfile(layer_styles={}), "preview")

        buildings_layer = next(layer for layer in scene.layers if layer.name == "buildings")
        building = buildings_layer.geometries[0]

        self.assertEqual(len(list(building.exterior.coords)), 5)
        self.assertGreater(building.area, 0.0)

    def test_coastline_generates_visible_sea_water_polygon(self) -> None:
        fc = FeatureCollection(
            geojson_by_layer={
                "coastline": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "LineString", "coordinates": [[0.0, 0.45], [1.0, 0.55]]},
                            "properties": {"natural": "coastline"},
                        },
                    ],
                },
                "roads": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "LineString", "coordinates": [[0.1, 0.8], [0.9, 0.8]]},
                            "properties": {"highway": "residential"},
                        },
                    ],
                },
                "buildings": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [[[0.2, 0.7], [0.25, 0.7], [0.25, 0.75], [0.2, 0.7]]],
                            },
                            "properties": {"building": "yes"},
                        },
                    ],
                },
            },
            bbox=(0.0, 0.0, 1.0, 1.0),
        )

        profile = GeometryPipelineProfile(derive_voronoi=False, derive_delaunay=False)
        scene = RenderSceneBuilder().build(fc, profile, default_preset("OSM Standard").style_profile, "preview")

        water_layer = next(layer for layer in scene.layers if layer.name == "water")

        self.assertGreaterEqual(len(water_layer.geometries), 1)
        self.assertTrue(water_layer.style.fill_enabled)
        self.assertGreater(water_layer.style.fill_color.b, water_layer.style.fill_color.r)

    def test_scene_carries_the_style_profile_background(self) -> None:
        """The renderer and the SVG exporter both read the ground off the scene."""
        fc = FeatureCollection(
            geojson_by_layer={
                "roads": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 10]]},
                            "properties": {},
                        },
                    ],
                },
            }
        )

        night = default_preset("Night")
        scene = RenderSceneBuilder().build(fc, night.geometry_profile, night.style_profile, "preview")

        expected = night.style_profile.background
        self.assertEqual(
            (scene.background.r, scene.background.g, scene.background.b),
            (expected.r, expected.g, expected.b),
        )


class DrawOrderTests(unittest.TestCase):
    """Where the sea sits in the stack.

    Elevation bands cover the sea as well as the land — the tiles carry the sea
    floor in the same band as the ground — and a hypsometric band fill is
    opaque. Drawn after the water, they paint the harbour out: the Auckland
    plate infers the Waitematā correctly from the coastline and then hides it
    under a land tint. A printed sheet draws the sea *over* the hypsometric
    tint, and so does this now.
    """

    TERRAIN = {
        "coastline", "water", "parks", "elevation_bands", "terrain_hillshade",
        "bathymetry", "terrain_contours", "terrain_index_contours",
        "buildings", "roads_primary", "places",
    }

    def order(self) -> list[str]:
        return _ordered_layers(self.TERRAIN)

    def test_the_sea_is_drawn_over_the_relief(self) -> None:
        order = self.order()
        self.assertLess(order.index("elevation_bands"), order.index("water"))
        self.assertLess(order.index("terrain_hillshade"), order.index("water"))

    def test_the_relief_still_sits_over_the_land_cover(self) -> None:
        """It is a tint on the ground, not a layer beside it."""
        self.assertLess(self.order().index("parks"), self.order().index("elevation_bands"))

    def test_depth_and_contours_are_drawn_over_the_water_they_describe(self) -> None:
        order = self.order()
        for layer in ("bathymetry", "terrain_contours", "terrain_index_contours"):
            with self.subTest(layer=layer):
                self.assertLess(order.index("water"), order.index(layer))

    def test_the_built_environment_still_sits_on_top_of_all_of_it(self) -> None:
        order = self.order()
        for layer in ("coastline", "water", "elevation_bands", "terrain_contours"):
            with self.subTest(layer=layer):
                self.assertLess(order.index(layer), order.index("buildings"))
                self.assertLess(order.index(layer), order.index("roads_primary"))

    def test_labels_are_last(self) -> None:
        order = self.order()
        self.assertEqual(order[-1], "places")

    def test_water_is_drawn_over_the_land_cover_too(self) -> None:
        """A consequence rather than a separate decision, and the right one.

        Relief has to sit above land cover — it is a tint on the ground — and
        below the water, or it paints the sea out. Both together put water above
        land cover. That is also how it should have been: an OSM park polygon
        commonly includes its ponds, and drawing the park afterwards filled them
        in with grass.
        """
        plain = _ordered_layers({"coastline", "water", "parks", "buildings", "roads_primary"})
        self.assertEqual(plain, ["parks", "coastline", "water", "buildings", "roads_primary"])


class EveryKnownLayerIsRankedTests(unittest.TestCase):
    """A layer missing from the preferred order is not skipped — it is drawn last.

    `_ordered_layers` appends everything it does not recognise, sorted by name,
    after every layer it does. For a line layer that is untidy; for a *filled*
    one it is destructive, because the fill paints over the finished sheet. Three
    of the layers that were missing are fills — `depth_bands`, `seamark_areas`
    and `sst_bands` — and `sst_bands` sorts last of all thirteen, so a sea
    temperature sheet painted the whole map out at the final step.

    The bug was found once before, in `night_lights`, and fixed only for
    `night_lights`. This asserts the rule instead of the instance: every layer
    the inventory knows about has a place in the order, so a new source is ranked
    when it is added rather than when somebody renders a sheet and sees it.
    """

    def known_layers(self) -> set[str]:
        return set(LAYER_LABELS) | set(_GROUPS)

    def test_every_known_layer_has_a_rank(self) -> None:
        missing = sorted(self.known_layers() - set(PREFERRED_LAYER_ORDER))
        self.assertEqual(missing, [], f"drawn last, over everything: {missing}")

    def test_the_order_ranks_nothing_the_inventory_has_never_heard_of(self) -> None:
        """The other direction: a rank for a layer that does not exist is a typo."""
        roads = {name for name in PREFERRED_LAYER_ORDER if name == "roads" or name.startswith("roads_")}
        unknown = sorted(set(PREFERRED_LAYER_ORDER) - self.known_layers() - roads)
        self.assertEqual(unknown, [], f"ranked but unknown to the inventory: {unknown}")

    def test_finer_borders_draw_under_coarser_ones(self) -> None:
        """The heaviest line must be the last ink on an edge the three share."""
        rank = PREFERRED_LAYER_ORDER.index
        self.assertLess(rank("county_boundaries"), rank("state_boundaries"))
        self.assertLess(rank("state_boundaries"), rank("admin_boundaries"))

    def test_no_layer_is_ranked_twice(self) -> None:
        self.assertEqual(len(PREFERRED_LAYER_ORDER), len(set(PREFERRED_LAYER_ORDER)))

    def test_the_filled_layers_are_drawn_under_the_linework(self) -> None:
        """The rule this file already states, applied to the fills that were missing.

        A band fill over the contours that describe the same ground paints them
        out; that is why `elevation_bands` sits where it does, and a sea floor or
        a temperature is no exception to it.
        """
        order = _ordered_layers({"depth_bands", "sst_bands", "bathymetry",
                                 "terrain_contours", "sst_contours"})
        for fill in ("depth_bands", "sst_bands"):
            for line in ("bathymetry", "terrain_contours", "sst_contours"):
                with self.subTest(fill=fill, line=line):
                    self.assertLess(order.index(fill), order.index(line))

    def test_sea_marks_are_drawn_over_the_built_environment(self) -> None:
        """On a chart the marks are the subject; a buoy under a building is lost."""
        order = _ordered_layers({"seamark_lights", "seamark_buoys", "buildings", "roads", "places"})
        for mark in ("seamark_lights", "seamark_buoys"):
            with self.subTest(mark=mark):
                self.assertLess(order.index("buildings"), order.index(mark))
                self.assertLess(order.index("roads"), order.index(mark))

    def test_labels_still_come_last(self) -> None:
        """The thirteen were all appended after the labels. None may stay there."""
        order = _ordered_layers({"places", "summits", "depth_bands", "sst_bands",
                                 "admin_boundaries", "ferry_routes", "night_lights",
                                 "seamark_lights", "current_streamlines"})
        for layer in ("depth_bands", "sst_bands", "admin_boundaries", "ferry_routes",
                      "night_lights", "seamark_lights", "current_streamlines"):
            with self.subTest(layer=layer):
                self.assertLess(order.index(layer), order.index("places"))


class ReliefOverBuildingsTests(unittest.TestCase):
    """The switch for a dense city, where relief drawn under the buildings by
    default is hidden behind almost all of them."""

    def names(self, layers: list[RenderLayer]) -> list[str]:
        return [layer.name for layer in layers]

    def test_relief_moves_above_the_built_environment(self) -> None:
        layers = [RenderLayer(name=name) for name in ("elevation_bands", "terrain_hillshade", "coastline", "water", "buildings", "roads_primary", "places")]
        reordered = self.names(_raise_relief_over_the_built_environment(layers))
        self.assertLess(reordered.index("terrain_hillshade"), reordered.index("places"))
        for layer in ("coastline", "water", "buildings", "roads_primary"):
            with self.subTest(layer=layer):
                self.assertLess(reordered.index(layer), reordered.index("terrain_hillshade"))

    def test_relief_still_sits_below_the_labels(self) -> None:
        layers = [RenderLayer(name=name) for name in ("terrain_hillshade", "buildings", "summits", "places", "shops")]
        reordered = self.names(_raise_relief_over_the_built_environment(layers))
        for label in ("summits", "places", "shops"):
            with self.subTest(label=label):
                self.assertLess(reordered.index("terrain_hillshade"), reordered.index(label))

    def test_a_scene_with_no_relief_is_unchanged(self) -> None:
        layers = [RenderLayer(name=name) for name in ("coastline", "water", "buildings")]
        self.assertEqual(_raise_relief_over_the_built_environment(layers), layers)

    def test_a_scene_with_no_labels_puts_relief_last(self) -> None:
        layers = [RenderLayer(name=name) for name in ("terrain_hillshade", "coastline", "buildings")]
        reordered = self.names(_raise_relief_over_the_built_environment(layers))
        self.assertEqual(reordered[-1], "terrain_hillshade")

    def test_the_geometry_profile_switch_reaches_the_built_scene(self) -> None:
        """Not just the pure reorder function -- the flag on the preset that is
        supposed to trigger it during a real build."""
        fc = FeatureCollection(
            geojson_by_layer={
                "buildings": {"features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}, "properties": {}}]},
                "terrain_hillshade": {"features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}, "properties": {"band_index": 0, "band_count": 2}}]},
            },
            bbox=(0.0, 0.0, 2.0, 2.0),
        )
        preset = default_preset("Hypsometric Relief")
        lifted = RenderSceneBuilder().build(
            fc,
            replace(preset.geometry_profile, relief_over_buildings=True),
            preset.style_profile,
            "preview",
        )
        grounded = RenderSceneBuilder().build(fc, preset.geometry_profile, preset.style_profile, "preview")

        def index_of(scene, name: str) -> int:
            return next(i for i, layer in enumerate(scene.layers) if layer.name == name)

        self.assertLess(index_of(grounded, "terrain_hillshade"), index_of(grounded, "buildings"))
        self.assertGreater(index_of(lifted, "terrain_hillshade"), index_of(lifted, "buildings"))


if __name__ == "__main__":
    unittest.main()
