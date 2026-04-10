"""Art-first preset system for map rendering workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from hipparchus.rendering.models import LayerStyle, RGBAColor

QualityMode = Literal["preview", "export"]


@dataclass(slots=True, frozen=True)
class GeometryPipelineProfile:
    """Defines enabled derivations and processing intensity."""

    simplify_tolerance_preview: float = 1.5
    simplify_tolerance_export: float = 0.6
    smoothing_iterations: int = 1
    derive_voronoi: bool = True
    derive_delaunay: bool = True
    derive_hex_grid: bool = False
    derive_circle_packing: bool = False
    hex_radius: float = 60.0
    circle_min_radius: float = 8.0
    circle_max_radius: float = 30.0
    max_on_screen_features_per_layer: int = 10000


@dataclass(slots=True, frozen=True)
class StyleProfile:
    """Named style set for composable map layer visuals."""

    layer_styles: dict[str, LayerStyle]


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
                derive_voronoi=True,
                derive_delaunay=True,
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
                derive_voronoi=True,
                derive_delaunay=True,
                derive_hex_grid=True,
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
                derive_voronoi=True,
                derive_delaunay=False,
                derive_hex_grid=False,
                derive_circle_packing=True,
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
                derive_delaunay=True,
                derive_hex_grid=True,
                derive_circle_packing=False,
                hex_radius=70.0,
                max_on_screen_features_per_layer=200000,
            ),
            style_profile=StyleProfile(layer_styles=_blueprint_styles()),
        ),
    }


def _base_styles() -> dict[str, LayerStyle]:
    return {
        # Road hierarchy with varying stroke widths (major to minor)
        "roads_motorway": LayerStyle(stroke_width=5.0, fill_enabled=False, stroke_color=RGBAColor(50, 80, 120), opacity=1.0),
        "roads_trunk": LayerStyle(stroke_width=4.5, fill_enabled=False, stroke_color=RGBAColor(55, 90, 130), opacity=1.0),
        "roads_primary": LayerStyle(stroke_width=4.0, fill_enabled=False, stroke_color=RGBAColor(220, 100, 80), opacity=1.0),
        "roads_secondary": LayerStyle(stroke_width=3.0, fill_enabled=False, stroke_color=RGBAColor(245, 170, 100), opacity=1.0),
        "roads_tertiary": LayerStyle(stroke_width=2.5, fill_enabled=False, stroke_color=RGBAColor(250, 210, 130), opacity=1.0),
        "roads_residential": LayerStyle(stroke_width=2.0, fill_enabled=False, stroke_color=RGBAColor(240, 240, 240), opacity=1.0),
        "roads_service": LayerStyle(stroke_width=1.5, fill_enabled=False, stroke_color=RGBAColor(200, 200, 200), opacity=0.9),
        "roads_other": LayerStyle(stroke_width=1.5, fill_enabled=False, stroke_color=RGBAColor(180, 180, 180), opacity=0.9),
        "roads": LayerStyle(stroke_width=2.0, fill_enabled=False, stroke_color=RGBAColor(60, 60, 60), opacity=1.0),
        # Buildings and areas
        "buildings": LayerStyle(stroke_width=1.0, fill_enabled=True, fill_color=RGBAColor(220, 220, 220, 255), stroke_color=RGBAColor(100, 100, 100), opacity=1.0),
        "water": LayerStyle(stroke_width=1.0, fill_enabled=True, fill_color=RGBAColor(160, 195, 235, 255), stroke_color=RGBAColor(100, 140, 190), opacity=1.0),
        "parks": LayerStyle(stroke_width=1.0, fill_enabled=True, fill_color=RGBAColor(170, 210, 145, 255), stroke_color=RGBAColor(100, 150, 80), opacity=1.0),
        "railways": LayerStyle(stroke_width=1.5, fill_enabled=False, stroke_color=RGBAColor(80, 80, 80), opacity=1.0),
        # New natural layers
        "forests": LayerStyle(stroke_width=1.0, fill_enabled=True, fill_color=RGBAColor(140, 190, 120, 255), stroke_color=RGBAColor(80, 130, 60), opacity=1.0),
        "fields": LayerStyle(stroke_width=0.8, fill_enabled=True, fill_color=RGBAColor(240, 230, 180, 255), stroke_color=RGBAColor(180, 170, 120), opacity=1.0),
        "natural": LayerStyle(stroke_width=0.8, fill_enabled=True, fill_color=RGBAColor(200, 210, 160, 255), stroke_color=RGBAColor(140, 150, 100), opacity=1.0),
        "coastline": LayerStyle(stroke_width=3.0, fill_enabled=True, fill_color=RGBAColor(140, 180, 220, 255), stroke_color=RGBAColor(50, 100, 150), opacity=1.0),
        "places": LayerStyle(stroke_width=0.0, fill_enabled=False, stroke_color=RGBAColor(0, 0, 0), opacity=1.0),
        # New detailed layers
        "shops": LayerStyle(stroke_width=0.0, fill_enabled=False, stroke_color=RGBAColor(150, 50, 150), opacity=1.0),
        "amenities": LayerStyle(stroke_width=0.0, fill_enabled=False, stroke_color=RGBAColor(50, 150, 50), opacity=1.0),
        "landuse": LayerStyle(stroke_width=0.5, fill_enabled=True, fill_color=RGBAColor(200, 200, 180, 200), stroke_color=RGBAColor(150, 150, 130), opacity=0.8),
        "barriers": LayerStyle(stroke_width=0.5, fill_enabled=False, stroke_color=RGBAColor(100, 100, 100), opacity=0.7),
        "power": LayerStyle(stroke_width=0.5, fill_enabled=False, stroke_color=RGBAColor(150, 150, 150), opacity=0.6),
        # Derived layers
        "voronoi_cells": LayerStyle(stroke_width=0.8, fill_enabled=False, stroke_color=RGBAColor(80, 80, 80), opacity=0.6),
        "delaunay_mesh": LayerStyle(stroke_width=1.0, fill_enabled=False, stroke_color=RGBAColor(60, 60, 60), opacity=0.7),
        "hex_grid": LayerStyle(stroke_width=0.8, fill_enabled=False, stroke_color=RGBAColor(100, 100, 100), opacity=0.5),
        "circle_packing": LayerStyle(stroke_width=0.8, fill_enabled=False, stroke_color=RGBAColor(110, 110, 110), opacity=0.55),
    }


def _osm_standard_styles() -> dict[str, LayerStyle]:
    """Colors and widths matching OpenStreetMap's standard Mapnik/Carto style."""
    return {
        # Roads with casings — OSM renders roads as casing (outline) + fill (inner)
        # Motorway: blue casing, blue fill
        "roads_motorway": LayerStyle(
            stroke_width=7.0, fill_enabled=False,
            stroke_color=RGBAColor(100, 130, 180),  # #6482B4 motorway fill
            casing_width=9.0, casing_color=RGBAColor(50, 70, 130),  # darker casing
            line_cap="round", opacity=1.0,
        ),
        # Trunk: green-ish
        "roads_trunk": LayerStyle(
            stroke_width=6.0, fill_enabled=False,
            stroke_color=RGBAColor(127, 201, 127),  # #7FC97F trunk fill
            casing_width=8.0, casing_color=RGBAColor(80, 150, 80),
            line_cap="round", opacity=1.0,
        ),
        # Primary: warm orange/salmon
        "roads_primary": LayerStyle(
            stroke_width=5.0, fill_enabled=False,
            stroke_color=RGBAColor(228, 109, 113),  # #E46D71 primary fill
            casing_width=7.0, casing_color=RGBAColor(180, 70, 70),
            line_cap="round", opacity=1.0,
        ),
        # Secondary: yellow-orange
        "roads_secondary": LayerStyle(
            stroke_width=4.5, fill_enabled=False,
            stroke_color=RGBAColor(253, 214, 164),  # #FDD6A4 secondary fill
            casing_width=6.5, casing_color=RGBAColor(200, 170, 110),
            line_cap="round", opacity=1.0,
        ),
        # Tertiary: pale yellow/white
        "roads_tertiary": LayerStyle(
            stroke_width=4.0, fill_enabled=False,
            stroke_color=RGBAColor(254, 254, 179),  # #FEFEB3 tertiary fill
            casing_width=5.5, casing_color=RGBAColor(190, 190, 130),
            line_cap="round", opacity=1.0,
        ),
        # Residential: white with gray casing
        "roads_residential": LayerStyle(
            stroke_width=3.0, fill_enabled=False,
            stroke_color=RGBAColor(255, 255, 255),  # white fill
            casing_width=4.5, casing_color=RGBAColor(180, 180, 180),
            line_cap="round", opacity=1.0,
        ),
        # Service: narrower white
        "roads_service": LayerStyle(
            stroke_width=1.5, fill_enabled=False,
            stroke_color=RGBAColor(255, 255, 255),
            casing_width=2.5, casing_color=RGBAColor(190, 190, 190),
            line_cap="round", opacity=1.0,
        ),
        "roads_other": LayerStyle(
            stroke_width=1.5, fill_enabled=False,
            stroke_color=RGBAColor(220, 220, 220),
            casing_width=2.5, casing_color=RGBAColor(180, 180, 180),
            line_cap="round", opacity=0.9,
        ),
        "roads": LayerStyle(
            stroke_width=3.0, fill_enabled=False,
            stroke_color=RGBAColor(255, 255, 255),
            casing_width=4.5, casing_color=RGBAColor(180, 180, 180),
            line_cap="round", opacity=1.0,
        ),
        # Buildings: brownish-gray fill, matching OSM
        "buildings": LayerStyle(
            stroke_width=0.5, fill_enabled=True,
            fill_color=RGBAColor(217, 208, 201, 255),  # #D9D0C9
            stroke_color=RGBAColor(188, 172, 158),      # #BCAC9E
            opacity=1.0,
        ),
        # Water: light blue fill
        "water": LayerStyle(
            stroke_width=0.5, fill_enabled=True,
            fill_color=RGBAColor(170, 211, 223, 255),  # #AAD3DF
            stroke_color=RGBAColor(170, 211, 223),
            opacity=1.0,
        ),
        # Parks/leisure: light green
        "parks": LayerStyle(
            stroke_width=0.5, fill_enabled=True,
            fill_color=RGBAColor(205, 235, 176, 255),  # #CDEBB0
            stroke_color=RGBAColor(180, 210, 150),
            opacity=1.0,
        ),
        # Railways: dark gray dashed-like
        "railways": LayerStyle(
            stroke_width=2.0, fill_enabled=False,
            stroke_color=RGBAColor(106, 106, 106),  # #6A6A6A
            opacity=1.0,
        ),
        # Forests: medium green
        "forests": LayerStyle(
            stroke_width=0.5, fill_enabled=True,
            fill_color=RGBAColor(173, 209, 158, 255),  # #ADD19E
            stroke_color=RGBAColor(140, 180, 120),
            opacity=1.0,
        ),
        # Fields/farmland: pale yellow-brown
        "fields": LayerStyle(
            stroke_width=0.5, fill_enabled=True,
            fill_color=RGBAColor(237, 224, 201, 255),  # #EDE0C9
            stroke_color=RGBAColor(210, 200, 170),
            opacity=1.0,
        ),
        # Natural areas: light olive
        "natural": LayerStyle(
            stroke_width=0.5, fill_enabled=True,
            fill_color=RGBAColor(200, 215, 171, 255),  # #C8D7AB
            stroke_color=RGBAColor(170, 190, 140),
            opacity=1.0,
        ),
        # Coastline
        "coastline": LayerStyle(
            stroke_width=2.0, fill_enabled=True,
            fill_color=RGBAColor(170, 211, 223, 255),  # same as water
            stroke_color=RGBAColor(100, 160, 190),
            opacity=1.0,
        ),
        # Places: labels only
        "places": LayerStyle(
            stroke_width=0.0, fill_enabled=False,
            stroke_color=RGBAColor(0, 0, 0), opacity=1.0,
        ),
        # Derived layers — not used in OSM Standard but keep defaults
        "voronoi_cells": LayerStyle(stroke_width=0.8, fill_enabled=False, stroke_color=RGBAColor(80, 80, 80), opacity=0.6, visible=False),
        "delaunay_mesh": LayerStyle(stroke_width=1.0, fill_enabled=False, stroke_color=RGBAColor(60, 60, 60), opacity=0.7, visible=False),
        "hex_grid": LayerStyle(stroke_width=0.8, fill_enabled=False, stroke_color=RGBAColor(100, 100, 100), opacity=0.5, visible=False),
        "circle_packing": LayerStyle(stroke_width=0.8, fill_enabled=False, stroke_color=RGBAColor(110, 110, 110), opacity=0.55, visible=False),
    }


def _fragmented_styles() -> dict[str, LayerStyle]:
    styles = _base_styles()
    styles["hex_grid"] = LayerStyle(stroke_width=1.2, fill_enabled=False, stroke_color=RGBAColor(40, 40, 40), opacity=0.7)
    styles["voronoi_cells"] = LayerStyle(stroke_width=1.0, fill_enabled=False, stroke_color=RGBAColor(30, 30, 30), opacity=0.8)
    return styles


def _organic_styles() -> dict[str, LayerStyle]:
    styles = _base_styles()
    styles["circle_packing"] = LayerStyle(stroke_width=1.0, fill_enabled=False, stroke_color=RGBAColor(60, 60, 60), opacity=0.75)
    styles["delaunay_mesh"].visible = False
    return styles


def _blueprint_styles() -> dict[str, LayerStyle]:
    styles = _base_styles()
    # Blueprint style roads - all blue tones
    styles["roads_motorway"] = LayerStyle(stroke_width=5.0, fill_enabled=False, stroke_color=RGBAColor(30, 70, 140), opacity=1.0)
    styles["roads_trunk"] = LayerStyle(stroke_width=4.5, fill_enabled=False, stroke_color=RGBAColor(35, 80, 150), opacity=1.0)
    styles["roads_primary"] = LayerStyle(stroke_width=4.0, fill_enabled=False, stroke_color=RGBAColor(40, 90, 160), opacity=1.0)
    styles["roads_secondary"] = LayerStyle(stroke_width=3.0, fill_enabled=False, stroke_color=RGBAColor(50, 100, 170), opacity=1.0)
    styles["roads_tertiary"] = LayerStyle(stroke_width=2.5, fill_enabled=False, stroke_color=RGBAColor(60, 110, 180), opacity=1.0)
    styles["roads_residential"] = LayerStyle(stroke_width=2.0, fill_enabled=False, stroke_color=RGBAColor(70, 120, 190), opacity=1.0)
    styles["roads_service"] = LayerStyle(stroke_width=1.5, fill_enabled=False, stroke_color=RGBAColor(80, 130, 200), opacity=0.9)
    styles["roads_other"] = LayerStyle(stroke_width=1.5, fill_enabled=False, stroke_color=RGBAColor(90, 140, 210), opacity=0.9)
    styles["roads"] = LayerStyle(stroke_width=2.0, fill_enabled=False, stroke_color=RGBAColor(40, 90, 160), opacity=1.0)
    styles["buildings"] = LayerStyle(stroke_width=1.0, fill_enabled=True, fill_color=RGBAColor(200, 220, 240, 255), stroke_color=RGBAColor(50, 110, 180), opacity=1.0)
    styles["hex_grid"] = LayerStyle(stroke_width=1.0, fill_enabled=False, stroke_color=RGBAColor(100, 150, 210), opacity=0.6)
    styles["voronoi_cells"] = LayerStyle(stroke_width=0.8, fill_enabled=False, stroke_color=RGBAColor(80, 140, 220), opacity=0.5)
    return styles
