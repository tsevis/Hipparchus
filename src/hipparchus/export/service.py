"""Export service contracts and implementations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol

from hipparchus.application.line_weight import scale_line_weights
from hipparchus.application.sheet_scale import scaled_for_sheet
from hipparchus.export.profiles import ExportDiagnostics, SVGExportProfile
from hipparchus.export.svg_clean import CleanSVGExporter
from hipparchus.rendering.models import RenderScene


class Exporter(Protocol):
    """Contract for exporting map documents."""

    def export(self, destination: Path) -> None:
        """Export current document to destination."""


@dataclass(slots=True)
class SVGExporter:
    """SVG exporter backed by clean layered path generation."""

    scene: RenderScene
    width: int = 4096
    height: int = 4096
    #: Absolute stroke scale for the medium this is drawn on -- see
    #: `application/line_weight.py`. 1.0 leaves every width exactly as the
    #: preset states it.
    line_weight: float = 1.0

    def export(self, destination: Path) -> None:
        self.export_with_profile(destination=destination, profile=SVGExportProfile(mode="clean"))

    def export_with_profile(self, destination: Path, profile: SVGExportProfile) -> ExportDiagnostics:
        precision = profile.precision
        if precision is None:
            precision = 6 if profile.mode == "print" else 4
        scene = scaled_for_sheet(scale_line_weights(self.scene, self.line_weight), self.width, self.height)
        diagnostics = CleanSVGExporter(precision=precision).export_scene(
            scene,
            destination,
            width=self.width,
            height=self.height,
            profile=profile,
        )

        if profile.include_diagnostics:
            diag_path = destination.with_suffix(destination.suffix + profile.diagnostics_file_suffix)
            diag_path.write_text(json.dumps(diagnostics.as_dict(), indent=2), encoding="utf-8")

        return diagnostics


@dataclass(slots=True)
class PDFExporter:
    """The scene as a PDF, drawn rather than photographed.

    Through the same renderer the window and the SVG use, onto a document
    canvas — so the paths in the file are the paths on screen, at whatever size
    the reader opens it. A PDF made by embedding a bitmap would be a picture of
    a map rather than the map.

    `width` and `height` are the **drawing**, in the pixels the PNG would use,
    because that is what sets how heavy a stroke reads against the sheet.
    `page_size` is the **paper**, in points at 72 to the inch. `PageSpec` in
    `application/page_size.py` produces both from one description in inches, and
    the window has no business computing either itself.

    Left as one number, this was the bug that made every A4 export a 34.4 x 48.7
    inch page: pixels at 300 dpi went in and Skia read them as points.
    """

    scene: RenderScene | None
    width: int = 2480
    height: int = 3508
    #: The paper, in points. `None` reads the drawing as points, which is what
    #: "no paper chosen" means.
    page_size: tuple[float, float] | None = None
    #: Absolute stroke scale for the medium this is drawn on -- see
    #: `application/line_weight.py`. 1.0 leaves every width exactly as the
    #: preset states it.
    line_weight: float = 1.0

    def export(self, destination: Path) -> None:
        scene = (
            scaled_for_sheet(scale_line_weights(self.scene, self.line_weight), self.width, self.height)
            if self.scene is not None
            else None
        )
        renderer = _renderer_for(scene)
        renderer.render_pdf(
            destination, self.width, self.height, page_size=self.page_size
        )


@dataclass(slots=True)
class PNGExporter:
    """The scene as a bitmap, at the size that was asked for.

    Unlike the preview, which draws at the display's device scale because it is
    going on a screen, an export goes into a file at a stated size: a poster at
    300 dpi is a different request from a window on a laptop.
    """

    scene: RenderScene | None
    width: int = 2048
    height: int = 2048
    scale: float = 1.0
    #: Absolute stroke scale for the medium this is drawn on -- see
    #: `application/line_weight.py`. 1.0 leaves every width exactly as the
    #: preset states it.
    line_weight: float = 1.0

    def export(self, destination: Path) -> None:
        scene = (
            scaled_for_sheet(scale_line_weights(self.scene, self.line_weight), self.width, self.height)
            if self.scene is not None
            else None
        )
        renderer = _renderer_for(scene)
        data = renderer.render_png(self.width, self.height, scale=self.scale)
        if not data:
            raise ValueError("the renderer produced no image")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)


def _renderer_for(scene: RenderScene | None):
    """A renderer holding this scene, or a refusal.

    Refused rather than written empty: a file with the right extension and
    nothing in it is worse than an error, because it looks like it worked.
    """
    if scene is None:
        raise ValueError("there is no map to export yet")
    from hipparchus.rendering.skia_renderer import SkiaRenderer

    renderer = SkiaRenderer()
    renderer.set_scene(scene)
    return renderer

