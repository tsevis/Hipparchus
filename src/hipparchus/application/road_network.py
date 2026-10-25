"""The road classes, drawn as one network.

Each class is a layer of its own, and a layer lays its casing across all of its
features before it draws a line, which is why two residential streets meet as
one junction. Across classes that was never true: each layer drew
casing-then-line in turn, so whichever class came later cut the earlier one at
every crossing. Drawn major to minor, every residential street painted itself
across the secondary road it met, and a city's orange roads came out beaded.

So for a run of road layers next to each other in the draw order, every casing
in the run goes down first and then every line, in the run's own order -- minor
to major, so the major road is the last ink at its junctions and a minor
street's line still reaches the major road's edge.

Both renderers walk the same turns; neither decides the order itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from hipparchus.rendering.models import RenderLayer

ROAD_LAYER_NAMES = frozenset({
    "roads", "roads_other", "roads_service", "roads_residential", "roads_tertiary",
    "roads_secondary", "roads_primary", "roads_trunk", "roads_motorway",
})

Part = Literal["whole", "casing", "body"]


@dataclass(frozen=True, slots=True)
class Turn:
    """One layer's turn at the canvas, and which of its parts is drawn in it.

    ``whole``: casing and body together (a layer outside the network).
    ``casing``: only the casing, lifted ahead of the run's lines.
    ``body``: everything but the casing.
    Every layer of a run keeps a ``body`` turn even if it has no casing, because
    that turn is where the SVG writes its group and its labels.
    """

    layer: RenderLayer
    part: Part


def has_casing(layer: RenderLayer) -> bool:
    return layer.style.casing_width > 0 and bool(layer.geometries)


def draw_turns(layers: Iterable[RenderLayer]) -> list[Turn]:
    """The order ``layers`` are drawn in, as turns."""
    turns: list[Turn] = []
    run: list[RenderLayer] = []

    def flush() -> None:
        turns.extend(Turn(layer, "casing") for layer in run if has_casing(layer))
        turns.extend(Turn(layer, "body") for layer in run)
        run.clear()

    for layer in layers:
        if layer.name in ROAD_LAYER_NAMES:
            run.append(layer)
        else:
            flush()
            turns.append(Turn(layer, "whole"))
    flush()
    return turns
