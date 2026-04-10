"""skia-python renderer for shapely vector layers."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Any

from shapely.geometry import LineString, LinearRing, Point, Polygon

from hipparchus.rendering.geometry_adapter import iter_atomic_geometries
from hipparchus.rendering.models import RGBAColor, RenderScene, ViewportState


class SkiaUnavailableError(RuntimeError):
    """Raised when skia-python is required but not installed."""


_SKIA_MODULE: Any | None = None


def _import_skia() -> Any:
    global _SKIA_MODULE
    if _SKIA_MODULE is not None:
        return _SKIA_MODULE
    try:
        import skia  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise SkiaUnavailableError(
            "skia-python is not installed. Install with: pip install skia-python"
        ) from exc
    _SKIA_MODULE = skia
    return _SKIA_MODULE


@dataclass(slots=True)
class SkiaRenderer:
    """Renderer supporting layer styles, zoom/pan, and retina scaling."""

    scene: RenderScene = field(default_factory=RenderScene)
    viewport: ViewportState = field(default_factory=ViewportState)
    device_scale: float = 1.0
    background: RGBAColor = field(default_factory=lambda: RGBAColor(250, 250, 250, 255))
    preview_max_geometries_per_layer: int = 100000
    preview_max_total_geometries: int = 300000

    _picture_cache: Any = field(default=None, init=False, repr=False)
    _dirty: bool = field(default=True, init=False, repr=False)
    _path_cache: dict[int, Any] = field(default_factory=dict, init=False, repr=False)
    _scene_bounds: tuple[float, float, float, float] | None = field(default=None, init=False, repr=False)
    _cache_width: int = field(default=0, init=False, repr=False)
    _cache_height: int = field(default=0, init=False, repr=False)
    _fit_scale: float = field(default=1.0, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _last_drawn_paths: int = field(default=0, init=False, repr=False)
    _label_font_size: int = field(default=10, init=False, repr=False)

    def set_scene(self, scene: RenderScene) -> None:
        with self._lock:
            self.scene = scene
            self._dirty = True
            self._path_cache.clear()
            self._scene_bounds = self._compute_scene_bounds()

    def set_viewport(self, viewport: ViewportState) -> None:
        with self._lock:
            self.viewport = viewport

    def pan(self, dx: float, dy: float) -> None:
        with self._lock:
            self.viewport = self.viewport.with_pan(dx, dy)

    def zoom(self, factor: float) -> None:
        with self._lock:
            self.viewport = self.viewport.with_zoom(factor)

    def rotate(self, degrees: float) -> None:
        """Rotate viewport by given degrees."""
        with self._lock:
            self.viewport = self.viewport.with_rotation(self.viewport.rotation + degrees)

    def set_rotation(self, degrees: float) -> None:
        """Set viewport rotation to absolute degrees."""
        with self._lock:
            self.viewport = self.viewport.with_rotation(degrees)

    def set_label_font_size(self, size: int) -> None:
        """Set the font size for place labels."""
        with self._lock:
            self._label_font_size = size
            self._dirty = True

    def set_layer_visibility(self, layer_name: str, visible: bool) -> None:
        with self._lock:
            for layer in self.scene.layers:
                if layer.name == layer_name:
                    if layer.style.visible != visible:
                        layer.style.visible = visible
                        self._dirty = True
                    break

    def render_preview_png(self, width: int, height: int) -> bytes:
        """Render scene to PNG bytes for fast UI preview refresh."""
        skia = _import_skia()
        with self._lock:
            scale = max(1.0, self.device_scale)
            pixel_width = max(1, int(width * scale))
            pixel_height = max(1, int(height * scale))

            import logging
            logging.getLogger("hipparchus.perf").info(
                "RENDER_PREVIEW_PNG START: width=%d, height=%d, scale=%.1f, pixel=%dx%d",
                width, height, scale, pixel_width, pixel_height,
            )

            surface = skia.Surface(pixel_width, pixel_height)
            canvas = surface.getCanvas()
            canvas.scale(scale, scale)

            self._draw_scene(canvas, width, height)

            image = surface.makeImageSnapshot()
            data = image.encodeToData()
            png_bytes = bytes(data) if data is not None else b""
            
            # Debug: check PNG content
            if len(png_bytes) < 10000:
                logging.getLogger("hipparchus.perf").warning(
                    "SMALL PNG: %d bytes, drawn_paths=%d, scene_bounds=%s, fit_scale=%.1f",
                    len(png_bytes),
                    self._last_drawn_paths,
                    self._scene_bounds,
                    self._fit_scale,
                )
            
            return png_bytes

    def _draw_scene(self, canvas: Any, width: int, height: int) -> None:
        skia = _import_skia()
        canvas.clear(skia.ColorSetARGB(self.background.a, self.background.r, self.background.g, self.background.b))

        # Debug: check scene state
        import logging
        scene_layers = len(self.scene.layers) if self.scene else 0
        scene_geoms = sum(len(l.geometries) for l in self.scene.layers) if self.scene else 0
        logging.getLogger("hipparchus.perf").info(
            "DRAW_SCENE: scene_layers=%d, scene_geoms=%d, bounds=%s, dirty=%s, cache_valid=%s",
            scene_layers,
            scene_geoms,
            self._scene_bounds,
            self._dirty,
            self._picture_cache is not None,
        )

        if self._dirty or self._picture_cache is None or self._cache_width != width or self._cache_height != height:
            recorder = skia.PictureRecorder()
            if self._scene_bounds is None:
                cull = skia.Rect.MakeWH(width, height)
            else:
                cull = skia.Rect.MakeWH(width, height)
            rec_canvas = recorder.beginRecording(cull)
            drawn_paths = self._draw_vector_layers(rec_canvas, width, height, sampled=True)
            if drawn_paths == 0:
                rec_canvas.clear(skia.ColorSetARGB(self.background.a, self.background.r, self.background.g, self.background.b))
                drawn_paths = self._draw_vector_layers(rec_canvas, width, height, sampled=False)
            self._last_drawn_paths = drawn_paths
            self._picture_cache = recorder.finishRecordingAsPicture()
            self._cache_width = width
            self._cache_height = height
            self._dirty = False
            
            # Debug: log picture recording
            import logging
            logging.getLogger("hipparchus.perf").info(
                "PICTURE RECORDED: drawn_paths=%d, dirty=%s, bounds=%s",
                drawn_paths,
                self._dirty,
                self._scene_bounds,
            )

        canvas.save()
        # Apply viewport transform: pan, zoom, and rotation
        canvas.translate(self.viewport.pan_x, self.viewport.pan_y)
        canvas.scale(self.viewport.zoom, self.viewport.zoom)
        if self.viewport.rotation != 0.0:
            canvas.rotate(self.viewport.rotation)
        canvas.drawPicture(self._picture_cache)
        canvas.restore()

        # Draw labels in a SEPARATE pass so they stay at fixed pixel size
        # regardless of viewport zoom.
        self._draw_labels(canvas, width, height, skia)

    def _draw_vector_layers(self, canvas: Any, width: int, height: int, sampled: bool) -> int:
        skia = _import_skia()
        canvas.save()
        self._apply_fit_transform(canvas, width, height)
        remaining_budget = self.preview_max_total_geometries
        drawn_paths = 0

        # Debug: log first layer's stroke color
        _first_layer = True

        for layer in self.scene.iter_visible_layers():
            if sampled and remaining_budget <= 0:
                break
            stroke_color = layer.style.stroke_color.with_opacity(layer.style.opacity)
            fill_color = layer.style.fill_color.with_opacity(layer.style.opacity)

            # Debug: log first visible layer
            if _first_layer and layer.geometries:
                import logging
                logging.getLogger("hipparchus.perf").info(
                    "DEBUG First visible layer: %s, stroke=(%d,%d,%d,%d), fill=(%d,%d,%d,%d), geoms=%d, fit_scale=%.1f",
                    layer.name,
                    stroke_color.r, stroke_color.g, stroke_color.b, stroke_color.a,
                    fill_color.r, fill_color.g, fill_color.b, fill_color.a,
                    len(layer.geometries),
                    self._fit_scale,
                )
                _first_layer = False

            # Line cap style
            cap = skia.Paint.kRound_Cap if layer.style.line_cap == "round" else skia.Paint.kButt_Cap
            join = skia.Paint.kRound_Join if layer.style.line_cap == "round" else skia.Paint.kMiter_Join

            stroke_paint = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kStroke_Style,
                StrokeWidth=max(0.0001, layer.style.stroke_width) / self._fit_scale,
                Color=skia.ColorSetARGB(stroke_color.a, stroke_color.r, stroke_color.g, stroke_color.b),
            )
            stroke_paint.setStrokeCap(cap)
            stroke_paint.setStrokeJoin(join)

            fill_paint = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kFill_Style,
                Color=skia.ColorSetARGB(fill_color.a, fill_color.r, fill_color.g, fill_color.b),
            )

            # Road casing paint (wider stroke drawn underneath)
            casing_paint = None
            if layer.style.casing_width > 0:
                casing_color = layer.style.casing_color.with_opacity(layer.style.opacity)
                casing_paint = skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=max(0.0001, layer.style.casing_width) / self._fit_scale,
                    Color=skia.ColorSetARGB(casing_color.a, casing_color.r, casing_color.g, casing_color.b),
                )
                casing_paint.setStrokeCap(cap)
                casing_paint.setStrokeJoin(join)

            if sampled:
                selected = self._sample_layer_geometries(
                    layer_name=layer.name,
                    geometries=layer.geometries,
                    hard_cap=min(self.preview_max_geometries_per_layer, remaining_budget),
                )
                remaining_budget -= len(selected)
            else:
                selected = layer.geometries

            # Skip label-only layers in the geometry pass — labels are drawn
            # separately in _draw_labels so they remain at fixed pixel size.
            if layer.name in {"places", "shops", "amenities"} and not layer.geometries:
                continue

            # First pass: draw all casings (so they appear underneath all fills)
            if casing_paint is not None:
                for geometry in selected:
                    for atomic in iter_atomic_geometries(geometry):
                        if isinstance(atomic, (LineString, LinearRing)):
                            path = self._path_for_geometry(atomic, skia)
                            if path is not None:
                                canvas.drawPath(path, casing_paint)

            # Second pass: draw fills and strokes
            for geometry in selected:
                for atomic in iter_atomic_geometries(geometry):
                    path = self._path_for_geometry(atomic, skia)
                    if path is None:
                        continue
                    if layer.style.fill_enabled and isinstance(atomic, Polygon):
                        canvas.drawPath(path, fill_paint)
                    canvas.drawPath(path, stroke_paint)
                    drawn_paths += 1
        canvas.restore()
        return drawn_paths

    def _sample_layer_geometries(self, layer_name: str, geometries: list[Any], hard_cap: int) -> list[Any]:
        if hard_cap <= 0 or not geometries:
            return []

        # Heavy derived layers get a stricter cap in interactive preview.
        derived_cap = 700 if layer_name in {"voronoi_cells", "delaunay_mesh", "hex_grid", "circle_packing"} else hard_cap
        cap = max(1, min(hard_cap, derived_cap))
        if len(geometries) <= cap:
            return geometries

        step = max(1, len(geometries) // cap)
        sampled = geometries[::step]
        if len(sampled) > cap:
            return sampled[:cap]
        return sampled

    def _draw_labels(self, canvas: Any, width: int, height: int, skia: Any) -> None:
        """Draw place/shop/amenity labels at fixed pixel size.

        Labels are drawn in a separate pass (not inside the cached Picture) so
        they are immune to viewport zoom — they always render at the configured
        font size in screen pixels.
        """
        from hipparchus.rendering.models import PlaceLabel

        if self._scene_bounds is None:
            return

        font_size = max(6, min(getattr(self, '_label_font_size', 10), 16))

        try:
            font = skia.Font(None, font_size)
        except Exception:
            return

        bg_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(180, 255, 255, 255))
        text_paint = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(255, 40, 40, 40))
        pad = 2.0

        # Pre-compute the world → screen transform (fit + viewport).
        minx, miny, maxx, maxy = self._scene_bounds
        span_x = max(maxx - minx, 1e-9)
        span_y = max(maxy - miny, 1e-9)
        margin = max(16.0, min(width, height) * 0.06)
        avail_w = max(1.0, width - 2.0 * margin)
        avail_h = max(1.0, height - 2.0 * margin)
        fit_scale = min(avail_w / span_x, avail_h / span_y)
        fit_scale = max(1e-6, min(fit_scale, 1e6))
        draw_w = span_x * fit_scale
        draw_h = span_y * fit_scale
        offset_x = (width - draw_w) * 0.5
        offset_y = (height - draw_h) * 0.5

        zoom = self.viewport.zoom
        pan_x = self.viewport.pan_x
        pan_y = self.viewport.pan_y

        def _world_to_screen(wx: float, wy: float) -> tuple[float, float]:
            # Fit transform (with Y-flip: north up).
            sx = offset_x + (wx - minx) * fit_scale
            sy = offset_y + (maxy - wy) * fit_scale
            # Viewport transform.
            return pan_x + sx * zoom, pan_y + sy * zoom

        # Collect labels with their screen positions, then cull off-screen and
        # suppress overlapping labels so the map stays readable at every zoom.
        entries: list[tuple[float, float, str]] = []
        for layer in self.scene.iter_visible_layers():
            if not layer.labels:
                continue
            for label in layer.labels:
                if not isinstance(label, PlaceLabel) or not label.name:
                    continue
                sx, sy = _world_to_screen(float(label.x), float(label.y))
                # Cull labels that are off-screen.
                if sx < -100 or sx > width + 100 or sy < -100 or sy > height + 100:
                    continue
                entries.append((sx, sy, str(label.name)))

        # Simple overlap suppression: reject any label whose centre is too
        # close to an already-placed label.
        min_gap_x = font_size * 6.0  # approximate character-width heuristic
        min_gap_y = font_size * 1.6
        placed: list[tuple[float, float, float]] = []  # (cx, cy, half_w)

        for sx, sy, text in entries:
            tw = font.measureText(text)
            half_w = tw / 2.0
            # Check overlap with already-placed labels.
            collides = False
            for px, py, phw in placed:
                if abs(sx - px) < (half_w + phw + pad * 2) and abs(sy - py) < min_gap_y:
                    collides = True
                    break
            if collides:
                continue
            placed.append((sx, sy, half_w))

            # Draw background pill.
            rect = skia.Rect.MakeXYWH(
                sx - half_w - pad,
                sy - font_size - pad,
                tw + 2 * pad,
                font_size + 2 * pad,
            )
            canvas.drawRect(rect, bg_paint)

            # Draw text.
            canvas.drawString(text, sx - half_w, sy - 2, font, text_paint)

    def _path_for_geometry(self, geometry: Any, skia: Any) -> Any | None:
        key = id(geometry)
        cached = self._path_cache.get(key)
        if cached is not None:
            return cached

        path = self._shape_to_skia_path(geometry, skia)
        if path is not None:
            self._path_cache[key] = path
        return path

    @staticmethod
    def _is_line_like(geometry: Any) -> bool:
        return isinstance(geometry, (LineString, LinearRing))

    @staticmethod
    def _shape_to_skia_path(geometry: Any, skia: Any) -> Any | None:
        path = skia.Path()

        if isinstance(geometry, Point):
            # Points are labels, not circles - skip rendering as geometry
            return None

        if isinstance(geometry, (LineString, LinearRing)):
            coords = _decimate_coords(list(geometry.coords), 5000)
            if len(coords) < 2:
                return None
            path.moveTo(coords[0][0], coords[0][1])
            for x, y in coords[1:]:
                path.lineTo(x, y)
            return path

        if isinstance(geometry, Polygon):
            ext = list(geometry.exterior.coords)
            if len(ext) >= 3:
                path.moveTo(ext[0][0], ext[0][1])
                for x, y in ext[1:]:
                    path.lineTo(x, y)
                path.close()

            for interior in geometry.interiors:
                ring = list(interior.coords)
                if len(ring) < 3:
                    continue
                path.moveTo(ring[0][0], ring[0][1])
                for x, y in ring[1:]:
                    path.lineTo(x, y)
                path.close()
            return path

        return None

    def _compute_scene_bounds(self) -> tuple[float, float, float, float] | None:
        # Use the scene bbox if available (this is the requested query area)
        if self.scene.bbox is not None:
            return self.scene.bbox

        # Fall back to computing from geometries
        minx: float | None = None
        miny: float | None = None
        maxx: float | None = None
        maxy: float | None = None

        for layer in self.scene.layers:
            for geometry in layer.geometries:
                if geometry.is_empty:
                    continue
                gx1, gy1, gx2, gy2 = geometry.bounds
                minx = gx1 if minx is None else min(minx, gx1)
                miny = gy1 if miny is None else min(miny, gy1)
                maxx = gx2 if maxx is None else max(maxx, gx2)
                maxy = gy2 if maxy is None else max(maxy, gy2)

        if minx is None or miny is None or maxx is None or maxy is None:
            return None
        return (minx, miny, maxx, maxy)

    def _apply_fit_transform(self, canvas: Any, width: int, height: int) -> None:
        """Map world-coordinate geometry bounds into visible canvas space."""
        if self._scene_bounds is None:
            self._fit_scale = 1.0
            return

        minx, miny, maxx, maxy = self._scene_bounds
        span_x = max(maxx - minx, 1e-9)
        span_y = max(maxy - miny, 1e-9)

        margin = max(16.0, min(width, height) * 0.06)
        avail_w = max(1.0, width - 2.0 * margin)
        avail_h = max(1.0, height - 2.0 * margin)
        fit_scale = min(avail_w / span_x, avail_h / span_y)
        fit_scale = max(1e-6, min(fit_scale, 1e6))
        self._fit_scale = fit_scale

        draw_w = span_x * fit_scale
        draw_h = span_y * fit_scale
        offset_x = (width - draw_w) * 0.5
        offset_y = (height - draw_h) * 0.5

        canvas.translate(offset_x, offset_y)
        # Flip Y axis so North is up (latitude increases upward)
        canvas.scale(fit_scale, -fit_scale)
        canvas.translate(-minx, -maxy)


def _decimate_coords(coords: list[tuple[float, float]], max_vertices: int) -> list[tuple[float, float]]:
    if len(coords) <= max_vertices or max_vertices < 3:
        return coords

    step = max(1, len(coords) // max_vertices)
    sampled = coords[::step]
    if sampled[-1] != coords[-1]:
        sampled.append(coords[-1])
    if len(sampled) > max_vertices:
        sampled = sampled[: max_vertices - 1] + [coords[-1]]
    return sampled
