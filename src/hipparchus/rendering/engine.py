"""Rendering engine interfaces and baseline implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from hipparchus.rendering.models import RenderScene, ViewportState


class Renderer(Protocol):
    """Contract for map render backends."""

    def set_scene(self, scene: RenderScene) -> None:
        """Attach an ordered scene to renderer."""

    def set_viewport(self, viewport: ViewportState) -> None:
        """Set zoom/pan viewport transform."""

    def pan(self, dx: float, dy: float) -> None:
        """Pan viewport by offsets."""

    def zoom(self, factor: float) -> None:
        """Apply multiplicative zoom factor."""

    def rotate(self, degrees: float) -> None:
        """Rotate viewport by degrees."""

    def set_rotation(self, degrees: float) -> None:
        """Set viewport rotation to absolute degrees."""

    def set_label_font_size(self, size: int) -> None:
        """Set the font size for place labels."""

    def set_layer_visibility(self, layer_name: str, visible: bool) -> None:
        """Toggle layer visibility."""

    def render_preview_png(self, width: int, height: int) -> bytes:
        """Render preview image and return PNG bytes."""


@dataclass(slots=True)
class NoOpRenderer:
    """No-op renderer fallback used in unsupported environments."""

    scene: RenderScene = field(default_factory=RenderScene)
    viewport: ViewportState = field(default_factory=ViewportState)

    def set_scene(self, scene: RenderScene) -> None:
        self.scene = scene

    def set_viewport(self, viewport: ViewportState) -> None:
        self.viewport = viewport

    def pan(self, dx: float, dy: float) -> None:
        self.viewport = self.viewport.with_pan(dx, dy)

    def zoom(self, factor: float) -> None:
        self.viewport = self.viewport.with_zoom(factor)

    def rotate(self, degrees: float) -> None:
        self.viewport = self.viewport.with_rotation(self.viewport.rotation + degrees)

    def set_rotation(self, degrees: float) -> None:
        self.viewport = self.viewport.with_rotation(degrees)

    def set_label_font_size(self, size: int) -> None:
        pass

    def set_layer_visibility(self, layer_name: str, visible: bool) -> None:
        for layer in self.scene.layers:
            if layer.name == layer_name:
                layer.style.visible = visible
                break

    def render_preview_png(self, width: int, height: int) -> bytes:
        _ = width, height
        return b""
