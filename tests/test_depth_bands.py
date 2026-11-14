"""The sea floor's own mass, rather than the deep end of the land's ramp.

``elevation_bands`` always spanned the whole measured range, so a coastal sheet
banded its sea floor in the land's own colours — a trench drawn as a kind of
valley. The sea got contours where the land got mass, and what mass it did get
was wearing the wrong clothes.

The split is at the waterline, which is the same division the bathymetry layer
already makes for contours, one level up.
"""

from __future__ import annotations

import unittest

from hipparchus.application.layer_inventory import LAYER_LABELS, layer_group
from hipparchus.data_sources.optional_providers import ALL_OPTIONAL_LAYERS
from hipparchus.data_sources.emodnet_bathymetry import _depth_band_mode
from hipparchus.geometry.bands import (
    STATED_DEPTHS,
    DepthBandMode,
    band_boundaries,
    depth_band_boundaries,
    land_band_boundaries,
)
from hipparchus.rendering.not_for_navigation import MARINE_LAYERS


class SplittingAtTheWaterlineTests(unittest.TestCase):
    def test_the_land_starts_at_the_waterline(self) -> None:
        """Not at the deepest sounding, which is what put a trench in the land's
        ramp."""
        self.assertEqual(land_band_boundaries(-40, 120, 4)[0], 0.0)

    def test_the_sea_ends_at_the_waterline(self) -> None:
        self.assertEqual(depth_band_boundaries(-40, 120, 4)[-1], 0.0)

    def test_the_two_halves_meet_and_do_not_overlap(self) -> None:
        land = land_band_boundaries(-40, 120, 4)
        sea = depth_band_boundaries(-40, 120, 4)
        self.assertEqual(sea[-1], land[0])
        self.assertTrue(all(edge <= 0 for edge in sea))
        self.assertTrue(all(edge >= 0 for edge in land))

    def test_an_inland_frame_has_no_sea_bands(self) -> None:
        """A sheet of the Alps should not carry a depth band, and an empty list
        says so more clearly than one band spanning nothing."""
        self.assertEqual(depth_band_boundaries(200, 4000, 6), [])

    def test_an_open_ocean_frame_has_no_land_bands(self) -> None:
        self.assertEqual(land_band_boundaries(-5000, -200, 6), [])

    def test_a_frame_touching_zero_from_below_is_still_all_sea(self) -> None:
        self.assertEqual(land_band_boundaries(-500, 0, 4), [])

    def test_nothing_is_produced_from_nonsense(self) -> None:
        self.assertEqual(depth_band_boundaries(float("nan"), 10, 4), [])
        self.assertEqual(land_band_boundaries(-10, float("nan"), 4), [])


class EvenModeTests(unittest.TestCase):
    def test_it_divides_the_water_evenly(self) -> None:
        self.assertEqual(depth_band_boundaries(-40, 0, 4), [-40, -30, -20, -10, 0])

    def test_it_asks_for_the_count_it_was_given(self) -> None:
        self.assertEqual(len(depth_band_boundaries(-100, 20, 5)), 6)


class ChartModeTests(unittest.TestCase):
    """The depths a chart prints. Not an even division of anything — these are
    the numbers a mariner already has in their head."""

    def test_it_uses_stated_depths(self) -> None:
        edges = depth_band_boundaries(-40, 10, 8, DepthBandMode.CHART)
        for edge in edges[:-1]:
            with self.subTest(edge=edge):
                self.assertIn(-edge, STATED_DEPTHS)

    def test_it_does_not_invent_ground_the_frame_does_not_have(self) -> None:
        """A harbour sheet should not carry a 200 m band it has no ground for.
        A boundary at a depth nobody states is the thing this mode exists to
        avoid."""
        edges = depth_band_boundaries(-12, 5, 8, DepthBandMode.CHART)
        self.assertTrue(all(edge > -20 for edge in edges), edges)

    def test_the_shallow_end_is_kept_when_the_ladder_is_too_long(self) -> None:
        """If the ladder offers more bands than were asked for, the deep end
        goes first — the shallow end is the half a reader is making decisions
        with."""
        edges = depth_band_boundaries(-6000, 0, 3, DepthBandMode.CHART)
        self.assertEqual(len(edges), 4)
        self.assertEqual(edges[-1], 0.0)
        # The shallowest stated depths survive; the abyssal ones are dropped.
        self.assertGreater(edges[0], -6000)

    def test_it_ends_at_the_waterline_like_the_even_mode(self) -> None:
        self.assertEqual(depth_band_boundaries(-40, 10, 6, DepthBandMode.CHART)[-1], 0.0)

    def test_a_frame_below_every_stated_depth_still_gives_something(self) -> None:
        edges = depth_band_boundaries(-1.5, 0, 4, DepthBandMode.CHART)
        # Nothing shallower than 2 m is stated, so there is no ladder to climb
        # and the mode has nothing honest to say.
        self.assertEqual(edges, [])


class ModeParsingTests(unittest.TestCase):
    """Settings travel as plain strings through the session file and the source
    panel, so an unknown one is a stale file rather than a reason to refuse to
    draw."""

    def test_the_names_round_trip(self) -> None:
        self.assertIs(_depth_band_mode("even"), DepthBandMode.EVEN)
        self.assertIs(_depth_band_mode("chart"), DepthBandMode.CHART)

    def test_it_is_forgiving_about_shape(self) -> None:
        self.assertIs(_depth_band_mode("  CHART "), DepthBandMode.CHART)

    def test_an_unknown_mode_falls_back_rather_than_raising(self) -> None:
        self.assertIs(_depth_band_mode("sounding-ladder"), DepthBandMode.EVEN)
        self.assertIs(_depth_band_mode(""), DepthBandMode.EVEN)


class TheLayerExistsEverywhereTests(unittest.TestCase):
    """A layer the rest of the application has never heard of is fetched, drawn
    and then invisible — which is how the sea marks spent a render being
    silently absent."""

    def test_it_is_a_known_layer(self) -> None:
        self.assertIn("depth_bands", ALL_OPTIONAL_LAYERS)

    def test_it_has_a_label_and_a_group(self) -> None:
        self.assertIn("depth_bands", LAYER_LABELS)
        self.assertEqual(layer_group("depth_bands"), "Terrain")

    def test_every_palette_gives_it_a_two_stop_ramp(self) -> None:
        from hipparchus.application.palette_sheet import style_profile
        from hipparchus.application.palettes import PALETTES

        for palette in PALETTES:
            style = style_profile(palette).layer_styles.get("depth_bands")
            with self.subTest(palette=palette.name):
                self.assertIsNotNone(style)
                assert style is not None
                self.assertTrue(style.fill_enabled)
                self.assertIsNotNone(style.fill_color_high)

    def test_deep_is_darker_than_shallow_in_every_palette(self) -> None:
        """The one thing about a depth ramp a reader assumes without being told,
        and the one that is invisible when inverted."""
        from hipparchus.application.palette_sheet import style_profile
        from hipparchus.application.palettes import PALETTES

        def luma(colour) -> float:
            return (299 * colour.r + 587 * colour.g + 114 * colour.b) / 1000.0

        for palette in PALETTES:
            style = style_profile(palette).layer_styles["depth_bands"]
            with self.subTest(palette=palette.name):
                assert style.fill_color_high is not None
                self.assertLess(luma(style.fill_color), luma(style.fill_color_high))

    def test_a_sheet_with_depth_bands_is_not_for_navigation(self) -> None:
        self.assertIn("depth_bands", MARINE_LAYERS)

    def test_it_gets_the_two_stop_ramp_and_not_one_flat_colour(self) -> None:
        """**A band layer missing from `_BANDED_LAYERS` does not fail; it draws
        flat**, in whichever single colour ``fill_color`` holds — for a depth
        ramp that is the deepest tone, so the whole sea comes out one slab of
        dark water with the shallows indistinguishable from the channel.

        It looked like a styling choice. Only rendering Cuxhaven and seeing a
        uniformly dark estuary, where the Elbe should read as a dark channel
        through pale flats, showed otherwise.
        """
        from hipparchus.application.scene_builder import _BANDED_LAYERS

        self.assertIn("depth_bands", _BANDED_LAYERS)


class NotChangingTheLandTests(unittest.TestCase):
    """With the split switched off the sea floor bands with the land on one
    ramp, which is what every sheet did before. Kept so an old render and a new
    one can be compared."""

    def test_the_whole_range_is_still_available(self) -> None:
        self.assertEqual(band_boundaries(-40, 120, 4), [-40, 0, 40, 80, 120])


if __name__ == "__main__":
    unittest.main()
