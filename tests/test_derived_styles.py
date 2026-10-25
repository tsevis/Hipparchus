"""The ocean fields and the border, for a preset that has never named either.

The same gap `derived_depth_bands` and `derived_seamark_style` close, three
layers further on. Not one of the sixteen built-in presets styles
``sst_bands``, ``sst_contours``, ``current_streamlines``, ``ferry_routes`` or
``admin_boundaries`` -- ``palette_sheet.style_profile`` is again the only place
that has ever styled them -- so each fell through to ``resolve_style``'s last
resort.

For the four line layers that meant a wrong-coloured hairline. For
``sst_bands`` it meant something worse: it is a **fill** layer, and the shared
default draws it as a flat box with the ramp thrown away, so a sea temperature
sheet lost the thing it exists to show.

The mixes below are ``palette_sheet``'s own for these five layers, read off
what the preset itself already chose rather than off a full palette -- exactly
the way the depth bands and the sea marks are derived.
"""

from __future__ import annotations

import unittest

from hipparchus.application.derived_styles import (
    OCEAN_LAYERS,
    derived_admin_boundaries,
    derived_contour_style,
    derived_hillshade,
    derived_ocean_style,
    sheets_own_ink,
    sheets_own_land,
    sheets_own_water,
    unstyled_fallback,
)
from hipparchus.application.palettes import mix
from hipparchus.application.presets import (
    StyleProfile,
    default_preset,
    preset_names,
    resolve_style,
)
from hipparchus.rendering.models import LayerStyle, RGBAColor

def _profile(
    *,
    elevation_bands: LayerStyle | None = None,
    buildings: LayerStyle | None = None,
    water: LayerStyle | None = None,
    bathymetry: LayerStyle | None = None,
    coastline: LayerStyle | None = None,
    background: RGBAColor = RGBAColor(250, 250, 250),
) -> StyleProfile:
    styles: dict[str, LayerStyle] = {}
    for name, style in (
        ("elevation_bands", elevation_bands),
        ("buildings", buildings),
        ("water", water),
        ("bathymetry", bathymetry),
        ("coastline", coastline),
    ):
        if style is not None:
            styles[name] = style
    return StyleProfile(layer_styles=styles, background=background)


def _filled(colour: RGBAColor) -> LayerStyle:
    return LayerStyle(fill_enabled=True, fill_color=colour)


def _ramped(low: RGBAColor, high: RGBAColor) -> LayerStyle:
    return LayerStyle(fill_enabled=True, fill_color=low, fill_color_high=high)


def _luma(colour: RGBAColor) -> float:
    return (299.0 * colour.r + 587.0 * colour.g + 114.0 * colour.b) / 1000.0


class SheetColourTests(unittest.TestCase):
    """The four colours every derivation here reads off the preset."""

    def test_water_comes_from_a_fill_or_a_stroke(self) -> None:
        filled = _profile(water=_filled(RGBAColor(10, 20, 30)))
        outlined = _profile(water=LayerStyle(fill_enabled=False, stroke_color=RGBAColor(40, 50, 60)))
        self.assertEqual(sheets_own_water(filled), RGBAColor(10, 20, 30))
        self.assertEqual(sheets_own_water(outlined), RGBAColor(40, 50, 60))

    def test_ink_prefers_the_bathymetry_over_the_coastline(self) -> None:
        both = _profile(
            bathymetry=LayerStyle(stroke_color=RGBAColor(1, 2, 3)),
            coastline=LayerStyle(stroke_color=RGBAColor(4, 5, 6)),
        )
        self.assertEqual(sheets_own_ink(both), RGBAColor(1, 2, 3))
        self.assertEqual(sheets_own_ink(_profile(coastline=LayerStyle(stroke_color=RGBAColor(4, 5, 6)))),
                         RGBAColor(4, 5, 6))

    def test_land_comes_from_the_buildings_however_stated(self) -> None:
        filled = _profile(buildings=_filled(RGBAColor(7, 8, 9)))
        outlined = _profile(buildings=LayerStyle(fill_enabled=False, stroke_color=RGBAColor(11, 12, 13)))
        self.assertEqual(sheets_own_land(filled), RGBAColor(7, 8, 9))
        self.assertEqual(sheets_own_land(outlined), RGBAColor(11, 12, 13))

    def test_every_colour_has_a_fallback(self) -> None:
        """A preset naming none of them still gets a usable answer."""
        bare = _profile()
        for helper in (sheets_own_water, sheets_own_ink, sheets_own_land):
            with self.subTest(helper=helper.__name__):
                self.assertIsInstance(helper(bare), RGBAColor)


class OceanDerivationTests(unittest.TestCase):
    def test_it_answers_only_for_its_own_layers(self) -> None:
        for layer in ("roads", "buildings", "terrain_contours", "admin_boundaries"):
            with self.subTest(layer=layer):
                self.assertIsNone(derived_ocean_style(_profile(), layer))

    def test_every_ocean_layer_gets_a_style(self) -> None:
        for layer in OCEAN_LAYERS:
            with self.subTest(layer=layer):
                self.assertIsNotNone(derived_ocean_style(_profile(), layer))

    def test_the_line_layers_are_never_filled(self) -> None:
        """A filled isotherm is a blot, and a filled ferry route is a smear."""
        for layer in ("sst_contours", "current_streamlines", "ferry_routes"):
            with self.subTest(layer=layer):
                self.assertFalse(derived_ocean_style(_profile(), layer).fill_enabled)

    def test_the_colours_are_the_sheets_own_water(self) -> None:
        green = _profile(water=_filled(RGBAColor(40, 120, 60)))
        blue = _profile(water=_filled(RGBAColor(40, 60, 120)))
        for layer in ("sst_contours", "current_streamlines", "ferry_routes"):
            with self.subTest(layer=layer):
                self.assertNotEqual(
                    derived_ocean_style(green, layer).stroke_color,
                    derived_ocean_style(blue, layer).stroke_color,
                )

    def test_streamlines_read_heavier_than_a_ferry_route(self) -> None:
        """When the currents are on they are the subject; a ferry route is not."""
        bare = _profile()
        currents = derived_ocean_style(bare, "current_streamlines")
        ferry = derived_ocean_style(bare, "ferry_routes")
        self.assertGreater(currents.stroke_width, ferry.stroke_width)
        self.assertGreater(currents.opacity, ferry.opacity)

    def test_streamlines_are_round_capped(self) -> None:
        self.assertEqual(derived_ocean_style(_profile(), "current_streamlines").line_cap, "round")

    def test_the_derived_weights_match_the_macos_application(self) -> None:
        """Pinned, because these four numbers drifted apart once already.

        The twin's `derivedOceanStyle` states the same values, and its
        `DerivedStyleTests` pins them from the other side. They are asserted as
        literals rather than derived from anything, so a change here has to be a
        change somebody meant to make in both places.

        `current_streamlines` is the one that had to be chosen rather than
        copied: this repository's own `palette_sheet` says 1.1 and mix 0.62,
        which is ~47% heavier, and the macOS side is where surface currents were
        written first.
        """
        water = RGBAColor(150, 180, 200)
        ink = RGBAColor(40, 60, 80)
        bare = _profile()
        self.assertEqual(sheets_own_water(bare), water)
        self.assertEqual(sheets_own_ink(bare), ink)

        expected = {
            "sst_contours": (0.4, mix(water, ink, 0.5), 0.65),
            "current_streamlines": (0.75, mix(water, ink, 0.7), 0.85),
            "ferry_routes": (0.6, mix(water, ink, 0.2), 0.7),
        }
        for layer, (width, colour, opacity) in expected.items():
            with self.subTest(layer=layer):
                style = derived_ocean_style(bare, layer)
                self.assertAlmostEqual(style.stroke_width, width)
                self.assertEqual(style.stroke_color, colour)
                self.assertAlmostEqual(style.opacity, opacity)


class SeaTemperatureBandTests(unittest.TestCase):
    """`sst_bands` is the one that mattered: a fill layer drawn as a grey box."""

    def test_a_sheet_that_fills_the_land_fills_the_sea_temperature(self) -> None:
        profile = _profile(
            elevation_bands=_filled(RGBAColor(232, 237, 226)),
            water=_filled(RGBAColor(150, 180, 200)),
        )
        self.assertTrue(derived_ocean_style(profile, "sst_bands").fill_enabled)

    def test_a_linework_sheet_keeps_its_temperature_unfilled(self) -> None:
        """Follows the land rather than overruling it, as the depth bands do.

        A preset that leaves `elevation_bands` unfilled has decided the sheet is
        linework; forcing a temperature wash onto it would be this derivation
        deciding what the sheet is.
        """
        profile = _profile(elevation_bands=LayerStyle(fill_enabled=False))
        self.assertFalse(derived_ocean_style(profile, "sst_bands").fill_enabled)

    def test_a_sheet_naming_no_bands_at_all_stays_unfilled(self) -> None:
        self.assertFalse(derived_ocean_style(_profile(), "sst_bands").fill_enabled)

    def test_the_bands_carry_a_ramp_rather_than_one_flat_tone(self) -> None:
        """The bug this closes: the shared default threw the ramp away."""
        profile = _profile(
            elevation_bands=_filled(RGBAColor(232, 237, 226)),
            water=_filled(RGBAColor(150, 180, 200)),
            buildings=_filled(RGBAColor(204, 199, 190)),
        )
        style = derived_ocean_style(profile, "sst_bands")
        self.assertIsNotNone(style.fill_color_high)
        self.assertNotEqual(style.fill_color, style.fill_color_high)

    def test_the_bands_are_unstroked(self) -> None:
        """A band edge and an isotherm are the same line; drawing both doubles it."""
        profile = _profile(elevation_bands=_filled(RGBAColor(232, 237, 226)))
        self.assertEqual(derived_ocean_style(profile, "sst_bands").stroke_width, 0)

    def test_the_bands_stay_translucent(self) -> None:
        """They sit over the sea floor they describe, which must stay readable."""
        profile = _profile(elevation_bands=_filled(RGBAColor(232, 237, 226)))
        self.assertLess(derived_ocean_style(profile, "sst_bands").opacity, 0.6)


class AdminBoundaryTests(unittest.TestCase):
    def test_a_border_is_a_line_not_a_filled_region(self) -> None:
        """It partitions land; filling it paints one country out."""
        self.assertFalse(derived_admin_boundaries(_profile()).fill_enabled)

    def test_the_colour_is_the_sheets_own_land_and_ink(self) -> None:
        pale = _profile(buildings=_filled(RGBAColor(230, 225, 215)))
        dark = _profile(buildings=_filled(RGBAColor(60, 55, 50)))
        self.assertNotEqual(
            derived_admin_boundaries(pale).stroke_color,
            derived_admin_boundaries(dark).stroke_color,
        )

    def test_it_is_drawn_lightly(self) -> None:
        """A border follows a network it must not outshout."""
        style = derived_admin_boundaries(_profile())
        self.assertLess(style.opacity, 1.0)
        self.assertLessEqual(style.stroke_width, 1.0)

    def test_borders_thin_from_country_to_state_to_county(self) -> None:
        """The weight is how a reader tells the three apart where they share an edge."""
        profile = _profile()
        country = resolve_style(profile, "admin_boundaries")
        state = resolve_style(profile, "state_boundaries")
        county = resolve_style(profile, "county_boundaries")
        self.assertGreater(country.stroke_width, state.stroke_width)
        self.assertGreater(state.stroke_width, county.stroke_width)
        self.assertFalse(state.fill_enabled)
        self.assertFalse(county.fill_enabled)


def _known_gaps() -> set[str]:
    """Layers still reaching the shared default, with the reason for each.

    **There are none left.** There were sixty-three, in three groups, and each
    group had a different answer:

    - `terrain_hillshade` on all sixteen presets: no Python equivalent of the
      port's `derivedHillshade`. Ported, and now `derived_hillshade`.
    - the contour pair on nine presets: closed by `derived_contour_style`, which
      reads each sheet's own relief ramp rather than imposing one colour that
      could only suit some of them.
    - fifteen layers apiece on `OSM Standard` and `Editorial Print`: those two
      were written as dicts from scratch and never gained what `_base_styles`
      grew. Closed by putting the base underneath.

    Kept as an empty set rather than deleted, because the assertion that it is
    empty is the useful part, and the next gap has somewhere to be recorded.
    """
    return set()


class OSMStandardKeepsItsOwnStyleTests(unittest.TestCase):
    """`OSM Standard` now layers over `_base_styles`, and must not shift.

    It and `Editorial Print` were the only presets written as a dict from
    scratch, so they never gained the layers the shared base has grown since —
    fifteen apiece drew as a grey hairline, `elevation_bands` among them, which
    is a fill and so drew as nothing.

    Putting the base underneath closes all of that. The risk is the other
    direction: that a layer OSM Standard *does* state quietly changes. It cannot,
    and this is what says so.
    """

    def test_every_layer_osm_standard_states_survives_unchanged(self) -> None:
        from hipparchus.application.presets import _osm_standard_overrides, _osm_standard_styles

        stated = _osm_standard_overrides()
        resolved = _osm_standard_styles()
        for layer, style in stated.items():
            with self.subTest(layer=layer):
                self.assertEqual(resolved[layer], style)

    def test_the_base_fills_in_what_it_never_stated(self) -> None:
        from hipparchus.application.presets import _osm_standard_overrides, _osm_standard_styles

        gained = set(_osm_standard_styles()) - set(_osm_standard_overrides())
        self.assertIn("elevation_bands", gained)
        self.assertIn("summits", gained)
        self.assertIn("bathymetry", gained)

    def test_editorial_print_inherits_the_same_repair(self) -> None:
        """It builds on OSM Standard, so it is fixed by the same change."""
        styles = default_preset("Editorial Print").style_profile.layer_styles
        for layer in ("elevation_bands", "summits", "bathymetry", "night_lights"):
            with self.subTest(layer=layer):
                self.assertIn(layer, styles)

    def test_editorial_print_keeps_its_own_choices(self) -> None:
        styles = default_preset("Editorial Print").style_profile.layer_styles
        self.assertEqual(styles["buildings"].fill_color, RGBAColor(218, 214, 205))
        self.assertEqual(styles["places"].stroke_color, RGBAColor(28, 30, 34))


class HillshadeDerivationTests(unittest.TestCase):
    """Relief shading for a preset that has never heard of it.

    Ported from the macOS `derivedHillshade`, which had no Python counterpart —
    all sixteen presets fell back here. It is a **wash that adds one tone and
    leaves the other alone**: the shade is drawn over the bands and the land
    cover, so the untouched end has to be nothing at all, carried as zero alpha.
    Setting it to the background instead paints the paper over what the map had
    already drawn, and the sheet goes flat while every colour still looks fine.
    """

    def test_it_is_a_fill_rather_than_linework(self) -> None:
        style = derived_hillshade(_profile())
        self.assertTrue(style.fill_enabled)
        self.assertEqual(style.stroke_width, 0)

    def test_pale_ground_takes_shadow(self) -> None:
        """Dark where it turns away, nothing where it faces the sun."""
        style = derived_hillshade(_profile(background=RGBAColor(250, 250, 250)))
        self.assertEqual(style.fill_color.a, 140)
        self.assertEqual(style.fill_color_high.a, 0)
        self.assertEqual(style.fill_color.r, 0)

    def test_dark_ground_takes_light(self) -> None:
        """Nothing in the shadows, which are already dark; a highlight on the
        faces that catch the sun. Backwards here reads inside out."""
        style = derived_hillshade(_profile(background=RGBAColor(14, 17, 23)))
        self.assertEqual(style.fill_color.a, 0)
        self.assertEqual(style.fill_color_high.a, 105)
        self.assertEqual(style.fill_color_high.r, 255)

    def test_the_ground_is_the_bands_rather_than_the_paper(self) -> None:
        """A dark preset with pale bands is shaded against the bands.

        `Night` is exactly that pairing. Judging by its background alone puts a
        white highlight onto near-white bands and shades nothing at all.
        """
        night_paper_pale_bands = _profile(
            background=RGBAColor(14, 17, 23),
            elevation_bands=_filled(RGBAColor(232, 237, 226)),
        )
        style = derived_hillshade(night_paper_pale_bands)
        self.assertEqual(style.fill_color.a, 140, "pale bands should take shadow")

    def test_unfilled_bands_leave_the_background_in_charge(self) -> None:
        profile = _profile(
            background=RGBAColor(250, 250, 250),
            elevation_bands=LayerStyle(fill_enabled=False),
        )
        self.assertEqual(derived_hillshade(profile).fill_color.a, 140)

    def test_it_stays_under_the_linework_it_supports(self) -> None:
        """At full strength it buries the map it is holding up."""
        self.assertLess(derived_hillshade(_profile()).opacity, 1.0)

    def test_every_preset_now_has_one(self) -> None:
        for name in preset_names():
            with self.subTest(preset=name):
                style = resolve_style(default_preset(name).style_profile, "terrain_hillshade")
                self.assertNotEqual(style, unstyled_fallback())


class ContourDerivationTests(unittest.TestCase):
    """Contours for a preset that has never named them.

    Nine presets still left the pair to the fallback after `Clean Atlas` was
    fixed by hand. Each needs a hue that suits its own palette, and a derivation
    gets that right by construction where one chosen colour could not: a brown
    that reads on `Terrain Study` is invisible on `Night`.

    The ink is the land's own darkest tone — the high end of the elevation
    ramp — pushed away from the ground it is drawn on. An explicit entry still
    wins, so `Clean Atlas` keeps the brown it was given.
    """

    def test_it_answers_only_for_the_contour_pair(self) -> None:
        for layer in ("roads", "bathymetry", "elevation_bands"):
            with self.subTest(layer=layer):
                self.assertIsNone(derived_contour_style(_profile(), layer))

    def test_contours_are_lines(self) -> None:
        for layer in ("terrain_contours", "terrain_index_contours"):
            with self.subTest(layer=layer):
                self.assertFalse(derived_contour_style(_profile(), layer).fill_enabled)

    def test_index_contours_carry_more_weight(self) -> None:
        sheet = _profile(elevation_bands=_filled(RGBAColor(232, 237, 226)))
        minor = derived_contour_style(sheet, "terrain_contours")
        index = derived_contour_style(sheet, "terrain_index_contours")
        self.assertGreater(index.stroke_width, minor.stroke_width)
        self.assertGreater(index.opacity, minor.opacity)

    def test_on_pale_ground_the_line_is_darker_than_the_ground(self) -> None:
        sheet = _profile(background=RGBAColor(250, 250, 250))
        contours = derived_contour_style(sheet, "terrain_contours")
        self.assertLess(_luma(contours.stroke_color), _luma(RGBAColor(250, 250, 250)))

    def test_on_dark_ground_the_line_is_lighter_than_the_ground(self) -> None:
        """The case a single chosen brown cannot serve: `Night` draws on near-black."""
        ground = RGBAColor(14, 17, 23)
        sheet = _profile(background=ground)
        contours = derived_contour_style(sheet, "terrain_contours")
        self.assertGreater(_luma(contours.stroke_color), _luma(ground))

    def test_the_ink_follows_the_relief_ramp(self) -> None:
        """Contours belong to the ground they describe, so they take its colour."""
        brown = _profile(elevation_bands=_ramped(RGBAColor(232, 237, 226), RGBAColor(150, 122, 96)))
        grey = _profile(elevation_bands=_ramped(RGBAColor(235, 235, 235), RGBAColor(110, 110, 110)))
        self.assertNotEqual(
            derived_contour_style(brown, "terrain_contours").stroke_color,
            derived_contour_style(grey, "terrain_contours").stroke_color,
        )

    def test_an_explicit_entry_still_wins(self) -> None:
        """`Clean Atlas` was chosen by eye and must not be overruled."""
        styles = default_preset("Clean Atlas").style_profile.layer_styles
        self.assertEqual(styles["terrain_contours"].stroke_color, RGBAColor(120, 105, 81))
        self.assertEqual(
            resolve_style(default_preset("Clean Atlas").style_profile, "terrain_contours"),
            styles["terrain_contours"],
        )

    def test_every_preset_now_draws_contours_in_its_own_voice(self) -> None:
        inks = set()
        for name in preset_names():
            profile = default_preset(name).style_profile
            for layer in ("terrain_contours", "terrain_index_contours"):
                with self.subTest(preset=name, layer=layer):
                    self.assertNotEqual(resolve_style(profile, layer), unstyled_fallback())
            inks.add(resolve_style(profile, "terrain_contours").stroke_color)
        self.assertGreater(len(inks), 1, "every preset resolved to the same ink")


class UnstyledFallbackTests(unittest.TestCase):
    """What a layer nobody has styled and nothing derives is drawn as.

    The two apps disagreed here, and neither knew it. The Swift port returns a
    deliberate translucent grey hairline; the Python returned a bare
    `LayerStyle()` — the dataclass default, which nobody chose for this purpose:
    a near-black line at 1.0 wide, **filled**. So the same preset drew the same
    unstyled layer as a faint hairline on one app and a heavy near-black line on
    the other, and an unrecognised *polygon* layer got a flat grey wash in the
    Python that the Mac never drew.

    The port's answer is the considered one and is now shared.
    """

    def test_an_unstyled_layer_is_a_hairline_not_a_heavy_line(self) -> None:
        style = unstyled_fallback()
        self.assertLess(style.stroke_width, LayerStyle().stroke_width)

    def test_an_unstyled_layer_is_never_filled(self) -> None:
        """The dangerous half of the old default: an unknown polygon layer got a
        flat grey wash over whatever it covered."""
        self.assertFalse(unstyled_fallback().fill_enabled)

    def test_it_is_grey_and_translucent_rather_than_near_black(self) -> None:
        style = unstyled_fallback()
        self.assertEqual(style.stroke_color.r, style.stroke_color.g)
        self.assertEqual(style.stroke_color.g, style.stroke_color.b)
        self.assertLess(style.stroke_color.a, 255)

    def test_it_is_still_visible(self) -> None:
        """A new source must show up as *something* the first time it appears,
        rather than silently not rendering."""
        style = unstyled_fallback()
        self.assertGreater(style.stroke_width, 0.0)
        self.assertTrue(style.visible)
        self.assertGreater(style.stroke_color.a, 0)

    def test_each_call_hands_back_its_own_copy(self) -> None:
        """`LayerStyle` is mutable; a shared instance would leak edits between layers."""
        first = unstyled_fallback()
        first.stroke_width = 99.0
        self.assertNotEqual(unstyled_fallback().stroke_width, 99.0)

    def test_resolve_style_uses_it_for_a_layer_nobody_has_named(self) -> None:
        profile = default_preset("Clean Atlas").style_profile
        self.assertEqual(resolve_style(profile, "zebra_crossings"), unstyled_fallback())


class NoLayerReachesTheBareFallbackTests(unittest.TestCase):
    """The rule, rather than the five instances of it found by rendering Cyprus.

    Every layer the inventory knows should resolve to either an explicit style
    or a derivation. A layer that reaches `LayerStyle()` is drawn in whatever
    the dataclass default happens to be, which is how 800 contours came to be
    laid down in near-black over a hypsometric tint and how the sea temperature
    lost its ramp.

    Sixty-three combinations still do, for three understood reasons listed in
    `_known_gaps`. They are asserted exactly rather than ignored: the list only
    shrinks, and anything new fails here on the day it is introduced instead of
    on the day somebody renders a sheet and looks at it.
    """

    def offenders(self) -> set[str]:
        from hipparchus.application.layer_inventory import LAYER_LABELS, _GROUPS

        bare = unstyled_fallback()
        known = set(LAYER_LABELS) | set(_GROUPS)
        return {
            f"{name}/{layer}"
            for name in preset_names()
            for layer in known
            if resolve_style(default_preset(name).style_profile, layer) == bare
        }

    def test_nothing_new_reaches_the_shared_default(self) -> None:
        unexpected = sorted(self.offenders() - _known_gaps())
        self.assertEqual(unexpected, [], f"newly unstyled: {unexpected}")

    def test_the_known_gaps_are_still_real(self) -> None:
        """A gap that has been closed must be struck off the list, not left on it."""
        stale = sorted(_known_gaps() - self.offenders())
        self.assertEqual(stale, [], f"fixed but still listed as a gap: {stale}")

    def test_the_layers_derived_here_are_never_among_them(self) -> None:
        """The five this module exists for, held to the stricter rule."""
        offenders = self.offenders()
        for layer in (*OCEAN_LAYERS, "admin_boundaries", "depth_bands"):
            with self.subTest(layer=layer):
                still_bare = sorted(n for n in offenders if n.endswith(f"/{layer}"))
                self.assertEqual(still_bare, [])


if __name__ == "__main__":
    unittest.main()
