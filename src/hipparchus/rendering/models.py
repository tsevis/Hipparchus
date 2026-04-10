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


@dataclass(slots=True)
class PlaceLabel:
    """A place name label with position."""

    name: str
    x: float
    y: float
    place_type: str = ""  # city, town, village, etc.


@dataclass(slots=True)
class RenderLayer:
    """A named layer with style and shapely geometries."""

    name: str
    geometries: list[BaseGeometry] = field(default_factory=list)
    style: LayerStyle = field(default_factory=LayerStyle)
    labels: list[PlaceLabel] = field(default_factory=list)  # For place names


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

    def iter_visible_layers(self) -> Iterable[RenderLayer]:
        for layer in self.layers:
            if layer.style.visible:
                yield layer
