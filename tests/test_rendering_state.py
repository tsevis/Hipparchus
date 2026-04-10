from __future__ import annotations

import unittest

from shapely.geometry import LineString

from hipparchus.rendering.engine import NoOpRenderer
from hipparchus.rendering.models import LayerStyle, RenderLayer, RenderScene, ViewportState


class RenderingStateTests(unittest.TestCase):
    def test_viewport_zoom_and_pan(self) -> None:
        vp = ViewportState().with_zoom(2.0).with_pan(10.0, -5.0)
        self.assertEqual(vp.zoom, 2.0)
        self.assertEqual(vp.pan_x, 10.0)
        self.assertEqual(vp.pan_y, -5.0)

    def test_layer_visibility_toggle(self) -> None:
        roads = RenderLayer(name="roads", geometries=[LineString([(0, 0), (1, 1)])], style=LayerStyle(visible=True))
        scene = RenderScene(layers=[roads])
        renderer = NoOpRenderer(scene=scene)

        renderer.set_layer_visibility("roads", False)

        self.assertFalse(scene.layers[0].style.visible)


if __name__ == "__main__":
    unittest.main()
