"""Art-first preset system for map rendering workflows."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from hipparchus.application.derived_styles import (
    derived_admin_boundaries as derived_admin_boundaries,
    derived_county_boundaries as derived_county_boundaries,
    derived_state_boundaries as derived_state_boundaries,
)
from hipparchus.application.derived_styles import (
    derived_contour_style as derived_contour_style,
)
from hipparchus.application.derived_styles import (
    derived_hillshade as derived_hillshade,
)
from hipparchus.application.derived_styles import (
    derived_ocean_style as derived_ocean_style,
)
from hipparchus.application.derived_styles import (
    sheets_own_ink as _sheets_own_ink,
)
from hipparchus.application.derived_styles import (
    sheets_own_water as _sheets_own_water,
)
from hipparchus.application.derived_styles import (
    unstyled_fallback as unstyled_fallback,
)
from hipparchus.application.preset_styles import (
    CONTOUR_PAPER as CONTOUR_PAPER,
    NIGHT_GROUND as NIGHT_GROUND,
    _base_styles,
    _blueprint_styles,
    _clean_atlas_styles,
    _coastal_survey_styles,
    _contour_study_styles,
    _editorial_print_styles,
    _fragmented_styles,
    _hypsometric_styles,
    _monochrome_figure_ground_styles,
    _night_styles,
    _organic_styles,
    _osm_standard_styles,
    _relief_sheet_styles,
    _soft_urban_styles,
    _technical_blueprint_styles,
    _terrain_study_styles,
)
from hipparchus.application.palettes import mix

# Re-exported for the public preset API; consumers import QualityMode from here.
from hipparchus.application.quality import QualityMode as QualityMode
from hipparchus.data_sources.seamarks import ALL_LAYERS as SEAMARK_LAYERS
from hipparchus.rendering.models import LayerStyle, RGBAColor

@dataclass(slots=True, frozen=True)
class GeometryPipelineProfile:
    """Defines enabled derivations and processing intensity."""

    simplify_tolerance_preview: float = 1.5
    simplify_tolerance_export: float = 0.6
    smoothing_iterations: int = 1
    derive_voronoi: bool = False
    derive_delaunay: bool = False
    derive_hex_grid: bool = False
    derive_circle_packing: bool = False
    # Relief is ground, and buildings sit on it, so by default the hillshade
    # draws underneath them -- correct in open country, but in a dense city it
    # leaves the shading visible only in the parks and the street corridors.
    # Switching this on lifts it over the whole built environment instead,
    # stopping just short of the labels.
    relief_over_buildings: bool = False
    hex_radius: float = 60.0
    circle_min_radius: float = 8.0
    circle_max_radius: float = 30.0
    max_on_screen_features_per_layer: int = 10000
    layer_smoothing_iterations: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class StyleProfile:
    """Named style set for composable map layer visuals."""

    layer_styles: dict[str, LayerStyle]
    # The ground the layers sit on. Light by default so every daylight preset
    # keeps rendering exactly as before; dark presets override it.
    background: RGBAColor = field(default_factory=lambda: RGBAColor(250, 250, 250, 255))


@dataclass(slots=True, frozen=True)
class ArtisticPreset:
    """High-level artistic preset."""

    name: str
    geometry_profile: GeometryPipelineProfile
    style_profile: StyleProfile


DEFAULT_PRESET_NAME = "Urban Structure"


def default_preset(name: str = DEFAULT_PRESET_NAME) -> ArtisticPreset:
    presets = _preset_registry()
    return presets.get(name, presets[DEFAULT_PRESET_NAME])


def preset_names() -> tuple[str, ...]:
    return tuple(_preset_registry().keys())


def _derived_luma(colour: RGBAColor) -> float:
    """Rec. 601 luma, the cheap standard answer to "is this light or dark"."""
    return (299 * colour.r + 587 * colour.g + 114 * colour.b) / 1000.0


def derived_depth_bands(profile: StyleProfile) -> LayerStyle:
    """Depth bands for a preset that has never heard of them.

    Not one of the built-in presets names ``depth_bands`` — they predate it, and
    ``palette_sheet.style_profile`` is the only place that has ever styled it —
    so a sheet drawn from a preset with no ``--palette`` override rendered the
    sea floor in the shared default: a single flat grey box, no ramp at all.
    This reads the same water and ink `derived_seamark_style` reads, mixed the
    same way `palette_sheet` mixes them for a palette's own eight colours.

    **It follows the land rather than overruling it.** A preset that leaves
    ``elevation_bands`` unfilled has decided the sheet is linework, and forcing
    a filled sea onto it would be this derivation overruling that choice — so
    the fill is enabled only where the land's bands are.
    """
    bands = profile.layer_styles.get("elevation_bands")
    fill_enabled = bands.fill_enabled if bands is not None else False
    style = LayerStyle(stroke_width=0.0, fill_enabled=fill_enabled)
    if not fill_enabled:
        return style

    water = _sheets_own_water(profile)
    ink = _sheets_own_ink(profile)

    # **Deep is darker, and which mix *is* darker depends on the sheet.** On a
    # dark preset the ink is pale and the paper is near-black, so naming the
    # ends "toward ink" and "toward ground" would invert the ramp — the same
    # trap `palette_sheet.style_profile` avoids for the same reason. So the two
    # mixes are computed and sorted by luminance rather than assigned by name.
    toward_ink = mix(water, ink, 0.5)
    toward_ground = mix(water, profile.background, 0.55)
    deep, shallow = sorted((toward_ink, toward_ground), key=_derived_luma)
    style.fill_color = deep
    style.fill_color_high = shallow
    style.opacity = bands.opacity if bands is not None else 0.9
    return style


def derived_seamark_style(profile: StyleProfile, layer: str) -> LayerStyle | None:
    """Sea marks for a preset that has never heard of them, or ``None`` for any
    other layer.

    The same gap `derived_depth_bands` closes, and the same shape of bug: no
    preset names any of the six ``seamark_*`` layers, so every one of them fell
    through to the shared default — a filled grey box round a chart symbol that
    needs to read as a light, a buoy or a wreck to mean anything. The weights
    and mixes below are `palette_sheet.style_profile`'s own for these six
    layers, read here off what the preset itself already chose rather than off
    a full palette.

    **Areas follow the land rather than overrule it**, the same rule
    `derived_depth_bands` follows for the sea: a linework preset that leaves
    ``buildings`` unfilled gets unfilled restricted areas too, because a solid
    area wash is exactly the kind of mass a linework sheet has decided not to
    draw. Harbours and hazards are never filled and the three point marks —
    lights, buoys, beacons — are always filled, in both cases regardless of
    that choice, matching `palette_sheet.style_profile` exactly: a chart
    symbol has to be there to be read at all.
    """
    if layer not in SEAMARK_LAYERS:
        return None

    water = _sheets_own_water(profile)
    ink = _sheets_own_ink(profile)
    ground = profile.background
    mark_ink = mix(water, ink, 0.62)

    if layer == "seamark_lights":
        return LayerStyle(
            stroke_width=1.0, stroke_color=mark_ink,
            fill_enabled=True, fill_color=mix(water, ground, 0.55), opacity=0.95,
        )
    if layer == "seamark_buoys":
        return LayerStyle(
            stroke_width=1.0, stroke_color=mark_ink,
            fill_enabled=True, fill_color=mix(water, ground, 0.35), opacity=0.95,
        )
    if layer == "seamark_beacons":
        return LayerStyle(
            stroke_width=1.0, stroke_color=mark_ink,
            fill_enabled=True, fill_color=mix(water, ground, 0.45), opacity=0.95,
        )
    if layer == "seamark_hazards":
        return LayerStyle(stroke_width=1.1, stroke_color=mix(water, ink, 0.78), fill_enabled=False)
    if layer == "seamark_harbours":
        return LayerStyle(
            stroke_width=0.7, stroke_color=mix(water, ink, 0.4),
            fill_enabled=False, opacity=0.75,
        )
    if layer == "seamark_areas":
        buildings = profile.layer_styles.get("buildings")
        fills_areas = buildings.fill_enabled if buildings is not None else True
        style = LayerStyle(
            stroke_width=0.8, stroke_color=mix(water, ink, 0.52),
            fill_enabled=fills_areas, opacity=0.6,
        )
        if fills_areas:
            style.fill_color = mix(water, ink, 0.24)
        return style
    return None


def resolve_style(profile: StyleProfile, layer_name: str) -> LayerStyle:
    """The style for a layer, falling back to a derivation for the layers no
    preset has ever named and to the shared default for everything else.

    A layer a preset says nothing about and this has no derivation for is drawn
    with `LayerStyle`'s own default rather than skipped, so a new source shows
    up as *something* the first time it appears instead of silently not
    rendering.
    """
    style = profile.layer_styles.get(layer_name)
    if style is not None:
        return style
    if layer_name == "depth_bands":
        return derived_depth_bands(profile)
    if layer_name == "terrain_hillshade":
        return derived_hillshade(profile)
    if layer_name == "admin_boundaries":
        return derived_admin_boundaries(profile)
    if layer_name == "state_boundaries":
        return derived_state_boundaries(profile)
    if layer_name == "county_boundaries":
        return derived_county_boundaries(profile)
    derived = derived_contour_style(profile, layer_name)
    if derived is not None:
        return derived
    derived = derived_seamark_style(profile, layer_name)
    if derived is not None:
        return derived
    derived = derived_ocean_style(profile, layer_name)
    if derived is not None:
        return derived
    return unstyled_fallback()


def resolve_preset_name(requested: str, available: Iterable[str], fallback: str) -> str:
    """Map a requested preset name onto one that exists, or fall back.

    Backs HIPPARCHUS_START_PRESET, where the name is typed on a command line:
    matching is case-insensitive and tolerates padding, and anything unknown
    yields the fallback rather than leaving the dropdown on a name that is not
    in it. ``available`` is passed in so custom presets are selectable too.
    """
    candidate = requested.strip()
    if not candidate:
        return fallback
    options = tuple(available)
    for option in options:
        if option.casefold() == candidate.casefold():
            return option
    return fallback


def _preset_registry() -> dict[str, ArtisticPreset]:
    return {
        "OSM Standard": ArtisticPreset(
            name="OSM Standard",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.0,
                simplify_tolerance_export=0.0,
                derive_voronoi=False,
                derive_delaunay=False,
                derive_hex_grid=False,
                derive_circle_packing=False,
                max_on_screen_features_per_layer=200000,
            ),
            style_profile=StyleProfile(layer_styles=_osm_standard_styles()),
        ),
        DEFAULT_PRESET_NAME: ArtisticPreset(
            name=DEFAULT_PRESET_NAME,
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.0,  # NO SIMPLIFICATION - raw OSM data
                simplify_tolerance_export=0.0,  # NO SIMPLIFICATION - raw OSM data
                derive_voronoi=False,
                derive_delaunay=False,
                derive_hex_grid=False,
                derive_circle_packing=False,
                max_on_screen_features_per_layer=200000,  # 200k features per layer - maximum detail
            ),
            style_profile=StyleProfile(layer_styles=_base_styles()),
        ),
        "Fragmented Urban": ArtisticPreset(
            name="Fragmented Urban",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.0,  # NO SIMPLIFICATION
                simplify_tolerance_export=0.0,  # NO SIMPLIFICATION
                derive_voronoi=False,
                derive_delaunay=False,
                derive_hex_grid=False,
                derive_circle_packing=False,
                hex_radius=45.0,
                max_on_screen_features_per_layer=200000,
            ),
            style_profile=StyleProfile(layer_styles=_fragmented_styles()),
        ),
        "Organic Field": ArtisticPreset(
            name="Organic Field",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.0,  # NO SIMPLIFICATION
                simplify_tolerance_export=0.0,  # NO SIMPLIFICATION
                derive_voronoi=False,
                derive_delaunay=False,
                derive_hex_grid=False,
                derive_circle_packing=False,
                circle_min_radius=10.0,
                circle_max_radius=36.0,
                max_on_screen_features_per_layer=200000,
            ),
            style_profile=StyleProfile(layer_styles=_organic_styles()),
        ),
        "Blueprint Relief": ArtisticPreset(
            name="Blueprint Relief",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.0,  # NO SIMPLIFICATION
                simplify_tolerance_export=0.0,  # NO SIMPLIFICATION
                derive_voronoi=False,
                derive_delaunay=False,
                derive_hex_grid=False,
                derive_circle_packing=False,
                hex_radius=70.0,
                max_on_screen_features_per_layer=200000,
            ),
            style_profile=StyleProfile(layer_styles=_blueprint_styles()),
        ),
        "Editorial Print": ArtisticPreset(
            name="Editorial Print",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.25,
                simplify_tolerance_export=0.05,
                smoothing_iterations=2,
                derive_voronoi=False,
                derive_delaunay=False,
                max_on_screen_features_per_layer=240000,
            ),
            style_profile=StyleProfile(layer_styles=_editorial_print_styles()),
        ),
        "Clean Atlas": ArtisticPreset(
            name="Clean Atlas",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.35,
                simplify_tolerance_export=0.08,
                smoothing_iterations=1,
                derive_voronoi=False,
                derive_delaunay=False,
                max_on_screen_features_per_layer=220000,
            ),
            style_profile=StyleProfile(layer_styles=_clean_atlas_styles()),
        ),
        "Soft Urban": ArtisticPreset(
            name="Soft Urban",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.2,
                simplify_tolerance_export=0.04,
                smoothing_iterations=1,
                derive_voronoi=False,
                derive_delaunay=False,
                max_on_screen_features_per_layer=220000,
            ),
            style_profile=StyleProfile(layer_styles=_soft_urban_styles()),
        ),
        "Technical Blueprint": ArtisticPreset(
            name="Technical Blueprint",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.15,
                simplify_tolerance_export=0.03,
                smoothing_iterations=1,
                derive_voronoi=False,
                derive_delaunay=False,
                derive_hex_grid=False,
                hex_radius=70.0,
                max_on_screen_features_per_layer=220000,
            ),
            style_profile=StyleProfile(layer_styles=_technical_blueprint_styles()),
        ),
        "Terrain Study": ArtisticPreset(
            name="Terrain Study",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.4,
                simplify_tolerance_export=0.1,
                smoothing_iterations=1,
                derive_voronoi=False,
                derive_delaunay=False,
                derive_hex_grid=False,
                derive_circle_packing=False,
                max_on_screen_features_per_layer=200000,
            ),
            style_profile=StyleProfile(layer_styles=_terrain_study_styles()),
        ),
        "Hypsometric Relief": ArtisticPreset(
            name="Hypsometric Relief",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.3,
                simplify_tolerance_export=0.06,
                smoothing_iterations=2,
                derive_voronoi=False,
                derive_delaunay=False,
                derive_hex_grid=False,
                derive_circle_packing=False,
                max_on_screen_features_per_layer=240000,
            ),
            style_profile=StyleProfile(
                layer_styles=_hypsometric_styles(),
                background=RGBAColor(247, 245, 240, 255),
            ),
        ),
        "Relief Sheet": ArtisticPreset(
            name="Relief Sheet",
            geometry_profile=GeometryPipelineProfile(
                # Hundreds of nested hairlines: simplify barely at all, or the
                # nesting loses the tight parallelism that carries the relief.
                simplify_tolerance_preview=0.12,
                simplify_tolerance_export=0.02,
                smoothing_iterations=1,
                derive_voronoi=False,
                derive_delaunay=False,
                derive_hex_grid=False,
                derive_circle_packing=False,
                max_on_screen_features_per_layer=400000,
            ),
            style_profile=StyleProfile(
                layer_styles=_relief_sheet_styles(),
                background=CONTOUR_PAPER,
            ),
        ),
        "Contour Study": ArtisticPreset(
            name="Contour Study",
            geometry_profile=GeometryPipelineProfile(
                # Contours arrive dense and already clean, so simplify lightly
                # and smooth twice: the look lives entirely in the linework.
                simplify_tolerance_preview=0.35,
                simplify_tolerance_export=0.08,
                smoothing_iterations=2,
                derive_voronoi=False,
                derive_delaunay=False,
                derive_hex_grid=False,
                derive_circle_packing=False,
                max_on_screen_features_per_layer=200000,
            ),
            style_profile=StyleProfile(
                layer_styles=_contour_study_styles(),
                background=CONTOUR_PAPER,
            ),
        ),
        "Monochrome Figure Ground": ArtisticPreset(
            name="Monochrome Figure Ground",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.12,
                simplify_tolerance_export=0.02,
                smoothing_iterations=1,
                derive_voronoi=False,
                derive_delaunay=False,
                max_on_screen_features_per_layer=240000,
            ),
            style_profile=StyleProfile(layer_styles=_monochrome_figure_ground_styles()),
        ),
        "Coastal Survey": ArtisticPreset(
            name="Coastal Survey",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.15,
                simplify_tolerance_export=0.03,
                smoothing_iterations=2,
                derive_voronoi=False,
                derive_delaunay=False,
                max_on_screen_features_per_layer=220000,
                layer_smoothing_iterations={"coastline": 3, "water": 2},
            ),
            style_profile=StyleProfile(layer_styles=_coastal_survey_styles()),
        ),
        "Night": ArtisticPreset(
            name="Night",
            geometry_profile=GeometryPipelineProfile(
                simplify_tolerance_preview=0.0,
                simplify_tolerance_export=0.0,
                smoothing_iterations=1,
                derive_voronoi=False,
                derive_delaunay=False,
                max_on_screen_features_per_layer=200000,
            ),
            style_profile=StyleProfile(
                layer_styles=_night_styles(),
                background=NIGHT_GROUND,
            ),
        ),
    }
