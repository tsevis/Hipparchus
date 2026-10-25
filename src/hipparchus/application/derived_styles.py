"""Styles for layers no preset has ever named.

`presets.py` carries sixteen style tables and not one of them mentions
``sst_bands``, ``sst_contours``, ``current_streamlines``, ``ferry_routes`` or
``admin_boundaries``. The tables predate all five, and
``palette_sheet.style_profile`` is the only place that has ever styled them —
so on a sheet drawn from a preset with no ``--palette`` override every one of
them fell through to ``resolve_style``'s last resort.

For the four line layers that is a wrong-coloured hairline. For ``sst_bands``
it is worse: it is a **fill** layer, so the shared default drew the sea
temperature as one flat box with its ramp discarded, which is the whole of what
the layer exists to show. That is the same shape of bug ``derived_depth_bands``
was written to end, and this closes it the same way.

**The mixes are ``palette_sheet``'s own**, read off what the preset itself
already chose rather than off a full palette — the approach
``derived_depth_bands`` and ``derived_seamark_style`` already take, so a preset
without a palette override gets these layers in its own voice rather than in
nobody's.

The profile is duck-typed rather than imported: ``StyleProfile`` lives in
`presets`, which imports this module, and only ``layer_styles`` and
``background`` are ever touched here.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from hipparchus.application.palettes import mix
from hipparchus.rendering.models import LayerStyle, RGBAColor

if TYPE_CHECKING:  # pragma: no cover - import cycle, types only
    from hipparchus.application.presets import StyleProfile

# The ocean fields, and the one transport layer that is drawn on them.
OCEAN_LAYERS: tuple[str, ...] = (
    "sst_bands",
    "sst_contours",
    "current_streamlines",
    "ferry_routes",
)

# The relief linework, minor and index.
CONTOUR_LAYERS: tuple[str, ...] = ("terrain_contours", "terrain_index_contours")


def unstyled_fallback() -> LayerStyle:
    """What a layer nobody has styled and nothing derives is drawn as.

    A layer a preset says nothing about is drawn as a hairline rather than
    skipped, so a new source shows up as *something* the first time it appears
    instead of silently not rendering.

    **This used to be a bare ``LayerStyle()``**, which is not a decision — it is
    the dataclass default, a near-black line 1.0 wide and *filled*. The Swift
    port has always returned the hairline below instead, so the two apps drew
    the same unstyled layer differently and neither knew: on the Cyprus plate
    the Python laid 825 contours in ``#141414`` at twice the port's weight over
    the same hypsometric tint, and greyed the land down doing it.

    ``fill_enabled=False`` is the half that matters most. Filled by default, an
    unrecognised *polygon* layer washes flat grey over whatever it covers — and
    an unranked layer is drawn last, so it covers everything.

    Returned fresh each call: ``LayerStyle`` is mutable, and a shared instance
    would leak one layer's edits into every other unstyled layer.
    """
    return LayerStyle(
        stroke_width=0.5,
        fill_enabled=False,
        stroke_color=RGBAColor(120, 120, 120, 200),
    )


def sheets_own_water(profile: StyleProfile) -> RGBAColor:
    """The sea's own colour, however the preset stated it: a filled water layer
    carries it as a fill, an outlined one as a stroke."""
    water = profile.layer_styles.get("water")
    if water is None:
        return RGBAColor(150, 180, 200)
    return water.fill_color if water.fill_enabled else water.stroke_color


def sheets_own_ink(profile: StyleProfile) -> RGBAColor:
    """The darkest line the preset draws on the sea: the sub-sea contours if it
    has them, the coastline if not."""
    bathymetry = profile.layer_styles.get("bathymetry")
    if bathymetry is not None:
        return bathymetry.stroke_color
    coastline = profile.layer_styles.get("coastline")
    if coastline is not None:
        return coastline.stroke_color
    return RGBAColor(40, 60, 80)


def sheets_own_land(profile: StyleProfile) -> RGBAColor:
    """The preset's own land, however it stated ``buildings``.

    A border is drawn against the ground it partitions rather than against the
    sea, so it is the one derivation here that reaches for this rather than for
    the water.
    """
    buildings = profile.layer_styles.get("buildings")
    if buildings is None:
        return RGBAColor(200, 190, 175)
    return buildings.fill_color if buildings.fill_enabled else buildings.stroke_color


def _luma(colour: RGBAColor) -> float:
    """Rec. 601 luma on 0–1, the cheap standard answer to "is this light or dark"."""
    return (299.0 * colour.r + 587.0 * colour.g + 114.0 * colour.b) / 255_000.0


def ground_as_drawn(profile: StyleProfile) -> RGBAColor:
    """The ground a relief layer actually lands on.

    Not the background: the hillshade and the contours are both drawn over
    ``elevation_bands``, so where those are filled *they* are the ground. Asking
    the background instead is wrong on any preset pairing dark paper with a pale
    sheet — ``Night`` is exactly that, and judging by its background alone puts a
    white highlight onto near-white bands and shades nothing at all.

    A band fill that is not opaque is sitting on the background, so the two are
    mixed rather than one chosen.
    """
    bands = profile.layer_styles.get("elevation_bands")
    if bands is None or not bands.fill_enabled:
        return profile.background
    return mix(profile.background, bands.fill_color, bands.fill_color.a / 255.0)


def derived_hillshade(profile: StyleProfile) -> LayerStyle:
    """Relief shading for a preset that has never heard of it.

    Ported from the macOS ``derivedHillshade``. Every one of the sixteen presets
    predates the hillshade, so none says anything about how it should look, and
    without this every one of them fell through to the shared default.

    It is derived as a **wash that adds one tone and leaves the other alone**,
    which is the part that is easy to get wrong. Relief shading is drawn over the
    elevation bands, the water and the land cover — not over the background — so
    the untouched end of the ramp has to be *nothing at all*, carried as zero
    alpha. Setting it to the background colour instead paints the paper over
    whatever the map had already put there, and the sheet goes flat and grey
    while every individual colour still looks reasonable.

    Which end is untouched depends on what is underneath. Pale ground takes
    shadow: dark where it turns away, nothing where it faces the sun. Dark ground
    takes light: nothing in the shadows, which are already dark, and a highlight
    on the faces that catch the sun. Backwards does not fail loudly — it produces
    a sheet where every colour is defensible and the relief reads inside out.
    """
    # Bands share their edges. Stroking them draws every seam between tones,
    # which is the one thing shading must not have.
    style = LayerStyle(stroke_width=0.0, fill_enabled=True)

    if _luma(ground_as_drawn(profile)) >= 0.5:
        # Band 0 is the deepest shadow, the last band the brightest.
        style.fill_color = RGBAColor(0, 0, 0, 140)
        style.fill_color_high = RGBAColor(0, 0, 0, 0)
    else:
        style.fill_color = RGBAColor(255, 255, 255, 0)
        style.fill_color_high = RGBAColor(255, 255, 255, 105)

    # Under the contours, not over them: relief is what the linework is drawn on,
    # and at full strength it buries the map it is supporting.
    style.opacity = 0.55
    return style


def _relief_ink(profile: StyleProfile) -> RGBAColor:
    """The land's own darkest tone: the high end of the elevation ramp.

    A contour describes the ground, so it is drawn in the ground's colour rather
    than in the sea's. Every hand-picked contour in this file already follows
    that relationship — `Terrain Study` draws ``120,105,81`` under a ramp topping
    out at ``150,122,96``, `Hypsometric Relief` ``96,78,58`` under ``146,114,84``
    — which is what makes contours read as belonging to the relief instead of
    lying on top of it.
    """
    bands = profile.layer_styles.get("elevation_bands")
    if bands is not None:
        if bands.fill_enabled and bands.fill_color_high is not None:
            return bands.fill_color_high
        return bands.stroke_color
    return sheets_own_land(profile)


def derived_contour_style(profile: StyleProfile, layer: str) -> LayerStyle | None:
    """Contours for a preset that has never named them, or ``None`` otherwise.

    Nine presets still left the pair to the fallback after `Clean Atlas` was
    given its ink by hand. A derivation serves them better than one chosen
    colour could: the brown that reads on `Terrain Study` is invisible on
    `Night`, whose ground is near-black, and the direction of the correction
    below is decided by the ground rather than assumed.

    An explicit entry always wins, so a preset whose contours are chosen by eye
    keeps them.
    """
    if layer not in CONTOUR_LAYERS:
        return None

    ground = ground_as_drawn(profile)
    ink = _relief_ink(profile)
    index = layer == "terrain_index_contours"

    # Push the ink away from the ground it is drawn on, so the line reads on a
    # dark sheet and a pale one alike. Index lines go further, being the ones
    # that carry the number.
    away = RGBAColor(0, 0, 0) if _luma(ground) >= 0.5 else RGBAColor(255, 255, 255)
    stroke = mix(ink, away, 0.45 if index else 0.25)

    # The weights `Clean Atlas` was given by hand, which came from `Terrain
    # Study` and pair a readable minor line with an index line that reads as the
    # one carrying the number.
    return LayerStyle(
        stroke_width=1.15 if index else 0.7,
        fill_enabled=False,
        stroke_color=stroke,
        opacity=0.8 if index else 0.55,
    )


def derived_ocean_style(profile: StyleProfile, layer: str) -> LayerStyle | None:
    """One of the four ocean layers for a preset that has never heard of them,
    or ``None`` for any other layer."""
    if layer not in OCEAN_LAYERS:
        return None

    water = sheets_own_water(profile)
    ink = sheets_own_ink(profile)

    if layer == "sst_bands":
        return _sea_temperature_bands(profile, water, ink)
    if layer == "sst_contours":
        # Isotherms: the sea's own ink at half strength. Finer than the
        # isobaths they cross, because when both are on the depth is the ground
        # and the temperature is the reading taken over it.
        #
        # `palette_sheet` scales this by its own `contourWeight` knob; a preset
        # has no equivalent, so the base weight stands on its own here.
        return LayerStyle(
            stroke_width=0.4,
            fill_enabled=False,
            stroke_color=mix(water, ink, 0.5),
            opacity=0.65,
        )
    if layer == "current_streamlines":
        # Drawn in the sea's own ink rather than an accent: the streamlines
        # cross the whole sheet, and a second accent colour on top of a chart is
        # one competing claim too many. Each run carries its own `stroke_scale`,
        # 0.45 to 2.2 of this, so this is the base that thickens where the water
        # runs rather than a width anything is drawn at.
        #
        # **These are the macOS application's numbers, not this file's palette
        # sheet's.** `palette_sheet` says 1.1 and mix 0.62 here where the port
        # says 0.75 and 0.7 — and since both apps scale by the identical
        # 0.45–2.2, that is not two framings of one intent but a genuine
        # disagreement, which draws every streamline ~47% heavier here. Surface
        # currents existed on the macOS side first and were ported onto this
        # one, so its values are the original and these are drift.
        #
        # Taking the origin's numbers here leaves this file briefly at odds with
        # `palette_sheet` in the same repository. That is the lesser of the two:
        # a preset and a palette differing within one app is visible to whoever
        # switches between them, where two apps differing is visible to nobody
        # until somebody renders the same sheet twice. The palette sheets need
        # reconciling across the two repositories in their own right — the whole
        # marine layer diverges, not only this line.
        return LayerStyle(
            stroke_width=0.75,
            fill_enabled=False,
            stroke_color=mix(water, ink, 0.7),
            opacity=0.85,
            line_cap="round",
        )
    # A ferry route is a line on the water and the faintest thing drawn on it:
    # it is a service, not a measurement, and it must not read as an isobath.
    return LayerStyle(
        stroke_width=0.6,
        fill_enabled=False,
        stroke_color=mix(water, ink, 0.2),
        opacity=0.7,
        line_cap="butt",
    )


def _sea_temperature_bands(profile: StyleProfile, water: RGBAColor, ink: RGBAColor) -> LayerStyle:
    """Filled temperature bands, cool through warm.

    **It follows the land rather than overruling it**, the rule
    ``derived_depth_bands`` follows for the sea floor: a preset that leaves
    ``elevation_bands`` unfilled has decided the sheet is linework, and forcing
    a temperature wash onto it would be this derivation deciding what the sheet
    is. So the fill is enabled only where the land's bands are.

    Unlike the depth ramp, the two stops are **not** sorted by luminance. Deep
    is darker is a thing a reader assumes about water without being told; warm
    is darker is not, and the ends here are cool and warm rather than near and
    far. They stay where ``palette_sheet`` puts them: the sea's own colour at
    the cold end, the land's at the warm one.
    """
    bands = profile.layer_styles.get("elevation_bands")
    fill_enabled = bands.fill_enabled if bands is not None else False
    style = LayerStyle(stroke_width=0.0, fill_enabled=fill_enabled)
    if not fill_enabled:
        return style

    land = sheets_own_land(profile)
    style.fill_color = mix(water, ink, 0.35)
    style.fill_color_high = mix(land, ink, 0.15)
    # Low, and deliberately: these sit over the sea floor they describe, and a
    # temperature that hides the isobaths has replaced the chart it annotates.
    style.opacity = 0.42
    return style


def derived_admin_boundaries(profile: StyleProfile) -> LayerStyle:
    """A border for a preset that has never named one.

    Drawn in the sheet's own land darkened towards its ink, lightly: a border
    follows a coast or a road network it must not outshout, and it is the one
    line here that belongs to the ground rather than to the water.

    Never filled. A boundary is a partition, and filling it paints one side out.
    """
    land = sheets_own_land(profile)
    ink = sheets_own_ink(profile)
    return LayerStyle(
        stroke_width=0.8,
        fill_enabled=False,
        stroke_color=mix(land, ink, 0.15),
        opacity=0.55,
    )


def derived_state_boundaries(profile: StyleProfile) -> LayerStyle:
    """A state line: the country border's colour at a lighter weight, so the
    two read as one family and the country still reads first."""
    return replace(derived_admin_boundaries(profile), stroke_width=0.5, opacity=0.5)


def derived_county_boundaries(profile: StyleProfile) -> LayerStyle:
    """A county line, the finest of the three.

    A sheet of the United States carries three thousand of them, so it has to
    stay a texture under the coast and the state lines rather than a net drawn
    over them.
    """
    return replace(derived_admin_boundaries(profile), stroke_width=0.25, opacity=0.4)
