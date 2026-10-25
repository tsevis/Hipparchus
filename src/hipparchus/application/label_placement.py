"""Which labels a sheet gets, decided once for every renderer.

Thinning used to run a layer at a time, and the canvas then suppressed overlaps
in layer order from a centre-distance guess: a street name was only ever tested
against street names, rotation was ignored, and a label the canvas edge cut was
drawn anyway. The SVG wrote every label it had.

Here every label of every layer is measured in the type it is set in, boxed with
its halo and turned with its street, and taken most important first. One that
would touch a label already placed, or does not fit on the canvas, is dropped.
The PNG/PDF canvas and the SVG both call `place_labels`, so the two files of one
sheet carry the same names.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

# The type size and baseline shift are stated once, in the renderer (which this
# package must not be imported by); they are re-exported here for callers.
#: The text is centred on its anchor, its baseline `BASELINE_SHIFT_EM` below
#: it, and the box is `BOX_HEIGHT_EM` tall about it -- the same numbers in both
#: files, because the SVG's `dominant-baseline` is not honoured everywhere.
BOX_HEIGHT_EM = 1.2

#: Settlement rank: a city is placed before a town before a village.
PLACE_RANK = {
    "city": 0, "town": 1, "village": 2, "suburb": 3,
    "quarter": 4, "hamlet": 5, "neighbourhood": 6,
}
_LAYER_RANK = {"places": 0, "summits": 1, "street_names": 2, "amenities": 3, "shops": 4}
_OTHER_RANK = 5


@dataclass(frozen=True, slots=True)
class LabelSpec:
    """One label, measured and positioned in canvas pixels."""

    key: object
    layer_name: str
    place_type: str
    x: float
    y: float
    #: Text width and type size, canvas pixels.
    width: float
    size: float
    halo: float = 0.0
    #: Degrees clockwise on the canvas.
    rotation: float = 0.0


def label_rank(layer_name: str, place_type: str = "") -> tuple[int, int]:
    """Smaller is more important: places by settlement size, then summits,
    street names, amenities, shops, then the rest."""
    if layer_name == "places" or place_type in PLACE_RANK:
        return (0, PLACE_RANK.get(place_type, len(PLACE_RANK)))
    return (_LAYER_RANK.get(layer_name, _OTHER_RANK), 0)


def label_corners(spec: LabelSpec) -> list[tuple[float, float]]:
    """The label's box -- text plus halo -- as four corners on the canvas."""
    half_w = spec.width / 2.0 + spec.halo / 2.0
    half_h = spec.size * BOX_HEIGHT_EM / 2.0 + spec.halo / 2.0
    angle = math.radians(spec.rotation)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return [
        (spec.x + dx * cos_a - dy * sin_a, spec.y + dx * sin_a + dy * cos_a)
        for dx, dy in ((-half_w, -half_h), (half_w, -half_h), (half_w, half_h), (-half_w, half_h))
    ]


def _projection(corners: Sequence[tuple[float, float]], axis: tuple[float, float]) -> tuple[float, float]:
    values = [x * axis[0] + y * axis[1] for x, y in corners]
    return min(values), max(values)


def boxes_touch(first: Sequence[tuple[float, float]], second: Sequence[tuple[float, float]]) -> bool:
    """Exact overlap of two turned rectangles, by separating axes.

    Touching counts: two labels that share an edge read as one smear.
    """
    for corners in (first, second):
        for index in range(2):
            ex = corners[index + 1][0] - corners[index][0]
            ey = corners[index + 1][1] - corners[index][1]
            length = math.hypot(ex, ey)
            if length == 0.0:
                continue
            axis = (-ey / length, ex / length)
            low_a, high_a = _projection(first, axis)
            low_b, high_b = _projection(second, axis)
            if high_a < low_b or high_b < low_a:
                return False
    return True


def place_labels(specs: Sequence[LabelSpec], width: float, height: float) -> list[object]:
    """The keys of the labels that get drawn, most important first."""
    ranked = sorted(
        range(len(specs)),
        key=lambda index: (label_rank(specs[index].layer_name, specs[index].place_type), index),
    )
    placed: list[tuple[tuple[float, float, float, float], list[tuple[float, float]]]] = []
    kept: list[object] = []
    for index in ranked:
        spec = specs[index]
        corners = label_corners(spec)
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        bounds = (min(xs), min(ys), max(xs), max(ys))
        if bounds[0] < 0.0 or bounds[1] < 0.0 or bounds[2] > width or bounds[3] > height:
            continue
        if any(
            not (bounds[2] < other[0] or other[2] < bounds[0] or bounds[3] < other[1] or other[3] < bounds[1])
            and boxes_touch(corners, other_corners)
            for other, other_corners in placed
        ):
            continue
        placed.append((bounds, corners))
        kept.append(spec.key)
    return kept
