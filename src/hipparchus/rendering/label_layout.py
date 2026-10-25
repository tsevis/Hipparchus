"""Labels measured in their real type, ready for either renderer to draw.

The canvas (window, PNG, PDF) and the SVG writer both lay labels out here, so
one sheet exported twice carries the same names in the same type: one size (the
configured one, scaled with the sheet), one face, and the halo the preset
states. What gets drawn is decided by `application/label_placement.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from hipparchus.rendering.models import PlaceLabel, RenderLayer, RenderScene
from hipparchus.rendering.skia_renderer import (
    _default_typeface,
    _family_typeface,
    _import_skia,
    _typeface_for_text,
)

MIN_LABEL_SIZE = 6
MAX_LABEL_SIZE = 16


@dataclass(frozen=True, slots=True)
class PlacedLabel:
    """A label that gets drawn, in canvas units."""

    layer_name: str
    text: str
    x: float
    y: float
    width: float
    size: float
    halo: float
    rotation: float


class LabelType:
    """The type labels are set in: a size and a family, measured with Skia."""

    def __init__(self, size: float, family: str = "") -> None:
        self.size = float(max(MIN_LABEL_SIZE, min(size, MAX_LABEL_SIZE)))
        self.family = family.strip()
        self._base = _family_typeface(self.family) or _default_typeface()
        self._fonts: dict[tuple[str | None, float], Any] = {}

    @property
    def face_name(self) -> str:
        """The family actually used, which is what the SVG has to name."""
        name = self._base.getFamilyName() if self._base is not None else ""
        return name or self.family

    def font(self, text: str, size: float) -> Any:
        skia = _import_skia()
        typeface = _typeface_for_text(text, base=self._base) or self._base
        family = typeface.getFamilyName() if typeface is not None else None
        key = (family, size)
        cached = self._fonts.get(key)
        if cached is None:
            cached = skia.Font(typeface, size) if typeface is not None else skia.Font()
            self._fonts[key] = cached
        return cached

    def width(self, text: str, size: float) -> float:
        return float(self.font(text, size).measureText(text))


def lay_out_labels(
    layers: Iterable[RenderLayer],
    scene: RenderScene,
    label_type: LabelType,
    to_canvas: Callable[[float, float], tuple[float, float] | None],
    width: float,
    height: float,
    *,
    extra_rotation: float = 0.0,
    keep_all: Iterable[RenderLayer] = (),
) -> list[PlacedLabel]:
    """Every label of ``layers`` that fits, measured and placed.

    ``keep_all`` layers are laid out too but never thinned: the SVG keeps every
    label of a hidden layer so switching it on brings its names back.
    """
    from hipparchus.application.label_placement import LabelSpec, place_labels

    size = label_type.size * max(scene.label_scale, 1e-6)
    drawn: list[PlacedLabel] = []
    specs: list[Any] = []
    for layer in layers:
        for label in layer.labels:
            if not isinstance(label, PlaceLabel) or not label.name:
                continue
            at = to_canvas(float(label.x), float(label.y))
            if at is None:
                continue
            text = str(label.name)
            specs.append(
                (
                    LabelSpec(
                        key=len(specs), layer_name=layer.name, place_type=label.place_type,
                        x=at[0], y=at[1], width=label_type.width(text, size), size=size,
                        halo=max(0.0, layer.style.label_halo_width),
                        rotation=label.rotation + extra_rotation,
                    ),
                    text,
                )
            )
    keep = set(place_labels([spec for spec, _ in specs], width, height))
    for spec, text in specs:
        if spec.key in keep:
            drawn.append(
                PlacedLabel(spec.layer_name, text, spec.x, spec.y, spec.width, spec.size, spec.halo, spec.rotation)
            )
    if keep_all:
        for layer in keep_all:
            for label in layer.labels:
                if not isinstance(label, PlaceLabel) or not label.name:
                    continue
                at = to_canvas(float(label.x), float(label.y))
                if at is None:
                    continue
                text = str(label.name)
                drawn.append(
                    PlacedLabel(
                        layer.name, text, at[0], at[1], label_type.width(text, size), size,
                        max(0.0, layer.style.label_halo_width), label.rotation + extra_rotation,
                    )
                )
    return drawn
