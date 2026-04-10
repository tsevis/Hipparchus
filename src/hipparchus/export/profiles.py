"""SVG export profile definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SVGExportMode = Literal["clean"]


@dataclass(slots=True, frozen=True)
class SVGExportProfile:
    """Profile controlling SVG export behavior and diagnostics."""

    mode: SVGExportMode = "clean"
    include_diagnostics: bool = True
    diagnostics_file_suffix: str = ".diagnostics.json"


@dataclass(slots=True)
class ExportDiagnostics:
    """Portable diagnostics contract for export quality checks."""

    mode: SVGExportMode
    total_paths: int = 0
    merged_polygons: int = 0
    invalid_geometries_fixed: int = 0
    removed_nodes: int = 0
    layer_path_counts: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "total_paths": self.total_paths,
            "merged_polygons": self.merged_polygons,
            "invalid_geometries_fixed": self.invalid_geometries_fixed,
            "removed_nodes": self.removed_nodes,
            "layer_path_counts": dict(self.layer_path_counts),
        }
