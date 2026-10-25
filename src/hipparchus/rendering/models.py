"""Core rendering models for layered vector scenes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from shapely.geometry.base import BaseGeometry


@dataclass(slots=True, frozen=True)
class RGBAColor:
    """RGBA color with 8-bit channels."""

    r: int
    g: int
    b: int
    a: int = 255

    def with_opacity(self, opacity: float) -> "RGBAColor":
        """Return color with opacity multiplier applied to alpha channel."""
        bounded = max(0.0, min(1.0, opacity))
        return RGBAColor(self.r, self.g, self.b, int(self.a * bounded))

    def to_hex(self) -> str:
        """Return ``#rrggbb``. Alpha is dropped; Tk colour strings have none."""
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"


@dataclass(slots=True)
class LayerStyle:
    """Visual style controls for a render layer."""

    stroke_width: float = 1.0
    stroke_color: RGBAColor = field(default_factory=lambda: RGBAColor(20, 20, 20, 255))
    fill_color: RGBAColor = field(default_factory=lambda: RGBAColor(220, 220, 220, 200))
    fill_enabled: bool = True
    opacity: float = 1.0
    visible: bool = True
    # Road casing support: draw a wider stroke underneath for OSM-style road rendering
    casing_width: float = 0.0  # 0 = no casing
    casing_color: RGBAColor = field(default_factory=lambda: RGBAColor(0, 0, 0, 255))
    # Line cap/join style: "round" or "butt"
    line_cap: str = "butt"
    label_halo_color: RGBAColor = field(default_factory=lambda: RGBAColor(255, 255, 255, 230))
    label_halo_width: float = 2.0
    # Illuminated contours: 0 leaves the layer at one uniform weight, above 0
    # varies stroke weight along each line by how its slope faces the light.
    illumination: float = 0.0
    illumination_azimuth: float = 315.0
    illumination_bands: int = 5
    illumination_lit_scale: float = 0.4
    illumination_shadow_scale: float = 1.9
    # High end of a two-stop fill ramp. Layers whose features carry a position
    # in a sequence -- elevation bands -- interpolate from ``fill_color`` to
    # this; everything else ignores it.
    fill_color_high: RGBAColor | None = None


@dataclass(slots=True)
class PlaceLabel:
    """A place name label with position."""

    name: str
    x: float
    y: float
    place_type: str = ""  # city, town, village, etc.
    #: Degrees clockwise on the canvas, for a name set along its street.
    rotation: float = 0.0


@dataclass(slots=True)
class RenderLayer:
    """A named layer with style and shapely geometries."""

    name: str
    geometries: list[BaseGeometry] = field(default_factory=list)
    style: LayerStyle = field(default_factory=LayerStyle)
    labels: list[PlaceLabel] = field(default_factory=list)  # For place names
    # Per-geometry stroke-width multipliers, parallel to ``geometries``. Empty
    # means one uniform weight for the whole layer.
    weights: list[float] = field(default_factory=list)
    # Per-geometry fill colours, parallel to ``geometries``. Empty means the
    # layer's single fill applies to all of them.
    fill_colors: list[RGBAColor] = field(default_factory=list)

    def weight_at(self, index: int) -> float:
        return self.weights[index] if index < len(self.weights) else 1.0

    def fill_color_at(self, index: int) -> RGBAColor:
        if index < len(self.fill_colors):
            return self.fill_colors[index]
        return self.style.fill_color


@dataclass(slots=True, frozen=True)
class ViewportState:
    """Viewport transform parameters in world coordinate space."""

    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0
    rotation: float = 0.0  # Rotation in degrees

    def with_zoom(self, factor: float) -> "ViewportState":
        """Return viewport with zoom multiplied by factor."""
        next_zoom = max(0.05, min(64.0, self.zoom * factor))
        return ViewportState(zoom=next_zoom, pan_x=self.pan_x, pan_y=self.pan_y, rotation=self.rotation)

    def with_pan(self, dx: float, dy: float) -> "ViewportState":
        """Return viewport shifted by world-space pan offset."""
        return ViewportState(zoom=self.zoom, pan_x=self.pan_x + dx, pan_y=self.pan_y + dy, rotation=self.rotation)

    def with_rotation(self, degrees: float) -> "ViewportState":
        """Return viewport with rotation set to degrees."""
        return ViewportState(zoom=self.zoom, pan_x=self.pan_x, pan_y=self.pan_y, rotation=degrees)


@dataclass(slots=True)
class RenderScene:
    """Ordered layer stack for rendering and export."""

    layers: list[RenderLayer] = field(default_factory=list)
    # Optional bbox for the scene (min_lon, min_lat, max_lon, max_lat)
    bbox: tuple[float, float, float, float] | None = None
    source_bbox: tuple[float, float, float, float] | None = None
    # Ground the layers are drawn on. Carried on the scene so the preview
    # renderer and the SVG exporter agree without consulting the preset.
    background: RGBAColor = field(default_factory=lambda: RGBAColor(250, 250, 250, 255))
    # Oversampling factor for preview rendering, carried from the quality
    # profile. Lives on the scene so the renderer never has to import the
    # application layer, which imports it.
    supersample: float = 1.0
    # The projection the geometry was built with. Carried so a click on the
    # canvas can be turned back into longitude and latitude without guessing
    # which projection produced the picture.
    projection: object | None = None
    #: How much larger label type and halos draw than the preset states. 1 for
    #: the window; a bigger sheet sets it with its line weights so the type
    #: keeps its proportion to the roads it names.
    label_scale: float = 1.0
    metadata: dict[str, object] = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)

    def iter_visible_layers(self) -> Iterable[RenderLayer]:
        for layer in self.layers:
            if layer.style.visible:
                yield layer
