"""Line weights and label type that keep their look on a bigger sheet.

A preset's widths are canvas pixels, and nothing scaled them to the sheet: a
print at 24 x 36 and 300 dpi drew the same three-pixel road across 7,200 pixels
instead of 1,024, and every line on it came out a hairline. A file bigger than
the reference canvas now draws the same picture enlarged.

Applied per file, at the size that file is written in, and never to the window,
which draws at whatever size it is dragged to. The manual Line Weight control
still multiplies the strokes alone and leaves labels where they are.
"""

from __future__ import annotations

import math
from dataclasses import replace

from hipparchus.rendering.models import RenderScene

#: The canvas a preset's widths are stated for: the smallest canvas the app
#: exports at (`PagePanelMixin._canvas_size` floors the window at this).
REFERENCE_WIDTH = 1024
REFERENCE_HEIGHT = 1024


def sheet_scale(width: float, height: float) -> float:
    """How much heavier lines and larger type draw on a sheet of this size.

    The square root of the area ratio, so a sheet of another shape is weighed by
    its size rather than by whichever edge happens to be longer.
    """
    if not (width > 0 and height > 0 and math.isfinite(width) and math.isfinite(height)):
        return 1.0
    ratio = math.sqrt((width * height) / (REFERENCE_WIDTH * REFERENCE_HEIGHT))
    # Never below one: a sheet at or under the reference draws at exactly the
    # widths the preset states.
    return max(1.0, ratio)


def scaled_for_sheet(scene: RenderScene, width: float, height: float) -> RenderScene:
    """``scene`` with line weights, label halos and label type scaled for a sheet."""
    factor = sheet_scale(width, height)
    if factor == 1.0:
        return scene
    layers = [
        replace(
            layer,
            style=replace(
                layer.style,
                stroke_width=layer.style.stroke_width * factor,
                casing_width=layer.style.casing_width * factor,
                label_halo_width=layer.style.label_halo_width * factor,
            ),
        )
        for layer in scene.layers
    ]
    return replace(scene, layers=layers, label_scale=scene.label_scale * factor)
