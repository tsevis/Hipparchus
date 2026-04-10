"""Persistent custom preset storage."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from hipparchus.application.presets import ArtisticPreset, GeometryPipelineProfile, StyleProfile
from hipparchus.rendering.models import LayerStyle, RGBAColor


class PresetStore:
    """Read and write user-created presets as JSON."""

    schema_version = 1

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, ArtisticPreset]:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        presets: dict[str, ArtisticPreset] = {}
        for item in data.get("presets", []):
            preset = _preset_from_dict(item)
            if preset is not None:
                presets[preset.name] = preset
        return presets

    def save(self, presets: dict[str, ArtisticPreset]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": self.schema_version,
            "presets": [_preset_to_dict(preset) for preset in sorted(presets.values(), key=lambda item: item.name)],
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _preset_to_dict(preset: ArtisticPreset) -> dict[str, Any]:
    return {
        "name": preset.name,
        "geometry_profile": asdict(preset.geometry_profile),
        "style_profile": {
            "layer_styles": {
                layer_name: _layer_style_to_dict(style)
                for layer_name, style in sorted(preset.style_profile.layer_styles.items())
            }
        },
    }


def _preset_from_dict(data: dict[str, Any]) -> ArtisticPreset | None:
    name = str(data.get("name", "")).strip()
    if not name:
        return None

    geometry_profile = GeometryPipelineProfile(**dict(data.get("geometry_profile", {})))
    raw_styles = dict(data.get("style_profile", {}).get("layer_styles", {}))
    layer_styles = {
        str(layer_name): _layer_style_from_dict(dict(style_data))
        for layer_name, style_data in raw_styles.items()
        if isinstance(style_data, dict)
    }
    return ArtisticPreset(
        name=name,
        geometry_profile=geometry_profile,
        style_profile=StyleProfile(layer_styles=layer_styles),
    )


def _layer_style_to_dict(style: LayerStyle) -> dict[str, Any]:
    data = asdict(style)
    data["stroke_color"] = asdict(style.stroke_color)
    data["fill_color"] = asdict(style.fill_color)
    data["casing_color"] = asdict(style.casing_color)
    return data


def _layer_style_from_dict(data: dict[str, Any]) -> LayerStyle:
    return LayerStyle(
        stroke_width=float(data.get("stroke_width", 1.0)),
        stroke_color=_color_from_dict(data.get("stroke_color"), RGBAColor(20, 20, 20, 255)),
        fill_color=_color_from_dict(data.get("fill_color"), RGBAColor(220, 220, 220, 200)),
        fill_enabled=bool(data.get("fill_enabled", True)),
        opacity=float(data.get("opacity", 1.0)),
        visible=bool(data.get("visible", True)),
        casing_width=float(data.get("casing_width", 0.0)),
        casing_color=_color_from_dict(data.get("casing_color"), RGBAColor(0, 0, 0, 255)),
        line_cap=str(data.get("line_cap", "butt")),
    )


def _color_from_dict(value: object, fallback: RGBAColor) -> RGBAColor:
    if not isinstance(value, dict):
        return fallback
    return RGBAColor(
        r=int(value.get("r", fallback.r)),
        g=int(value.get("g", fallback.g)),
        b=int(value.get("b", fallback.b)),
        a=int(value.get("a", fallback.a)),
    )
