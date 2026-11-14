"""Two failures that used to vanish without a trace.

Both sites recover on purpose -- a PMTiles archive with an unreadable header is
still read at a default zoom, and a failed fetch still reports its own error
when the previous map cannot be put back. What neither did was say so, which
left a wrong-looking map with nothing in the log to explain it.
"""

from __future__ import annotations

import threading
import unittest

from hipparchus.application.controller import ApplicationController
from hipparchus.data_sources import optional_providers
from hipparchus.data_sources.provider import BBoxQuery

_WAIT_SECONDS = 5.0
_AOI = BBoxQuery(min_lon=0.0, min_lat=0.0, max_lon=1.0, max_lat=1.0, layers=("roads",))


class _BrokenHeaderReader:
    def header(self) -> dict:
        raise ValueError("truncated header")


class _HeaderReader:
    def __init__(self, header: dict) -> None:
        self._header = header

    def header(self) -> dict:
        return self._header


class PmtilesHeaderTests(unittest.TestCase):
    def test_an_unreadable_header_is_logged_and_the_default_zoom_stands(self) -> None:
        with self.assertLogs(optional_providers.__name__, level="WARNING") as logs:
            zoom = optional_providers._pmtiles_max_zoom(_BrokenHeaderReader(), default=14)
        self.assertEqual(zoom, 14)
        self.assertIn("truncated header", "\n".join(logs.output))

    def test_the_header_zoom_is_used_when_it_can_be_read(self) -> None:
        zoom = optional_providers._pmtiles_max_zoom(_HeaderReader({"max_zoom": 9}), default=14)
        self.assertEqual(zoom, 9)


class _Collection:
    metadata: dict = {}
    features_by_layer: dict = {}


class _Manager:
    def __init__(self) -> None:
        self.fail = False

    def fetch(self, *args, **kwargs):
        if self.fail:
            raise RuntimeError("network down")
        return _Collection()


class _Scene:
    layers: tuple = ()


class _Builder:
    def build(self, **kwargs):
        return _Scene()


class _RendererThatCannotRestore:
    def set_scene(self, scene) -> None:
        raise RuntimeError("surface lost")


class FallbackFailureTests(unittest.TestCase):
    def _run(self, controller: ApplicationController, on_scene, on_error) -> None:
        controller.run_fetch_and_render(
            aoi=_AOI,
            layers=_AOI.layers,
            style_profile=None,
            quality_mode=None,
            geometry_profile=None,
            on_scene=on_scene,
            on_error=on_error,
        )

    def test_a_fallback_that_fails_is_logged_and_the_first_error_still_reported(self) -> None:
        manager = _Manager()
        controller = ApplicationController(
            data_source_manager=manager,
            renderer=_RendererThatCannotRestore(),
            scene_builder=_Builder(),
        )
        first_done = threading.Event()
        self._run(controller, lambda scene, cache: first_done.set(), lambda exc: first_done.set())
        self.assertTrue(first_done.wait(_WAIT_SECONDS))

        manager.fail = True
        errors: list[Exception] = []
        second_done = threading.Event()

        def on_error(exc: Exception) -> None:
            errors.append(exc)
            second_done.set()

        with self.assertLogs("hipparchus.perf", level="ERROR") as logs:
            self._run(controller, lambda scene, cache: None, on_error)
            self.assertTrue(second_done.wait(_WAIT_SECONDS))

        self.assertEqual([str(exc) for exc in errors], ["network down"])
        self.assertIn("surface lost", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
