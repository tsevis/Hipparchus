"""Export service contracts and implementations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Protocol

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

    def export(self, destination: Path) -> None:
        self.export_with_profile(destination=destination, profile=SVGExportProfile(mode="clean"))

    def export_with_profile(self, destination: Path, profile: SVGExportProfile) -> ExportDiagnostics:
        diagnostics = CleanSVGExporter().export_scene(self.scene, destination, width=self.width, height=self.height)

        if profile.include_diagnostics:
            diag_path = destination.with_suffix(destination.suffix + profile.diagnostics_file_suffix)
            diag_path.write_text(json.dumps(diagnostics.as_dict(), indent=2), encoding="utf-8")

        return diagnostics


@dataclass(slots=True)
class PDFExporter:
    """Placeholder PDF exporter."""

    def export(self, destination: Path) -> None:
        _ = destination


@dataclass(slots=True)
class PNGExporter:
    """Placeholder PNG exporter."""

    def export(self, destination: Path) -> None:
        _ = destination


@dataclass(slots=True)
class GeoJSONExporter:
    """Placeholder GeoJSON exporter."""

    def export(self, destination: Path) -> None:
        _ = destination
