"""A whole map's worth of layers, derived from a palette's eight colours.

Everything here is *derived* rather than chosen, which is the entire argument
for palettes: a colour scheme picked layer by layer drifts, and one obtained by
mixing from a small set cannot. The mixes are the macOS application's, which
took them from the style-pack build script, and they are kept identical for the
same reason — if two implementations of one derivation disagreed, there would
be no way to tell which was wrong.
"""

from __future__ import annotations

from hipparchus.application.palettes import BLUE, TURQUOISE, Palette, mix
from hipparchus.application.presets import ArtisticPreset, StyleProfile
from hipparchus.rendering.models import LayerStyle, RGBAColor


#: The road classes, widest first. Every sheet draws all of them: one that
#: styles ``roads`` but not ``roads_motorway`` loses its motorways silently,
#: which reads as missing data rather than as a style.
ROAD_WIDTHS: tuple[tuple[str, float], ...] = (
    ("roads_motorway", 3.2),
    ("roads_trunk", 2.8),
    ("roads_primary", 2.3),
    ("roads_secondary", 1.8),
    ("roads_tertiary", 1.3),
    ("roads_residential", 0.9),
    ("roads_service", 0.6),
    ("roads_other", 0.5),
    ("roads", 1.0),
)


def _style(
    *,
    stroke: float = 0.0,
    stroke_color: RGBAColor | None = None,
    fill: RGBAColor | None = None,
    fill_alpha: int = 255,
    #: The far end of a two-stop ramp, for layers whose fill varies by
    #: ``band_index`` rather than being one colour. Only the band layers use it,
    #: and a palette has to state it for ``depth_bands``, which no preset knows.
    fill_high: RGBAColor | None = None,
    opacity: float = 1.0,
    cap: str = "round",
    casing: float = 0.0,
    casing_color: RGBAColor | None = None,
    halo: RGBAColor | None = None,
) -> LayerStyle:
    """One layer, with only what it needs stated."""
    style = LayerStyle(
        stroke_width=stroke,
        # An unstated stroke falls back to the shared ink rather than to the
        # sheet's own, because that is what the build script does and what the
        # shipped packs carry. Matching it is not endorsing it; it is refusing
        # to have two answers.
        stroke_color=stroke_color if stroke_color is not None else _DEFAULT_INK,
        opacity=opacity,
        line_cap=cap,
        casing_width=casing,
        fill_enabled=fill is not None,
    )
    if fill is not None:
        style.fill_color = RGBAColor(fill.r, fill.g, fill.b, fill_alpha)
    if fill_high is not None:
        style.fill_color_high = RGBAColor(fill_high.r, fill_high.g, fill_high.b, fill_alpha)
    if casing_color is not None:
        style.casing_color = casing_color
    if halo is not None:
        style.label_halo_color = RGBAColor(halo.r, halo.g, halo.b, 225)
        style.label_halo_width = 2.0
    return style


#: The build script's module-level ink, which an unstated stroke falls back to.
_DEFAULT_INK = RGBAColor(17, 34, 51)


def _luma(colour: RGBAColor) -> float:
    """Rec. 601, the cheap standard answer to "is this light or dark"."""
    return (299 * colour.r + 587 * colour.g + 114 * colour.b) / 255_000.0


def _hillshade(palette: Palette) -> LayerStyle:
    """Relief shading in this palette's own ink.

    Shading is drawn *over* the ground rather than instead of it, so the
    untouched end of the ramp has to be nothing at all — carried as zero alpha,
    not as the paper colour, which would paint over whatever the map had
    already put there and flatten the sheet.

    Which end is untouched depends on the paper. Pale ground takes shadow: dark
    where it turns away, nothing where it faces the sun. Dark ground takes
    light, because its shadows are already dark. Getting that backwards does
    not fail loudly — it produces a sheet where every colour is defensible and
    the relief reads inside out.
    """
    ink = palette.ink
    style = LayerStyle(
        # Bands share their edges, so a stroke would draw every seam.
        stroke_width=0.0,
        stroke_color=RGBAColor(ink.r, ink.g, ink.b, 0),
        fill_enabled=True,
        # Under the linework, never over it: relief is what a map is drawn on.
        opacity=0.55,
        # Moot at zero width, and stated anyway so this sheet and the shipped
        # style packs are the same object rather than nearly the same one.
        line_cap="round",
    )
    if _luma(palette.ground) < 0.5:
        style.fill_color = RGBAColor(ink.r, ink.g, ink.b, 0)
        style.fill_color_high = RGBAColor(ink.r, ink.g, ink.b, 105)
    else:
        style.fill_color = RGBAColor(ink.r, ink.g, ink.b, 140)
        style.fill_color_high = RGBAColor(ink.r, ink.g, ink.b, 0)
    return style


def style_profile(palette: Palette) -> StyleProfile:
    """The style profile this palette makes on its own."""
    ground = palette.ground
    ink = palette.ink
    water = palette.water
    land = palette.land
    contour = palette.contour
    vegetation = palette.vegetation

    styles: dict[str, LayerStyle] = {}

    for layer, width in ROAD_WIDTHS:
        scaled = width * palette.roadScale
        styles[layer] = _style(
            stroke=scaled,
            stroke_color=palette.road,
            casing=scaled + 1.1,
            casing_color=palette.roadCasing,
            halo=ground,
        )

    styles["water"] = _style(
        stroke=0.6,
        stroke_color=mix(water, ink, 0.25),
        fill=water if palette.fillsSea else None,
    )
    styles["coastline"] = _style(stroke=1.6, stroke_color=mix(water, ink, 0.45))
    styles["bathymetry"] = _style(
        stroke=0.5 * palette.contourWeight,
        stroke_color=mix(water, ground, 0.4),
        opacity=0.9,
    )
    # Sea marks, from each palette's own eight colours rather than chart red and
    # green. **Shape carries the meaning here and colour does not** — a can is
    # square and a cone is pointed whatever they are painted — so the marks can
    # stay in the palette without losing what they say.
    #
    # The stroke is ordinary linework, ~1.0. These were 3–4pt in the macOS port
    # while they were still dots, because a point *is* its stroke to a renderer;
    # the moment they became shapes those numbers closed the light flare into a
    # blob and thickened every mast into a smudge. Symbols are outlines, and
    # outlines want an outline's weight.
    # **These are the macOS application's values, and this file used to disagree
    # with it on every one of them.** Sea marks were written there first and
    # ported here, so where the two differ the port is drift rather than a second
    # opinion — and nothing checked it, because `palette-parity.json` compares
    # the Swift engine against the pack builder in that same repository, not
    # against this file. Six marks and the currents had quietly gone their own
    # way: one shared `mark_ink` here against a colour chosen per mark there,
    # filled discs here against outlines with halos there.
    #
    # The per-mark reasoning is the origin's and is kept with it: a beacon is
    # fixed to the ground and drawn like it, a buoy is afloat and lighter on the
    # page for it, a wreck exists to say "not here" and takes the ink undiluted,
    # and a light is what a reader looks for first, so its flare is filled and
    # its weight comes from its area rather than its edge.
    #
    # `HaloedMarkTests` pins these, and the Swift `PaletteTests` pins the same
    # numbers from the other side.
    styles["seamark_beacons"] = _style(
        stroke=1.0, stroke_color=mix(land, ink, 0.6), halo=ground
    )
    styles["seamark_buoys"] = _style(
        stroke=0.9, stroke_color=mix(water, ink, 0.65), halo=ground
    )
    styles["seamark_hazards"] = _style(
        stroke=1.05, stroke_color=ink, opacity=0.95, halo=ground
    )
    styles["seamark_lights"] = _style(
        stroke=0.9, stroke_color=ink,
        fill=mix(ground, ink, 0.15), fill_alpha=210, halo=ground,
    )
    styles["seamark_harbours"] = _style(
        stroke=0.8, stroke_color=mix(land, ink, 0.45),
        fill=mix(ground, land, 0.35), fill_alpha=70, opacity=0.85,
    )
    # Rules drawn as ground, so they sit under everything and read as an area
    # rather than as another object competing with the marks.
    #
    # **A tenth of the way from water to ink, at 0.45 opacity, was water.** Sixty
    # restricted and routed areas drew nothing at all over the Elbe, which the
    # feature count could not show and the render did in one look. An area that
    # is a *rule* has to be visible enough to be obeyed; it is the edge that
    # matters, so the stroke carries most of the increase and the fill only
    # enough to tell inside from out.
    styles["seamark_areas"] = _style(
        stroke=0.7, stroke_color=mix(water, ink, 0.55),
        fill=mix(water, ink, 0.3), fill_alpha=28, opacity=0.75,
    )
    # An ocean scalar -- sea surface temperature today, whatever ERDDAP is
    # pointed at next. Warm reads as the palette's land and cool as its water,
    # which is not a physical claim but is the association every reader
    # already has, and it keeps the sheet inside its eight colours rather than
    # importing a rainbow.
    styles["sst_bands"] = _style(
        stroke=0, fill=mix(water, ink, 0.35),
        fill_high=mix(land, ink, 0.15), opacity=0.42,
    )
    styles["sst_contours"] = _style(
        stroke=0.4 * palette.contourWeight,
        stroke_color=mix(water, ink, 0.5), opacity=0.65,
    )
    # Surface currents. Drawn in the sea's own ink rather than an accent: the
    # streamlines cross the whole sheet, and a second accent colour on top of a
    # chart is one competing claim too many. The weight varies per feature —
    # `stroke_scale` on each run — so this is the middle of the range rather
    # than the whole of it.
    # A streamline is the one line on the sheet whose width means something, so
    # this is the *base* a per-run `stroke_scale` multiplies — 0.45 to 2.2 of it,
    # thin where the water is slack and heavy where it runs. Both applications
    # scale by that identical range, so the 1.1 this file used to carry was not a
    # second way of describing the same intent; it simply drew every streamline
    # around 47% heavier than the app the feature was written in.
    styles["current_streamlines"] = _style(
        stroke=0.75, stroke_color=mix(water, ink, 0.7), opacity=0.85, cap="round"
    )
    styles["buildings"] = _style(
        stroke=0.35, stroke_color=mix(land, ink, 0.4), fill=land, opacity=0.95
    )
    styles["parks"] = _style(fill=mix(ground, vegetation, 0.30))
    styles["forests"] = _style(fill=mix(ground, vegetation, 0.42))
    styles["fields"] = _style(fill=mix(ground, vegetation, 0.16))
    styles["natural"] = _style(fill=mix(ground, vegetation, 0.22))
    styles["landuse"] = _style(fill=mix(ground, land, 0.08))
    styles["railways"] = _style(stroke=0.7, stroke_color=mix(land, ink, 0.55), cap="butt")
    styles["ferry_routes"] = _style(
        stroke=0.6, stroke_color=mix(water, ink, 0.2), opacity=0.7, cap="butt"
    )
    styles["barriers"] = _style(
        stroke=0.4, stroke_color=mix(ground, ink, 0.35), opacity=0.7
    )
    styles["power"] = _style(stroke=0.4, stroke_color=mix(ground, ink, 0.30), opacity=0.6)
    styles["elevation_bands"] = _style(fill=mix(ground, contour, 0.18), opacity=0.6)
    # The sea floor's own ramp, in the palette's water rather than the land's
    # ground.
    #
    # **Deep is darker, and which mix *is* darker depends on the palette.** On a
    # dark sheet the ink is pale and the paper is near-black, so naming the ends
    # "toward ink" and "toward ground" inverts the ramp and draws the deep water
    # bright — every colour still defensible, the sea floor read inside out. So
    # the two mixes are computed and then sorted by luminance rather than
    # assigned by name. A test across all seventeen palettes caught this; on a
    # light palette the two orderings agree, which is why it survived being
    # looked at.
    toward_ink = mix(water, ink, 0.5)
    toward_ground = mix(water, ground, 0.55)
    deep, shallow = sorted((toward_ink, toward_ground), key=_luma)
    styles["depth_bands"] = _style(fill=deep, fill_high=shallow, opacity=0.9)
    styles["terrain_hillshade"] = _hillshade(palette)
    styles["terrain_contours"] = _style(
        stroke=0.3 * palette.contourWeight, stroke_color=contour, opacity=0.7
    )
    styles["terrain_index_contours"] = _style(
        stroke=0.7 * palette.contourWeight,
        stroke_color=mix(contour, ink, 0.3),
        opacity=0.9,
    )
    styles["summits"] = _style(stroke=0.5, stroke_color=ink, opacity=0.85)
    styles["admin_boundaries"] = _style(
        stroke=0.8, stroke_color=mix(land, ink, 0.15), opacity=0.55
    )
    styles["state_boundaries"] = _style(
        stroke=0.5, stroke_color=mix(land, ink, 0.15), opacity=0.5
    )
    styles["county_boundaries"] = _style(
        stroke=0.25, stroke_color=mix(land, ink, 0.15), opacity=0.4
    )
    styles["night_lights"] = _style(fill=TURQUOISE, fill_alpha=90, opacity=0.5)
    styles["places"] = _style(stroke_color=ink, halo=ground)
    styles["street_names"] = _style(stroke_color=mix(ink, ground, 0.25), halo=ground)
    styles["amenities"] = _style(stroke_color=mix(land, ink, 0.2), halo=ground)
    styles["shops"] = _style(stroke_color=mix(land, ink, 0.2), halo=ground)
    styles["earthquakes_shallow"] = _style(stroke=1.0, stroke_color=TURQUOISE)
    styles["earthquakes_intermediate"] = _style(
        stroke=1.0, stroke_color=mix(TURQUOISE, BLUE, 0.5)
    )
    styles["earthquakes_deep"] = _style(stroke=1.0, stroke_color=BLUE)
    styles["satellite_tracks"] = _style(
        stroke=0.6, stroke_color=mix(ink, ground, 0.4), opacity=0.8
    )
    styles["satellite_footprints"] = _style(
        stroke=0.4,
        stroke_color=mix(ink, ground, 0.5),
        fill=ink,
        fill_alpha=30,
        opacity=0.5,
    )

    return StyleProfile(layer_styles=styles, background=ground)


def recoloured(preset: ArtisticPreset, palette: Palette | None) -> ArtisticPreset:
    """This preset's geometry, in another palette's colours.

    The preset keeps everything that is not colour — how much to simplify, how
    much to smooth, how many features to draw — because that is what a preset
    is once colour has been lifted out of it. No palette returns the preset
    untouched, so "the preset's own colours" needs no special case anywhere
    else.
    """
    if palette is None:
        return preset
    return ArtisticPreset(
        name=preset.name,
        geometry_profile=preset.geometry_profile,
        style_profile=style_profile(palette),
    )
