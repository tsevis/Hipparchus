"""Application controller orchestrating fetch -> build -> render workflow."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import logging
import threading
import time
from typing import Callable

from hipparchus.application.presets import GeometryPipelineProfile, QualityMode, StyleProfile
from hipparchus.application.scene_builder import RenderSceneBuilder
from hipparchus.data_sources.data_source_manager import DataSourceConfig, DataSourceManager
from hipparchus.data_sources.provider import BBoxQuery, FeatureCollection
from hipparchus.rendering.engine import Renderer
from hipparchus.rendering.models import RenderScene


SceneCallback = Callable[[RenderScene, str], None]
ErrorCallback = Callable[[Exception], None]
_LOGGER = logging.getLogger("hipparchus.perf")


@dataclass(slots=True)
class ApplicationController:
    """Coordinates async map fetching, geometry derivation, and rendering."""

    data_source_manager: DataSourceManager
    renderer: Renderer
    scene_builder: RenderSceneBuilder = field(default_factory=RenderSceneBuilder)

    _last_scene: RenderScene | None = field(default=None, init=False, repr=False)
    _request_version: int = field(default=0, init=False, repr=False)

    def run_fetch_and_render(
        self,
        aoi: BBoxQuery,
        layers: tuple[str, ...],
        style_profile: StyleProfile,
        quality_mode: QualityMode,
        geometry_profile: GeometryPipelineProfile,
        on_scene: SceneCallback,
        on_error: ErrorCallback,
    ) -> None:
        """Run data pipeline asynchronously and callback with ready scene."""
        self._request_version += 1
        version = self._request_version

        def _worker() -> None:
            try:
                t0 = time.perf_counter()
                query = BBoxQuery(
                    min_lon=aoi.min_lon,
                    min_lat=aoi.min_lat,
                    max_lon=aoi.max_lon,
                    max_lat=aoi.max_lat,
                    layers=layers,
                )
                # Use unified data source manager
                feature_collection = self.data_source_manager.fetch(query)
                t_fetch = time.perf_counter()
                scene = self.scene_builder.build(
                    feature_collection=feature_collection,
                    geometry_profile=geometry_profile,
                    style_profile=style_profile,
                    quality_mode=quality_mode,
                )
                t_build = time.perf_counter()
                if version != self._request_version:
                    return

                self._last_scene = scene
                _LOGGER.info(
                    "request=%s source=%s cache=%s fetch_ms=%.1f build_ms=%.1f total_ms=%.1f features=%s layers=%d",
                    version,
                    feature_collection.metadata.get("source", "unknown"),
                    feature_collection.metadata.get("cache", "unknown"),
                    (t_fetch - t0) * 1000.0,
                    (t_build - t_fetch) * 1000.0,
                    (t_build - t0) * 1000.0,
                    _layer_feature_counts(feature_collection),
                    len(scene.layers),
                )
                on_scene(scene, str(feature_collection.metadata.get("cache", "unknown")))
            except ImportError as exc:
                _LOGGER.exception("request=%s failed - missing dependency", version)
                on_error(RuntimeError(f"Missing dependency: {exc}"))
            except FileNotFoundError as exc:
                _LOGGER.exception("request=%s failed - data file not found", version)
                on_error(RuntimeError(f"Data file not found: {exc}"))
            except Exception as exc:  # noqa: BLE001
                _LOGGER.exception("request=%s failed during fetch/build", version)
                if self._last_scene is not None:
                    try:
                        self.renderer.set_scene(self._last_scene)
                        on_scene(self._last_scene, "fallback")
                    except Exception:
                        pass
                on_error(exc)

        threading.Thread(target=_worker, daemon=True).start()

    def get_data_source_status(self) -> dict:
        """Get status of all data sources."""
        return self.data_source_manager.get_status()


def _layer_feature_counts(feature_collection: FeatureCollection) -> dict[str, int]:
    return {
        layer_name: len(feature_collection.features_by_layer.get(layer_name, []))
        for layer_name in sorted(feature_collection.features_by_layer.keys())
    }
