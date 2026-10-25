"""skia-python renderer for shapely vector layers."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
from pathlib import Path
import threading
from typing import Any

from shapely.geometry import LineString, LinearRing, Point, Polygon

from hipparchus.rendering.geometry_adapter import iter_atomic_geometries
from hipparchus.rendering.models import RGBAColor, RenderScene, ViewportState
from hipparchus.rendering.not_for_navigation import NOTICE
from hipparchus.rendering.not_for_navigation import applies as not_for_navigation_applies

# The type size, and where a label sits on its anchor, are one statement shared
# with the SVG writer. Plain constants: the application package imports this one.
DEFAULT_LABEL_SIZE = 10
BASELINE_SHIFT_EM = 0.35

_PERF_LOGGER = logging.getLogger("hipparchus.perf")


# Beyond this the memory cost grows faster than the visible gain, and a large
# preview at 4x can exhaust the surface allocation outright.
MAX_SUPERSAMPLE = 3.0


def _resample(image: Any, width: int, height: int, skia: Any) -> Any:
    """Downscale with a Mitchell filter, falling back to the original."""
    try:
        resized = image.resize(width, height, skia.SamplingOptions(skia.CubicResampler.Mitchell()))
    except Exception:  # noqa: BLE001 - an unfiltered preview beats no preview
        return image
    return resized if resized is not None else image


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


# Label font fallback. The default typeface is Latin-only, so a Japanese or
# Korean place name renders as tofu boxes. Skia's font manager can match a
# typeface that covers a specific character; results are cached per 256-point
# Unicode block so the lookup runs a handful of times, not once per label.
_UNSET = object()
_DEFAULT_TYPEFACE: Any = _UNSET
_FALLBACK_TYPEFACES: dict[int, Any] = {}
_FAMILY_TYPEFACES: dict[str, Any] = {}

# Fonts shipped with the app, by family name. Bundling the default means a
# machine without it still draws labels in a known face, the same face on every
# platform, rather than whatever the OS happens to call default. Noto Sans
# covers Latin, Greek and Cyrillic; the per-block fallback below reaches the OS
# for the scripts it does not, so a Japanese or Arabic name still renders.
_FONTS_DIR = Path(__file__).resolve().parents[1] / "ui" / "assets" / "fonts"
_BUNDLED_FONT_FILES: dict[str, str] = {"Noto Sans": "NotoSans-Regular.ttf"}
DEFAULT_FONT_FAMILY = "Noto Sans"
_BUNDLED_TYPEFACES: dict[str, Any] = {}


def _bundled_typeface(family: str) -> Any:
    """The shipped typeface for a family, or None if it is not one we ship."""
    if family not in _BUNDLED_FONT_FILES:
        return None
    if family not in _BUNDLED_TYPEFACES:
        skia = _import_skia()
        path = _FONTS_DIR / _BUNDLED_FONT_FILES[family]
        try:
            _BUNDLED_TYPEFACES[family] = (
                skia.Typeface.MakeFromFile(str(path)) if path.exists() else None
            )
        except Exception:  # noqa: BLE001 - a missing font is not a crash
            _BUNDLED_TYPEFACES[family] = None
    return _BUNDLED_TYPEFACES[family]


def available_font_families() -> tuple[str, ...]:
    """Every family the picker may offer: the bundled ones and the system's.

    Sorted and de-duplicated. Degrades to just the bundled families when Skia is
    unavailable, so the dropdown is never empty.
    """
    families = set(_BUNDLED_FONT_FILES)
    try:
        skia = _import_skia()
        manager = skia.FontMgr()
        for index in range(manager.countFamilies()):
            name = manager.getFamilyName(index)
            if name:
                families.add(name)
    except Exception:  # noqa: BLE001 - no Skia, no system list
        pass
    return tuple(sorted(families))


def _family_typeface(family: str) -> Any:
    """Return the typeface for a requested family, or None to use the default.

    A bundled family is loaded from its shipped file; otherwise the system is
    asked. None covers both "nothing requested" and "the system does not have
    it", so an unavailable family degrades to the default face rather than
    blanking every label.
    """
    requested = family.strip()
    if not requested:
        return None
    bundled = _bundled_typeface(requested)
    if bundled is not None:
        return bundled
    if requested not in _FAMILY_TYPEFACES:
        skia = _import_skia()
        try:
            _FAMILY_TYPEFACES[requested] = skia.FontMgr().matchFamilyStyle(requested, skia.FontStyle())
        except Exception:  # noqa: BLE001 - font matching is best effort
            _FAMILY_TYPEFACES[requested] = None
    return _FAMILY_TYPEFACES[requested]


def _default_typeface() -> Any:
    """Return the typeface used for Latin labels, or None if unavailable.

    The bundled default first, so labels look the same on every machine; the
    system's own default only if the shipped font is somehow missing.
    """
    global _DEFAULT_TYPEFACE
    if _DEFAULT_TYPEFACE is _UNSET:
        _DEFAULT_TYPEFACE = _bundled_typeface(DEFAULT_FONT_FAMILY)
        if _DEFAULT_TYPEFACE is None:
            skia = _import_skia()
            try:
                _DEFAULT_TYPEFACE = skia.FontMgr().matchFamilyStyleCharacter(
                    "", skia.FontStyle(), ["und"], ord("A")
                )
            except Exception:  # noqa: BLE001 - font matching is best effort
                _DEFAULT_TYPEFACE = None
    return _DEFAULT_TYPEFACE


def _typeface_for_text(text: str, base: Any = None) -> Any:
    """Return a typeface covering ``text``, or None when ``base`` suffices.

    Only the first character the base face cannot render decides the fallback:
    a mixed "Kyoto 京都" label is drawn entirely in the CJK face, which also
    covers Latin.

    ``base`` is the face the label would otherwise use, so coverage is judged
    against the family the user picked. Courier lacks kanji just as the default
    face does, and both must still fall back. Defaults to the Latin face.
    """
    if not text:
        return None
    default = base if base is not None else _default_typeface()
    if default is None:
        return None
    for char in text:
        code_point = ord(char)
        if code_point < 0x80 or default.unicharToGlyph(code_point):
            continue
        block = code_point >> 8
        if block not in _FALLBACK_TYPEFACES:
            skia = _import_skia()
            try:
                _FALLBACK_TYPEFACES[block] = skia.FontMgr().matchFamilyStyleCharacter(
                    "", skia.FontStyle(), ["und"], code_point
                )
            except Exception:  # noqa: BLE001 - fall back to the default face
                _FALLBACK_TYPEFACES[block] = None
        return _FALLBACK_TYPEFACES[block]
    return None


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
    #: Let the map run to the edges of the sheet instead of breathing inside a
    #: margin. Only worth asking for when the sheet already has the map's own
    #: shape -- otherwise the space reappears as letterboxing on the long side,
    #: which is why `PagePanelMixin` sizes the sheet and sets this together.
    edge_to_edge: bool = field(default=False, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _last_drawn_paths: int = field(default=0, init=False, repr=False)
    _label_font_size: int = field(default=DEFAULT_LABEL_SIZE, init=False, repr=False)
    # Empty means the default Latin face. Public so the UI can read it back.
    label_font_family: str = field(default="", init=False)
    _last_render_diagnostics: dict[str, object] = field(default_factory=dict, init=False, repr=False)

    def set_scene(self, scene: RenderScene) -> None:
        with self._lock:
            self.scene = scene
            # The scene carries the preset's ground, so switching to a dark
            # preset repaints the canvas instead of leaving pale lines on white.
            self.background = scene.background
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

    def set_label_font_family(self, family: str) -> None:
        """Set the font family for labels; empty selects the default face."""
        with self._lock:
            self.label_font_family = family.strip()
            # The cached picture holds the old face, so it has to be rebuilt.
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
            # Draw larger than needed, then resample down. Hairlines are the
            # whole point of a contour sheet and they alias badly at 1:1; a
            # quality profile that asks for oversampling now gets it.
            supersample = max(1.0, min(float(self.scene.supersample), MAX_SUPERSAMPLE))
            pixel_width = max(1, int(width * scale * supersample))
            pixel_height = max(1, int(height * scale * supersample))

            _PERF_LOGGER.debug(
                "RENDER_PREVIEW_PNG START: width=%d, height=%d, scale=%.1f, pixel=%dx%d",
                width, height, scale, pixel_width, pixel_height,
            )

            surface = skia.Surface(pixel_width, pixel_height)
            canvas = surface.getCanvas()
            canvas.scale(scale * supersample, scale * supersample)

            self._draw_scene(canvas, width, height)

            image = surface.makeImageSnapshot()
            if supersample > 1.0:
                image = _resample(image, max(1, int(width * scale)), max(1, int(height * scale)), skia)
            data = image.encodeToData()
            png_bytes = bytes(data) if data is not None else b""
            self._last_render_diagnostics = {
                "width": width,
                "height": height,
                "device_scale": scale,
                "supersample": supersample,
                "pixel_width": pixel_width,
                "pixel_height": pixel_height,
                "drawn_paths": self._last_drawn_paths,
                "scene_geometries": sum(len(layer.geometries) for layer in self.scene.layers),
                "png_bytes": len(png_bytes),
            }

            # Debug: check PNG content
            if len(png_bytes) < 10000:
                _PERF_LOGGER.warning(
                    "SMALL PNG: %d bytes, drawn_paths=%d, scene_bounds=%s, fit_scale=%.1f",
                    len(png_bytes),
                    self._last_drawn_paths,
                    self._scene_bounds,
                    self._fit_scale,
                )

            return png_bytes

    def render_png(self, width: int, height: int, *, scale: float = 1.0) -> bytes:
        """The scene at an exact pixel size, for export rather than preview.

        The preview draws at the display's device scale because it is going on
        a screen. An export is going into a file at the size that was asked
        for, so the scale is the caller's to choose — a poster at 300 dpi is a
        different request from a window on a laptop.
        """
        skia = _import_skia()
        with self._lock:
            supersample = max(1.0, min(float(self.scene.supersample), MAX_SUPERSAMPLE))
            pixel_width = max(1, int(width * scale * supersample))
            pixel_height = max(1, int(height * scale * supersample))

            surface = skia.Surface(pixel_width, pixel_height)
            canvas = surface.getCanvas()
            canvas.scale(scale * supersample, scale * supersample)
            # An exported PNG is the artefact that gets shared, so it carries
            # the notice. The preview above does not.
            self._draw_scene(canvas, width, height, furniture=True)

            image = surface.makeImageSnapshot()
            if supersample > 1.0:
                image = _resample(
                    image, max(1, int(width * scale)), max(1, int(height * scale)), skia
                )
            data = image.encodeToData()
            return bytes(data) if data is not None else b""

    def render_pdf(
        self,
        destination: Path,
        width: int,
        height: int,
        *,
        page_size: tuple[float, float] | None = None,
    ) -> None:
        """The scene as a PDF, drawn rather than photographed.

        The same `_draw_scene` the window and the PNG use, onto a document
        canvas — so the paths in the file are the paths on screen, at whatever
        size the reader opens it. A PDF made by embedding a bitmap would be a
        picture of a map; this is the map.

        **Two sizes, and they are not the same thing.** `width` and `height` are
        the drawing, in the units the PNG uses, because that is what decides how
        heavy a stroke is relative to the sheet. `page_size` is the physical
        page in points, 72 to the inch, which is what a printer obeys.

        They used to be one number, and it was the wrong one: the caller passed
        pixels at 300 dpi and Skia read them as points, so an A4 export was a
        page 34.4 x 48.7 inches. Drawing straight onto the correct page instead
        would have fixed the paper and made every line four times heavier, so
        the drawing keeps its own size and the canvas is scaled onto the paper.

        `page_size` of `None` reads the drawing as points, which is the right
        answer when no paper has been chosen.
        """
        skia = _import_skia()
        destination.parent.mkdir(parents=True, exist_ok=True)
        page_width, page_height = page_size or (float(width), float(height))
        with self._lock:
            stream = skia.FILEWStream(str(destination))
            try:
                document = skia.PDF.MakeDocument(stream)
                if document is None:  # pragma: no cover - skia without PDF support
                    raise RuntimeError("this build of Skia cannot write PDF")
                canvas = document.beginPage(float(page_width), float(page_height))
                canvas.scale(page_width / max(1, width), page_height / max(1, height))
                self._draw_scene(canvas, width, height, furniture=True)
                document.endPage()
                document.close()
            finally:
                stream.flush()

    def _draw_scene(
        self, canvas: Any, width: int, height: int, *, furniture: bool = False
    ) -> None:
        skia = _import_skia()
        canvas.clear(skia.ColorSetARGB(self.background.a, self.background.r, self.background.g, self.background.b))

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
            _PERF_LOGGER.debug(
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

        # The one thing this renderer draws that is not the map.
        #
        # Furniture is otherwise an SVG idea — the title, the scale bar and the
        # legend all live in the exporter. This does not, because **a PNG is the
        # artefact that actually gets shared**, and a sheet that looks like a
        # chart in an SVG looks exactly as much like one as a picture.
        #
        # Not on the preview: the window is not the artefact, and the status bar
        # already says what the map is made of. `furniture` is off by default so
        # that stays true without every caller having to remember it.
        if furniture and not_for_navigation_applies(self.scene):
            self._draw_not_for_navigation(canvas, width, height, skia)

    def _draw_not_for_navigation(self, canvas: Any, width: int, height: int, skia: Any) -> None:
        """The notice, bottom centre, on a panel that keeps it legible over a
        dark sea or a busy coast."""
        luminance = (
            0.2126 * self.background.r + 0.7152 * self.background.g + 0.0722 * self.background.b
        )
        dark = luminance < 128.0
        ink = (242, 242, 242) if dark else (34, 34, 34)
        panel = (18, 21, 28) if dark else (255, 255, 255)

        short = min(width, height)
        size = max(9.0, short * 0.014)
        font = skia.Font(skia.Typeface("Helvetica", skia.FontStyle.Bold()), size)
        text_width = font.measureText(NOTICE)
        padding = size * 0.7

        x = (width - text_width) / 2.0
        y = height - max(10.0, short * 0.022)

        panel_paint = skia.Paint(
            AntiAlias=True, Color=skia.ColorSetARGB(210, panel[0], panel[1], panel[2])
        )
        canvas.drawRect(
            skia.Rect.MakeLTRB(
                x - padding, y - size - padding * 0.5, x + text_width + padding, y + padding * 0.7
            ),
            panel_paint,
        )
        text_paint = skia.Paint(
            AntiAlias=True, Color=skia.ColorSetARGB(255, ink[0], ink[1], ink[2])
        )
        canvas.drawString(NOTICE, x, y, font, text_paint)

    def _draw_vector_layers(self, canvas: Any, width: int, height: int, sampled: bool) -> int:
        skia = _import_skia()
        canvas.save()
        self._apply_fit_transform(canvas, width, height)
        remaining_budget = self.preview_max_total_geometries
        drawn_paths = 0

        # Debug: log first layer's stroke color
        _first_layer = True

        # Turns rather than layers, so a run of road layers lays every casing
        # down before any of its lines. See `application/road_network.py`.
        # Imported here: the application package imports this one.
        from hipparchus.application.road_network import draw_turns

        selections: dict[int, list[Any]] = {}
        for turn in draw_turns(list(self.scene.iter_visible_layers())):
            layer = turn.layer
            if sampled and remaining_budget <= 0 and id(layer) not in selections:
                break
            # Opacity belongs to the layer, not to each part of it, so it is
            # applied once by compositing the whole layer as a group below
            # rather than folded into every colour here. Folded in, two
            # overlapping parts of one layer blend against each other and the
            # seam between them reads darker than either — which is how ten
            # elevation bands, flattened into 248 loose polygons by the clip,
            # turned a warm tan Cyprus into a pale grey one while the Swift
            # port drew it correctly from identical colours. `<g opacity>` in
            # SVG and PDF means the group; this now means the same thing.
            stroke_color = layer.style.stroke_color
            fill_color = layer.style.fill_color

            # Debug: log first visible layer
            if _first_layer and layer.geometries:
                _PERF_LOGGER.debug(
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
                casing_color = layer.style.casing_color
                casing_paint = skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=max(0.0001, layer.style.casing_width) / self._fit_scale,
                    Color=skia.ColorSetARGB(casing_color.a, casing_color.r, casing_color.g, casing_color.b),
                )
                casing_paint.setStrokeCap(cap)
                casing_paint.setStrokeJoin(join)

            # Weighted layers keep geometry and weight paired through sampling,
            # so a thinned preview never draws a line at another line's weight.
            weighted = bool(layer.weights)
            indexed = list(enumerate(layer.geometries))
            if id(layer) in selections:
                # The casing turn already chose what to draw of this layer.
                selected_pairs = selections[id(layer)]
            elif sampled:
                selected_pairs = self._sample_layer_geometries(
                    layer_name=layer.name,
                    geometries=indexed,
                    hard_cap=min(self.preview_max_geometries_per_layer, remaining_budget),
                )
                remaining_budget -= len(selected_pairs)
            else:
                selected_pairs = indexed
            selections[id(layer)] = selected_pairs
            selected = [geometry for _index, geometry in selected_pairs]

            # One paint per distinct weight, not per geometry: weights are
            # quantised into a handful of bands, so this stays a small cache.
            weight_paints: dict[float, Any] = {}
            banded = bool(layer.fill_colors)
            fill_paints: dict[tuple[int, int, int, int], Any] = {}

            def _fill_paint_for(color: RGBAColor) -> Any:
                shaded = color
                key = (shaded.r, shaded.g, shaded.b, shaded.a)
                cached = fill_paints.get(key)
                if cached is None:
                    cached = skia.Paint(
                        AntiAlias=True,
                        Style=skia.Paint.kFill_Style,
                        Color=skia.ColorSetARGB(shaded.a, shaded.r, shaded.g, shaded.b),
                    )
                    fill_paints[key] = cached
                return cached

            def _stroke_paint_for(weight: float) -> Any:
                if weight == 1.0:
                    return stroke_paint
                cached = weight_paints.get(weight)
                if cached is None:
                    cached = skia.Paint(
                        AntiAlias=True,
                        Style=skia.Paint.kStroke_Style,
                        StrokeWidth=max(0.0001, layer.style.stroke_width * weight) / self._fit_scale,
                        Color=skia.ColorSetARGB(stroke_color.a, stroke_color.r, stroke_color.g, stroke_color.b),
                    )
                    cached.setStrokeCap(cap)
                    cached.setStrokeJoin(join)
                    weight_paints[weight] = cached
                return cached

            # Skip label-only layers in the geometry pass — labels are drawn
            # separately in _draw_labels so they remain at fixed pixel size.
            if layer.name in {"places", "shops", "amenities"} and not layer.geometries:
                continue

            # The layer is composited as one group at its own opacity, so its
            # parts draw against each other at full strength and the finished
            # layer is faded once. A fully opaque layer skips the offscreen
            # surface entirely — most layers are opaque, and there is no reason
            # to pay for a save layer that would composite unchanged.
            alpha = max(0.0, min(1.0, layer.style.opacity))
            grouped = alpha < 1.0
            if grouped:
                canvas.saveLayerAlpha(None, round(alpha * 255))

            # First pass: draw all casings (so they appear underneath all fills)
            if casing_paint is not None and turn.part != "body":
                for geometry in selected:
                    for atomic in iter_atomic_geometries(geometry):
                        if isinstance(atomic, (LineString, LinearRing)):
                            path = self._path_for_geometry(atomic, skia)
                            if path is not None:
                                canvas.drawPath(path, casing_paint)

            # Second pass: draw fills and strokes
            for index, geometry in (selected_pairs if turn.part != "casing" else ()):
                paint = _stroke_paint_for(layer.weight_at(index)) if weighted else stroke_paint
                for atomic in iter_atomic_geometries(geometry):
                    path = self._path_for_geometry(atomic, skia)
                    if path is None:
                        continue
                    if layer.style.fill_enabled and isinstance(atomic, Polygon):
                        canvas.drawPath(
                            path,
                            _fill_paint_for(layer.fill_color_at(index)) if banded else fill_paint,
                        )
                    canvas.drawPath(path, paint)
                    drawn_paths += 1

            if grouped:
                canvas.restore()
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
        they are immune to viewport zoom -- they always render at the configured
        font size in screen pixels, scaled with the sheet (`scene.label_scale`).
        Which labels survive is decided over every visible layer at once by
        `lay_out_labels`, the same call the SVG writer makes.
        """
        from hipparchus.rendering.label_layout import LabelType, lay_out_labels

        if self._scene_bounds is None:
            return

        try:
            label_type = LabelType(getattr(self, "_label_font_size", DEFAULT_LABEL_SIZE), self.label_font_family)
        except Exception:  # noqa: BLE001 - no usable font on this system
            return

        def _to_screen(wx: float, wy: float) -> tuple[float, float] | None:
            return self.world_to_screen(wx, wy, width, height)

        placed = lay_out_labels(
            list(self.scene.iter_visible_layers()), self.scene, label_type, _to_screen,
            width, height, extra_rotation=self.viewport.rotation,
        )
        layer_styles = {layer.name: layer.style for layer in self.scene.layers}
        for label in placed:
            style = layer_styles[label.layer_name]
            font = label_type.font(label.text, label.size)
            text_color = style.stroke_color
            text_paint = skia.Paint(
                AntiAlias=True,
                Style=skia.Paint.kFill_Style,
                Color=skia.ColorSetARGB(255, text_color.r, text_color.g, text_color.b),
            )
            baseline = label.y + label.size * BASELINE_SHIFT_EM
            left = label.x - label.width / 2.0
            canvas.save()
            if label.rotation:
                canvas.rotate(label.rotation, label.x, label.y)
            if label.halo > 0.0:
                halo_color = style.label_halo_color
                halo_paint = skia.Paint(
                    AntiAlias=True,
                    Style=skia.Paint.kStroke_Style,
                    StrokeWidth=label.halo,
                    Color=skia.ColorSetARGB(halo_color.a, halo_color.r, halo_color.g, halo_color.b),
                )
                halo_paint.setStrokeJoin(skia.Paint.kRound_Join)
                canvas.drawString(label.text, left, baseline, font, halo_paint)
            canvas.drawString(label.text, left, baseline, font, text_paint)
            canvas.restore()

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

    def fit_margin(self, width: int, height: int) -> float:
        """Points of breathing room around the map, or none when bleeding.

        One place rather than two: `fit_metrics` calls itself the single source
        of truth for the fit and `_apply_fit_transform` recomputed the same
        arithmetic beside it, so a margin changed in one was a map drawn at one
        scale and hit-tested at another.
        """
        if self.edge_to_edge:
            return 0.0
        return max(16.0, min(width, height) * 0.06)

    def scene_aspect(self) -> float | None:
        """The drawn map's own width-over-height, or None with nothing drawn.

        What a sheet has to match for `edge_to_edge` to mean anything: a 2:1
        world on a 4:3 sheet is letterboxed whatever the margin says, because
        the bar is sheet the map never reaches rather than padding.
        """
        if self._scene_bounds is None:
            return None
        minx, miny, maxx, maxy = self._scene_bounds
        span_x = max(maxx - minx, 1e-9)
        span_y = max(maxy - miny, 1e-9)
        aspect = span_x / span_y
        return aspect if aspect > 0 else None

    def fit_metrics(self, width: int, height: int) -> tuple[float, float, float, float, float] | None:
        """``(fit_scale, offset_x, offset_y, min_x, max_y)`` for the fit transform.

        The single source of truth for how world coordinates land on the canvas.
        Both directions of the mapping and the drawing code all read it, so they
        cannot drift apart.
        """
        if self._scene_bounds is None:
            return None
        minx, miny, maxx, maxy = self._scene_bounds
        span_x = max(maxx - minx, 1e-9)
        span_y = max(maxy - miny, 1e-9)
        margin = self.fit_margin(width, height)
        avail_w = max(1.0, width - 2.0 * margin)
        avail_h = max(1.0, height - 2.0 * margin)
        fit_scale = max(1e-6, min(min(avail_w / span_x, avail_h / span_y), 1e6))
        offset_x = (width - span_x * fit_scale) * 0.5
        offset_y = (height - span_y * fit_scale) * 0.5
        return (fit_scale, offset_x, offset_y, minx, maxy)

    def world_to_screen(self, wx: float, wy: float, width: int, height: int) -> tuple[float, float] | None:
        """World (projected) coordinates to canvas pixels."""
        metrics = self.fit_metrics(width, height)
        if metrics is None:
            return None
        fit_scale, offset_x, offset_y, minx, maxy = metrics
        px = offset_x + (wx - minx) * fit_scale
        py = offset_y + (maxy - wy) * fit_scale
        radians = math.radians(self.viewport.rotation)
        cos_r, sin_r = math.cos(radians), math.sin(radians)
        rx = px * cos_r - py * sin_r
        ry = px * sin_r + py * cos_r
        return (self.viewport.pan_x + rx * self.viewport.zoom, self.viewport.pan_y + ry * self.viewport.zoom)

    def screen_to_world(self, sx: float, sy: float, width: int, height: int) -> tuple[float, float] | None:
        """Canvas pixels back to world (projected) coordinates.

        The inverse of :meth:`world_to_screen`, which is what lets the canvas be
        used as an input device rather than only as a picture.
        """
        metrics = self.fit_metrics(width, height)
        if metrics is None:
            return None
        fit_scale, offset_x, offset_y, minx, maxy = metrics
        zoom = self.viewport.zoom or 1.0
        rx = (sx - self.viewport.pan_x) / zoom
        ry = (sy - self.viewport.pan_y) / zoom
        radians = math.radians(self.viewport.rotation)
        cos_r, sin_r = math.cos(radians), math.sin(radians)
        px = rx * cos_r + ry * sin_r
        py = -rx * sin_r + ry * cos_r
        return (minx + (px - offset_x) / fit_scale, maxy - (py - offset_y) / fit_scale)

    def _apply_fit_transform(self, canvas: Any, width: int, height: int) -> None:
        """Map world-coordinate geometry bounds into visible canvas space."""
        if self._scene_bounds is None:
            self._fit_scale = 1.0
            return

        minx, miny, maxx, maxy = self._scene_bounds
        span_x = max(maxx - minx, 1e-9)
        span_y = max(maxy - miny, 1e-9)

        margin = self.fit_margin(width, height)
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
    """Thin a vertex list without changing the shape it describes.

    The stride is chosen so the result fits the budget outright. The previous
    version could still overshoot after striding, and dealt with it by cutting
    the list short and jumping to the final vertex -- which draws one long chord
    straight across the shape. On a coastline-hugging contour, and Santorini's
    have upwards of eight thousand vertices, that reads as a line ruled across
    the island.
    """
    if len(coords) <= max_vertices or max_vertices < 3:
        return coords

    step = math.ceil(len(coords) / max_vertices)
    sampled = coords[::step]
    if sampled[-1] != coords[-1]:
        sampled.append(coords[-1])
    return sampled
