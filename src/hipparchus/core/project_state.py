"""Project document serialization for .hipparchus.json files."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path


@dataclass(slots=True)
class AOIState:
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float


@dataclass(slots=True)
class ProjectState:
    """Persisted state for reproducible artistic map sessions."""

    project_name: str
    aoi: AOIState
    active_layers: list[str]
    preset_name: str
    quality_mode: str
    layer_overrides: dict[str, dict[str, float | bool | str]] = field(default_factory=dict)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @staticmethod
    def load(path: Path) -> "ProjectState":
        data = json.loads(path.read_text(encoding="utf-8"))
        preset_name = str(data.get("preset_name", "Urban Structure"))
        if preset_name == "Mask Structural":
            preset_name = "Urban Structure"

        return ProjectState(
            project_name=str(data["project_name"]),
            aoi=AOIState(**data["aoi"]),
            active_layers=[str(x) for x in data.get("active_layers", [])],
            preset_name=preset_name,
            quality_mode=str(data.get("quality_mode", "preview")),
            layer_overrides=dict(data.get("layer_overrides", {})),
        )
