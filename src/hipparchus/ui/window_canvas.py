"""The map canvas: taking scenes from the worker, redrawing, and the view controls.

A mixin for `MainWindow`: the methods read and write the window's own state.
"""

from __future__ import annotations

import base64
import os
import queue
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from hipparchus.application import provenance
from hipparchus.core.fetch_progress import FetchReporter
from hipparchus.rendering.models import RenderScene, ViewportState
from hipparchus.ui import theme


class CanvasMixin:
    """The map canvas: taking scenes from the worker, redrawing, and the view controls."""

    def _queue_progress(self, reporter: FetchReporter) -> None:
        """Called from the fetch thread; hand it to the UI thread to display."""
        self._pending_queue.put(("progress", reporter.snapshot()))

    def _queue_scene(self, scene: RenderScene, cache_state: str) -> None:
        self._pending_queue.put(("scene", (scene, cache_state)))

    def _queue_error(self, error: Exception) -> None:
        self._pending_queue.put(("error", error))

    def _drain_callback_queue(self) -> None:
        try:
            while True:
                kind, payload = self._pending_queue.get_nowait()
                if kind == "scene":
                    scene, cache_state = payload
                    self._apply_scene(scene, cache_state)
                    # The fetch that asked for this is over. Its own end,
                    # rather than a redraw popping one more than it pushed,
                    # which is what used to stop the spinner.
                    self._set_idle()
                elif kind == "run":
                    # A callable a worker thread wants run on the UI thread. Tk's
                    # own after() is not thread-safe to call off it; the queue is.
                    payload()
                elif kind == "places":
                    self._show_search_results(payload)
                elif kind == "search_failed":
                    self._search_failed(payload)
                elif kind == "image":
                    self._apply_canvas_png(payload)
                elif kind == "progress":
                    self._status.show_progress(payload)
                elif kind == "error":
                    error_msg = str(payload)
                    if "No match" in error_msg:
                        messagebox.showerror("Location Not Found", f"Could not find location: {error_msg}")
                    elif "timeout" in error_msg.lower():
                        messagebox.showerror("Timeout", f"Request timed out. Try again or use a smaller area.\n{error_msg}")
                    elif "local OSM data" in error_msg.lower():
                        messagebox.showerror("Data Not Available", error_msg)
                    else:
                        messagebox.showerror("Error", error_msg)
                    self._status.set_message(f"Error: {error_msg[:80]}")
                    self._set_idle("Error")
        except queue.Empty:
            pass
        except Exception:  # noqa: BLE001
            # The loop must survive a bad callback. Rescheduling below happens
            # either way; without this an exception here would silently stop
            # every future scene, image and progress update.
            self._logger.exception("callback queue handler failed")
        finally:
            self._queue_job = self._root.after(60, self._drain_callback_queue)

    def _apply_scene(self, scene: RenderScene, cache_state: str) -> None:
        self._current_scene = scene
        # What this map is *of*, kept so the next Render map can tell a pan
        # apart from a choice. The scene's own bounds rather than the
        # coordinate boxes: the boxes can be edited, and the map cannot.
        self._rendered_area = scene.source_bbox
        self._status.set_provenance(provenance.for_sources(self.source_stack.enabled_ids()))
        if cache_state != "undo" and not self._restoring:
            # Undo of a fetch must never cost another fetch, so the map itself
            # is kept with the entry rather than the recipe for making it.
            self._history.record_fetch(self.current_session(), scene)
            self._refresh_undo_menu()
        if self._layers_panel is not None:
            self._layer_summary = self._layers_panel.update(scene)
            self._layer_visibility_vars = self._layers_panel.visibility_vars()
        # Follow the new preset's ground, so switching to or from a dark preset
        # repaints the margin around the fitted render too.
        self._canvas.configure(background=self._canvas_surround_color())
        self._sync_layer_visibility_to_scene()
        self.renderer.set_scene(scene)
        self.renderer.set_viewport(ViewportState())
        self._status.set_cache(cache_state)
        geometry_count = sum(len(layer.geometries) for layer in scene.layers)
        bounds_text = self._scene_bounds_text(scene)
        if self._fetch_started_at is not None:
            elapsed_ms = (time.perf_counter() - self._fetch_started_at) * 1000.0
            self._debug(
                "scene_ready cache=%s elapsed_ms=%.1f layers=%d geometries=%d bounds=%s",
                cache_state,
                elapsed_ms,
                len(scene.layers),
                geometry_count,
                bounds_text,
            )
            self._perf_summary_var.set(
                self._scene_diagnostics_text(
                    scene,
                    elapsed_ms=elapsed_ms,
                    geometry_count=geometry_count,
                    bounds_text=bounds_text,
                    cache_state=cache_state,
                )
            )
        self._schedule_redraw()

    def _scene_diagnostics_text(
        self,
        scene: RenderScene,
        *,
        elapsed_ms: float,
        geometry_count: int,
        bounds_text: str,
        cache_state: str,
    ) -> str:
        diagnostics = scene.diagnostics or {}
        layer_counts = sorted(
            ((layer.name, len(layer.geometries)) for layer in scene.layers if layer.geometries),
            key=lambda item: item[1],
            reverse=True,
        )
        busy_layers = ", ".join(f"{name}:{count}" for name, count in layer_counts[:6]) or "none"
        projection = diagnostics.get("projection", {})
        crs = ""
        if isinstance(projection, dict):
            crs = str(projection.get("render_crs", projection.get("mode", "")))
        quality = str(scene.metadata.get("quality_profile", diagnostics.get("quality_profile", "unknown")))
        source = str(scene.metadata.get("source", "unknown"))
        warnings: list[str] = []
        if geometry_count == 0:
            warnings.append("No drawable geometry for this AOI/layer selection.")
        if int(diagnostics.get("invalid_geometries", 0) or 0) > 0:
            warnings.append(f"Invalid geometries: {diagnostics.get('invalid_geometries')}")
        warning_text = "\nWarnings: " + " ".join(warnings) if warnings else ""
        return (
            "Explain This Map\n"
            f"Source: {source} | Quality: {quality}\n"
            f"CRS: {crs or 'unknown'} | Cache: {cache_state}\n"
            f"Fetch+build: {elapsed_ms:.1f} ms\n"
            f"Layers: {len(scene.layers)} | Geometries: {geometry_count}\n"
            f"Busiest: {busy_layers}\n"
            f"Bounds: {bounds_text}"
            f"{warning_text}"
        )

    def _copy_diagnostics(self) -> None:
        text = self._perf_summary_var.get().strip()
        if not text or text == "No diagnostics yet.":
            messagebox.showinfo("Diagnostics", "No map diagnostics available yet.")
            return
        self._root.clipboard_clear()
        self._root.clipboard_append(text)
        self._status.set_message("Diagnostics copied")

    def _save_diagnostics(self) -> None:
        text = self._perf_summary_var.get().strip()
        if not text or text == "No diagnostics yet.":
            messagebox.showinfo("Diagnostics", "No map diagnostics available yet.")
            return
        target = filedialog.asksaveasfilename(
            title="Save Diagnostics",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if not target:
            return
        Path(target).write_text(text + "\n", encoding="utf-8")
        self._status.set_message("Diagnostics saved")

    def _sync_layer_visibility_to_scene(self) -> None:
        if self._current_scene is None:
            return
        for layer in self._current_scene.layers:
            var = self._layer_visibility_vars.get(layer.name)
            if var is not None:
                layer.style.visible = bool(var.get())

    def _schedule_redraw(self) -> None:
        if self._redraw_job is not None:
            self._root.after_cancel(self._redraw_job)
        self._redraw_job = self._root.after(40, self._redraw_canvas)

    def _redraw_canvas(self) -> None:
        self._redraw_job = None
        if self._current_scene is None:
            return

        width = max(1, self._canvas.winfo_width())
        height = max(1, self._canvas.winfo_height())
        if self._render_inflight:
            return

        self._render_inflight = True
        self._render_request_id += 1
        request_id = self._render_request_id
        self._set_busy("Rendering preview...")

        def _worker() -> None:
            started = time.perf_counter()
            try:
                png = self.renderer.render_preview_png(width, height)
                render_ms = (time.perf_counter() - started) * 1000.0
                self._debug("WORKER: png_bytes=%d, request_id=%d", len(png), request_id)
                self._pending_queue.put(("image", (request_id, width, height, png, render_ms)))
            except Exception as exc:  # noqa: BLE001
                self._pending_queue.put(("error", exc))
            finally:
                self._pending_queue.put(("image", (request_id, width, height, None, None)))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_canvas_png(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) not in {4, 5}:
            return
        if len(payload) == 4:
            request_id, width, height, png = payload
            render_ms = None
        else:
            request_id, width, height, png, render_ms = payload
        if not isinstance(request_id, int):
            return
        if request_id != self._render_request_id:
            return

        # Debug: log received PNG
        if png is not None:
            self._debug("APPLY_CANVAS_PNG: png_bytes=%d, request_id=%d", len(png), request_id)

        # End-of-worker marker
        if png is None:
            self._render_inflight = False
            self._set_idle("Idle")
            return

        self._canvas.delete("placeholder")
        if not png:
            self._canvas.delete("all")
            self._canvas.create_text(
                width // 2,
                height // 2,
                text="Renderer fallback active (Skia unavailable)\nScene generated successfully",
                fill="#555555",
                font=theme.font("lead"),
                justify="center",
            )
            self._status.note("Renderer fallback active")
            return

        self._canvas_image = self._photo_image_from_png(png)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._canvas_image)
        self._canvas.configure(scrollregion=(0, 0, width, height))
        self._status.note(f"Rendered · {getattr(self, '_layer_summary', '')}".rstrip(" ·"))
        png_bytes = len(png)
        if isinstance(render_ms, (int, float)):
            drawn_paths = getattr(self.renderer, "_last_drawn_paths", -1)
            self._debug(
                "render_preview elapsed_ms=%.1f size=%dx%d png_bytes=%d drawn_paths=%s",
                float(render_ms),
                width,
                height,
                png_bytes,
                drawn_paths,
            )
            summary = self._perf_summary_var.get()
            self._perf_summary_var.set(
                f"{summary}\nRender: {float(render_ms):.1f} ms | PNG: {png_bytes / 1024.0:.1f} KiB | Paths: {drawn_paths}"
            )

    def _photo_image_from_png(self, png_bytes: bytes) -> tk.PhotoImage:
        """Robust PNG->PhotoImage loader for macOS Tk variants."""
        # Some Tk/macOS combinations display corrupted pixels with in-memory PNG data.
        # Use file-based loading first for stable preview output.
        if self._canvas_image_tempfile is not None:
            self._canvas_image_tempfile.unlink(missing_ok=True)
            self._canvas_image_tempfile = None
        fd, tmp_path = tempfile.mkstemp(prefix="hipparchus_canvas_", suffix=".png")
        os.close(fd)
        Path(tmp_path).write_bytes(png_bytes)
        Path(tmp_path).chmod(0o600)
        self._canvas_image_tempfile = Path(tmp_path)
        try:
            return tk.PhotoImage(file=str(self._canvas_image_tempfile))
        except tk.TclError:
            # Fallback to in-memory loading for platforms where file mode fails.
            return tk.PhotoImage(data=base64.b64encode(png_bytes).decode("ascii"))

    def _on_visibility_changed(self) -> None:
        if self._current_scene is None:
            return
        for name, var in self._layer_visibility_vars.items():
            self.renderer.set_layer_visibility(name, bool(var.get()))
        self._schedule_redraw()

    # Pan, zoom, turning and drawing an area all live in `ui/map_canvas.py`
    # now. The verbs below are what the menu bar and the toolbar call; each is
    # one line, because the canvas already knows how to do the thing.

    def _zoom_view(self, factor: float) -> None:
        self._map.zoom(factor)

    def _reset_view(self) -> None:
        self._map.reset_view()

    def _rotate_view(self, degrees: float) -> None:
        self._map.turn(degrees)

    def _reset_rotation(self) -> None:
        self._map.north_up()

    def _set_busy(self, label: str) -> None:
        self._status.begin(label)
        if self._toolbar_cancel_button is not None:
            self._toolbar_cancel_button.state(["!disabled"])

    def _set_idle(self, label: str = "Idle") -> None:
        """The label is not used: what the bar says when work ends is whatever
        stands behind the work — a result, or the last report."""
        self._status.end()
        if self._toolbar_cancel_button is not None:
            self._toolbar_cancel_button.state(["disabled"])

    def _scene_bounds_text(self, scene: RenderScene) -> str:
        minx: float | None = None
        miny: float | None = None
        maxx: float | None = None
        maxy: float | None = None
        for layer in scene.layers:
            for geometry in layer.geometries:
                if geometry.is_empty:
                    continue
                gx1, gy1, gx2, gy2 = geometry.bounds
                minx = gx1 if minx is None else min(minx, gx1)
                miny = gy1 if miny is None else min(miny, gy1)
                maxx = gx2 if maxx is None else max(maxx, gx2)
                maxy = gy2 if maxy is None else max(maxy, gy2)
        if minx is None or miny is None or maxx is None or maxy is None:
            return "empty"
        return f"({minx:.5f},{miny:.5f})..({maxx:.5f},{maxy:.5f})"

    def _auto_device_scale(self) -> float:
        try:
            scale = float(self._root.winfo_fpixels("1i")) / 72.0
        except Exception:
            scale = float(getattr(self.renderer, "device_scale", 1.0))
        return max(1.0, min(4.0, scale))
