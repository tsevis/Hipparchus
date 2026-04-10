"""Main Tkinter window with Art-first Beta interactions."""

from __future__ import annotations

import base64
from copy import deepcopy
from dataclasses import dataclass, field, replace
import json
import logging
import os
import platform
from pathlib import Path
import queue
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from hipparchus.application.controller import ApplicationController
from hipparchus.application.presets import ArtisticPreset, QualityMode, default_preset, preset_names
from hipparchus.application.preset_store import PresetStore
from hipparchus.core.config import AppConfig
from hipparchus.data_sources.provider import BBoxQuery
from hipparchus.export.profiles import SVGExportProfile
from hipparchus.export.service import SVGExporter
from hipparchus.plugins.interfaces import LoadedPlugin
from hipparchus.rendering.engine import Renderer
from hipparchus.rendering.models import RenderScene, ViewportState

LOCATION_PRESETS: dict[str, tuple[float, float, float, float]] = {
    "London Center": (-0.15, 51.48, -0.02, 51.56),
    "Athens Center": (23.68, 37.94, 23.80, 38.03),
    "New York Midtown": (-74.02, 40.72, -73.94, 40.79),
    "Paris Core": (2.26, 48.83, 2.38, 48.89),
    "Tokyo Central": (139.68, 35.65, 139.79, 35.73),
}

LEFT_SIDEBAR_WIDTH = 360
RIGHT_SIDEBAR_WIDTH = 300
SIDEBAR_CONTENT_PADDING = 10

THEME_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#f2f2f2",
        "panel": "#f7f7f7",
        "panel_alt": "#ffffff",
        "text": "#151515",
        "muted": "#555555",
        "border": "#d0d0d0",
        "button": "#ffffff",
        "button_active": "#e7eef8",
        "field": "#ffffff",
        "field_text": "#151515",
        "select": "#d7e8ff",
        "select_text": "#111111",
        "canvas_bg": "#f5f5f5",
        "canvas_border": "#d0d0d0",
    },
    "dark": {
        "bg": "#17191f",
        "panel": "#20232b",
        "panel_alt": "#252936",
        "text": "#f2f5f8",
        "muted": "#b7beca",
        "border": "#3d4350",
        "button": "#2f3543",
        "button_active": "#3c465a",
        "field": "#11141b",
        "field_text": "#f8fafc",
        "select": "#44648f",
        "select_text": "#ffffff",
        "canvas_bg": "#f3f3f1",
        "canvas_border": "#636b78",
    },
}


@dataclass
class MainWindow:
    """Primary application window with sidebar layout."""

    config: AppConfig
    loaded_plugins: list[LoadedPlugin]
    controller: ApplicationController
    renderer: Renderer
    default_preset: ArtisticPreset = field(default_factory=default_preset)

    def __post_init__(self) -> None:
        self._root = tk.Tk()
        self._theme_mode = self.config.theme_mode
        self._current_scene: RenderScene | None = None
        self._canvas_image: tk.PhotoImage | None = None
        self._canvas_image_tempfile: Path | None = None
        self._pending_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._drag_last_xy: tuple[int, int] | None = None
        self._redraw_job: str | None = None
        self._render_request_id = 0
        self._render_inflight = False
        self._busy_counter = 0
        self._scroll_x = 0.5
        self._scroll_y = 0.5
        self._scroll_step = 0.06
        self._scroll_span_pixels = 1800.0
        self._fetch_started_at: float | None = None
        self._debug_enabled_var = tk.BooleanVar(value=True)
        self._perf_summary_var = tk.StringVar(value="No diagnostics yet.")
        self._debug_log_file = self.config.cache_dir / "hipparchus_debug.log"

        self._layer_visibility_vars: dict[str, tk.BooleanVar] = {}
        self._preset_store = PresetStore(self.config.presets_file)
        self._custom_presets = self._load_custom_presets()
        self._preset_options = sorted({*preset_names(), *self._custom_presets.keys()})
        self._status_var = tk.StringVar(value="Ready")
        self._cache_status_var = tk.StringVar(value="Cache: n/a")
        self._progress_label_var = tk.StringVar(value="Idle")
        self._quality_var = tk.StringVar(value="preview")
        self._preset_var = tk.StringVar(value=self.default_preset.name)
        self._location_preset_var = tk.StringVar(value="London Center")
        self._location_query_var = tk.StringVar(value="")
        self._new_preset_name_var = tk.StringVar(value="")
        # Get Overpass settings from data source manager
        overpass_settings = self.controller.data_source_manager.get_overpass_settings()
        self._provider_endpoint_var = tk.StringVar(value=overpass_settings["endpoint"])
        self._provider_rps_var = tk.DoubleVar(value=overpass_settings["requests_per_second"])
        self._provider_timeout_var = tk.DoubleVar(value=overpass_settings["timeout_seconds"])
        device_scale = getattr(self.renderer, "device_scale", 2.0)
        self._device_scale_var = tk.DoubleVar(value=float(device_scale))

        self._aoi_vars = {
            "min_lon": tk.StringVar(value="-0.15"),
            "min_lat": tk.StringVar(value="51.48"),
            "max_lon": tk.StringVar(value="-0.02"),
            "max_lat": tk.StringVar(value="51.56"),
        }

        self._logger = self._configure_diagnostics_logger()

        self._build_window()
        self._build_layout()
        self._apply_theme()
        self._root.after(50, self._drain_callback_queue)

    def _create_scrollable_frame(self, parent: tk.Widget, width: int, *, padding: int = SIDEBAR_CONTENT_PADDING) -> tuple[ttk.Frame, tk.Canvas, ttk.Frame]:
        """Create a fixed-width scrollable frame."""
        container = ttk.Frame(parent, width=width)
        container.grid_propagate(False)
        container.grid_rowconfigure(0, weight=1)
        container.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(container, highlightthickness=0, width=width - 16)
        canvas.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        canvas.configure(yscrollcommand=scrollbar.set)

        content = ttk.Frame(canvas, padding=padding)
        content_window = canvas.create_window((0, 0), window=content, anchor="nw")

        def _sync_scroll_region(_: tk.Event | None = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_content_width(_: tk.Event | None = None) -> None:
            content_width = max(1, canvas.winfo_width())
            canvas.itemconfigure(content_window, width=content_width)

        content.bind("<Configure>", _sync_scroll_region)
        canvas.bind("<Configure>", _sync_content_width)
        return container, canvas, content

    def _populate_checkbutton_grid(
        self,
        parent: ttk.Frame,
        *,
        items: list[tuple[str, str]],
        columns: int,
        default: bool,
    ) -> None:
        grid = ttk.Frame(parent)
        grid.pack(fill="x", pady=(0, 2))
        for column in range(columns):
            grid.grid_columnconfigure(column, weight=1)
        for index, (layer_id, display_name) in enumerate(items):
            var = tk.BooleanVar(value=default)
            self._layer_visibility_vars[layer_id] = var
            ttk.Checkbutton(
                grid,
                text=display_name,
                variable=var,
                command=self._on_visibility_changed,
            ).grid(row=index // columns, column=index % columns, sticky="w", padx=(0, 8), pady=1)

    def _build_window(self) -> None:
        self._root.title(self.config.app_name)
        self._root.geometry(f"{self.config.default_width}x{self.config.default_height}")
        self._root.minsize(1400, 980)

        style = ttk.Style(master=self._root)
        self._setup_platform_theme(style)

    def _setup_platform_theme(self, style: ttk.Style) -> None:
        """Use native Aqua on macOS and styleable fallbacks elsewhere."""
        if platform.system() == "Darwin":
            try:
                style.theme_use("aqua")
            except tk.TclError:
                pass
            return

        preferred = ("vista", "clam", "alt", "default") if platform.system() == "Windows" else ("clam", "alt", "default")
        available = set(style.theme_names())
        for theme_name in preferred:
            if theme_name in available:
                try:
                    style.theme_use(theme_name)
                    return
                except tk.TclError:
                    continue

    def _configure_diagnostics_logger(self) -> logging.Logger:
        logger = logging.getLogger("hipparchus.perf")
        logger.setLevel(logging.INFO)
        self._debug_log_file.parent.mkdir(parents=True, exist_ok=True)
        target = str(self._debug_log_file.resolve())

        already_configured = any(
            isinstance(handler, logging.FileHandler) and Path(handler.baseFilename).resolve() == self._debug_log_file.resolve()
            for handler in logger.handlers
        )
        if not already_configured:
            file_handler = logging.FileHandler(target, encoding="utf-8")
            file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
            logger.addHandler(file_handler)
        return logger

    def _debug(self, message: str, *args: object) -> None:
        if not self._debug_enabled_var.get():
            return
        self._logger.info(message, *args)

    def _build_layout(self) -> None:
        root = self._root
        root.grid_rowconfigure(0, weight=0)  # Top bar - fixed height
        root.grid_rowconfigure(1, weight=1)  # Main content - expands
        root.grid_columnconfigure(0, weight=0, minsize=LEFT_SIDEBAR_WIDTH)  # Left sidebar - fixed width
        root.grid_columnconfigure(1, weight=1)  # Center canvas - expands
        root.grid_columnconfigure(2, weight=0, minsize=RIGHT_SIDEBAR_WIDTH)  # Right sidebar - fixed width

        top = ttk.Frame(root, padding=(14, 10, 14, 10))
        top.grid(row=0, column=0, columnspan=3, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=0)

        ttk.Label(top, text="Hipparchus", font=("SF Pro Text", 15, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Button(top, text="Dark/Light", command=self._toggle_theme).grid(row=0, column=1, sticky="e")

        # Controls using pack for reliable layout
        controls = ttk.Frame(top)
        controls.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # Left side - Location and Fetch
        ttk.Label(controls, text="Location:").pack(side="left", padx=(0, 4))
        self._location_entry = ttk.Entry(controls, textvariable=self._location_query_var, width=18)
        self._location_entry.pack(side="left", padx=(0, 6))
        self._location_entry.bind("<Return>", lambda _e: self._on_location_lookup_clicked())
        ttk.Button(controls, text="Find", command=self._on_location_lookup_clicked).pack(side="left", padx=(0, 4))
        ttk.Button(controls, text="Fetch", command=self._on_fetch_clicked).pack(side="left", padx=(0, 12))

        # Middle - Preset
        ttk.Label(controls, text="Preset:").pack(side="left", padx=(0, 4))
        self._preset_menu = ttk.OptionMenu(controls, self._preset_var, self._preset_var.get(), *self._preset_options)
        self._preset_menu.pack(side="left", padx=(0, 8))

        # Middle - Quality
        ttk.Label(controls, text="Quality:").pack(side="left", padx=(0, 4))
        self._quality_menu = ttk.OptionMenu(controls, self._quality_var, "preview", "preview", "export")
        self._quality_menu.pack(side="left", padx=(0, 8))

        # Right side - Export
        ttk.Button(controls, text="Export SVG", command=self._on_export_clicked).pack(side="right")

        left_outer, self._left_sidebar_canvas, left = self._create_scrollable_frame(root, LEFT_SIDEBAR_WIDTH)
        left_outer.grid(row=1, column=0, sticky="ns")

        center = ttk.Frame(root, padding=12)
        center.grid(row=1, column=1, sticky="nsew")
        center.grid_rowconfigure(1, weight=1)
        center.grid_columnconfigure(0, weight=1)

        right_outer, self._right_sidebar_canvas, right = self._create_scrollable_frame(root, RIGHT_SIDEBAR_WIDTH)
        right_outer.grid(row=1, column=2, sticky="ns")

        self._build_left_sidebar(left)
        self._build_center_canvas(center)
        self._build_right_sidebar(right)

        statusbar = ttk.Frame(root, padding=(12, 6, 12, 8))
        statusbar.grid(row=2, column=0, columnspan=3, sticky="ew")
        statusbar.grid_columnconfigure(0, weight=1)
        ttk.Label(statusbar, textvariable=self._status_var).grid(row=0, column=0, sticky="w")
        ttk.Label(statusbar, textvariable=self._cache_status_var).grid(row=0, column=1, sticky="e")

    def _build_left_sidebar(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Area", font=("SF Pro Text", 12, "bold")).pack(anchor="w", pady=(0, 8))
        ttk.OptionMenu(parent, self._location_preset_var, self._location_preset_var.get(), *LOCATION_PRESETS.keys()).pack(
            fill="x", pady=(0, 6)
        )
        ttk.Button(parent, text="Use Preset AOI", command=self._apply_location_preset).pack(fill="x", pady=(0, 8))

        # Coordinates in compact 2x2 grid
        ttk.Label(parent, text="Coordinates", font=("SF Pro Text", 10, "bold")).pack(anchor="w", pady=(0, 4))
        coord_frame = ttk.Frame(parent)
        coord_frame.pack(fill="x", pady=2)

        # Row 1: Min Lon, Min Lat
        ttk.Label(coord_frame, text="Min Lon", width=7).grid(row=0, column=0, sticky="w")
        ttk.Entry(coord_frame, textvariable=self._aoi_vars["min_lon"], width=9).grid(row=0, column=1, sticky="ew", padx=(2, 6))
        ttk.Label(coord_frame, text="Min Lat", width=7).grid(row=0, column=2, sticky="w")
        ttk.Entry(coord_frame, textvariable=self._aoi_vars["min_lat"], width=9).grid(row=0, column=3, sticky="ew", padx=(2, 0))

        # Row 2: Max Lon, Max Lat
        ttk.Label(coord_frame, text="Max Lon", width=7).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Entry(coord_frame, textvariable=self._aoi_vars["max_lon"], width=9).grid(row=1, column=1, sticky="ew", padx=(2, 6), pady=(4, 0))
        ttk.Label(coord_frame, text="Max Lat", width=7).grid(row=1, column=2, sticky="w", pady=(4, 0))
        ttk.Entry(coord_frame, textvariable=self._aoi_vars["max_lat"], width=9).grid(row=1, column=3, sticky="ew", padx=(2, 0), pady=(4, 0))

        # Compact navigation arrows
        nav = ttk.Frame(parent)
        nav.pack(fill="x", pady=(8, 6))
        for column in range(4):
            nav.grid_columnconfigure(column, weight=1)

        ttk.Button(nav, text="-", width=3, command=lambda: self._scale_aoi(1.15)).grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        ttk.Button(nav, text="▲", width=3, command=lambda: self._nudge_aoi(0.0, 0.25)).grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        ttk.Button(nav, text="+", width=3, command=lambda: self._scale_aoi(0.85)).grid(row=0, column=2, padx=2, pady=2, sticky="ew")
        ttk.Button(nav, text="Reset", width=5, command=self._apply_location_preset).grid(row=0, column=3, padx=2, pady=2, sticky="ew")
        ttk.Button(nav, text="◀", width=3, command=lambda: self._nudge_aoi(-0.25, 0.0)).grid(row=1, column=0, padx=2, pady=2, sticky="ew")
        ttk.Button(nav, text="▼", width=3, command=lambda: self._nudge_aoi(0.0, -0.25)).grid(row=1, column=1, padx=2, pady=2, sticky="ew")
        ttk.Button(nav, text="▶", width=3, command=lambda: self._nudge_aoi(0.25, 0.0)).grid(row=1, column=2, padx=2, pady=2, sticky="ew")
        ttk.Button(nav, text="Fetch", width=5, command=self._on_fetch_clicked).grid(row=1, column=3, padx=2, pady=2, sticky="ew")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(parent, text="View Controls", font=("SF Pro Text", 11, "bold")).pack(anchor="w", pady=(0, 6))

        # Zoom controls
        zoom_frame = ttk.Frame(parent)
        zoom_frame.pack(fill="x", pady=(0, 8))
        for column in range(3):
            zoom_frame.grid_columnconfigure(column, weight=1)
        ttk.Button(zoom_frame, text="Zoom In", command=lambda: self._zoom_view(1.5)).grid(row=0, column=0, padx=(0, 4), sticky="ew")
        ttk.Button(zoom_frame, text="Zoom Out", command=lambda: self._zoom_view(0.67)).grid(row=0, column=1, padx=2, sticky="ew")
        ttk.Button(zoom_frame, text="Reset", command=self._reset_view).grid(row=0, column=2, padx=(4, 0), sticky="ew")

        # Rotation controls
        rotation_frame = ttk.Frame(parent)
        rotation_frame.pack(fill="x", pady=(0, 8))
        rotation_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(rotation_frame, text="Rotation:").grid(row=0, column=0, sticky="w", padx=(0, 4))
        self._rotation_var = tk.DoubleVar(value=0.0)
        rotation_scale = ttk.Scale(rotation_frame, from_=-180, to=180, variable=self._rotation_var, orient="horizontal", command=self._on_rotation_changed)
        rotation_scale.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        ttk.Button(rotation_frame, text="↺", width=3, command=lambda: self._rotate_view(-15)).grid(row=0, column=2, padx=(0, 2))
        ttk.Button(rotation_frame, text="↻", width=3, command=lambda: self._rotate_view(15)).grid(row=0, column=3, padx=(0, 2))
        ttk.Button(rotation_frame, text="0°", width=3, command=self._reset_rotation).grid(row=0, column=4)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(parent, text="Layers", font=("SF Pro Text", 12, "bold")).pack(anchor="w", pady=(0, 6))

        # Natural/Area layers
        area_layers = [
            ("coastline", "Coastline/Sea"),
            ("water", "Water/Lakes"),
            ("fields", "Fields/Farmland"),
            ("forests", "Forests/Woods"),
            ("natural", "Natural Areas"),
            ("parks", "Parks/Gardens"),
        ]
        self._populate_checkbutton_grid(parent, items=area_layers, columns=2, default=True)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(8, 4))
        ttk.Label(parent, text="Roads", font=("SF Pro Text", 10, "bold")).pack(anchor="w", pady=(0, 4))

        # Road layers
        road_layers = [
            ("roads_motorway", "Motorways"),
            ("roads_trunk", "Trunk Roads"),
            ("roads_primary", "Primary Roads"),
            ("roads_secondary", "Secondary Roads"),
            ("roads_tertiary", "Tertiary Roads"),
            ("roads_residential", "Residential"),
            ("roads_service", "Service Roads"),
        ]
        self._populate_checkbutton_grid(parent, items=road_layers, columns=2, default=True)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(8, 4))
        ttk.Label(parent, text="Structures", font=("SF Pro Text", 10, "bold")).pack(anchor="w", pady=(0, 4))

        # Structure layers
        structure_layers = [
            ("buildings", "Buildings"),
            ("railways", "Railways"),
        ]
        self._populate_checkbutton_grid(parent, items=structure_layers, columns=2, default=True)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(8, 4))
        ttk.Label(parent, text="Labels", font=("SF Pro Text", 10, "bold")).pack(anchor="w", pady=(0, 4))

        # Label layers
        label_layers = [
            ("places", "Place Names (cities, towns)"),
            ("shops", "Shops & Businesses"),
            ("amenities", "Amenities (cafes, etc.)"),
        ]
        self._populate_checkbutton_grid(parent, items=label_layers, columns=1, default=True)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(8, 4))
        ttk.Label(parent, text="Derived Layers", font=("SF Pro Text", 10, "bold")).pack(anchor="w", pady=(0, 4))

        # Derived layers
        derived_layers = [
            ("voronoi_cells", "Voronoi Cells"),
            ("delaunay_mesh", "Delaunay Mesh"),
            ("hex_grid", "Hex Grid"),
            ("circle_packing", "Circle Packing"),
        ]
        self._populate_checkbutton_grid(parent, items=derived_layers, columns=2, default=False)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=(10, 6))
        ttk.Label(parent, textvariable=self._progress_label_var).pack(anchor="w")
        self._progress = ttk.Progressbar(parent, mode="indeterminate")
        self._progress.pack(fill="x", pady=(4, 0))

    def _build_center_canvas(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Map Preview", font=("SF Pro Text", 12, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        canvas_wrap = ttk.Frame(parent)
        canvas_wrap.grid(row=1, column=0, sticky="nsew")
        canvas_wrap.grid_rowconfigure(0, weight=1)
        canvas_wrap.grid_columnconfigure(0, weight=1)

        self._canvas = tk.Canvas(canvas_wrap, background="#f5f5f5", highlightthickness=1, highlightbackground="#d0d0d0")
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._v_scroll = ttk.Scrollbar(canvas_wrap, orient="vertical", command=self._on_vscroll)
        self._v_scroll.grid(row=0, column=1, sticky="ns")
        self._h_scroll = ttk.Scrollbar(canvas_wrap, orient="horizontal", command=self._on_hscroll)
        self._h_scroll.grid(row=1, column=0, sticky="ew")
        self._sync_scrollbars()
        self._canvas.create_text(
            450,
            280,
            text="Fetch an area to render artistic map structures",
            fill="#555555",
            font=("SF Pro Text", 13),
            justify="center",
            tags=("placeholder",),
        )

        self._canvas.bind("<ButtonPress-1>", self._on_drag_start)
        self._canvas.bind("<B1-Motion>", self._on_drag_move)
        self._canvas.bind("<ButtonRelease-1>", self._on_drag_end)
        self._canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self._canvas.bind("<Button-4>", self._on_mouse_wheel_linux)
        self._canvas.bind("<Button-5>", self._on_mouse_wheel_linux)
        # Keyboard shortcuts for zoom
        self._canvas.bind("<plus>", lambda e: self._zoom_view(1.5))
        self._canvas.bind("<minus>", lambda e: self._zoom_view(0.67))
        self._canvas.bind("<KP_Add>", lambda e: self._zoom_view(1.5))
        self._canvas.bind("<KP_Subtract>", lambda e: self._zoom_view(0.67))
        self._canvas.bind("<0>", lambda e: self._reset_view())
        self._canvas.bind("<KeyPress-r>", lambda e: self._reset_view())
        # Focus the canvas so it can receive keyboard events
        self._canvas.focus_set()

    def _build_right_sidebar(self, parent: ttk.Frame) -> None:
        self._build_settings_tab(parent)

    def _on_fetch_clicked(self) -> None:
        try:
            # Validate and parse coordinates
            min_lon_str = self._aoi_vars["min_lon"].get().strip()
            min_lat_str = self._aoi_vars["min_lat"].get().strip()
            max_lon_str = self._aoi_vars["max_lon"].get().strip()
            max_lat_str = self._aoi_vars["max_lat"].get().strip()

            if not all([min_lon_str, min_lat_str, max_lon_str, max_lat_str]):
                messagebox.showerror("Invalid AOI", "Please enter all coordinate values.")
                return

            min_lon = float(min_lon_str)
            min_lat = float(min_lat_str)
            max_lon = float(max_lon_str)
            max_lat = float(max_lat_str)

            # Validate coordinate ranges
            if not (-180 <= min_lon <= 180 and -180 <= max_lon <= 180):
                messagebox.showerror("Invalid AOI", "Longitude must be between -180 and 180.")
                return
            if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
                messagebox.showerror("Invalid AOI", "Latitude must be between -90 and 90.")
                return
            if min_lon >= max_lon:
                messagebox.showerror("Invalid AOI", "Min Lon must be less than Max Lon.")
                return
            if min_lat >= max_lat:
                messagebox.showerror("Invalid AOI", "Min Lat must be less than Max Lat.")
                return

            aoi = BBoxQuery(
                min_lon=min_lon,
                min_lat=min_lat,
                max_lon=max_lon,
                max_lat=max_lat,
                layers=tuple(self._active_base_layers()),
            )
        except ValueError:
            messagebox.showerror("Invalid AOI", "Coordinates must be valid numbers.")
            return

        preset = self._resolve_selected_preset()
        preset_profile = preset.geometry_profile

        # Keep preview responsive for very large AOIs.
        span_lon = abs(aoi.max_lon - aoi.min_lon)
        span_lat = abs(aoi.max_lat - aoi.min_lat)
        area_deg2 = span_lon * span_lat
        if area_deg2 > 0.02:
            preset_profile = replace(
                preset_profile,
                max_on_screen_features_per_layer=min(preset_profile.max_on_screen_features_per_layer, 1500),
            )
            self._status_var.set("Large area detected: applying preview sampling")
        else:
            self._status_var.set("Fetching map data...")
        self._set_busy("Fetching map data...")
        self._fetch_started_at = time.perf_counter()
        self._debug(
            "fetch_start aoi=(%.5f,%.5f,%.5f,%.5f) layers=%s preset=%s quality=%s",
            aoi.min_lon,
            aoi.min_lat,
            aoi.max_lon,
            aoi.max_lat,
            ",".join(aoi.layers),
            preset.name,
            self._quality_var.get(),
        )

        self.controller.run_fetch_and_render(
            aoi=aoi,
            layers=tuple(self._active_base_layers()),
            style_profile=preset.style_profile,
            quality_mode=self._quality_var.get() if self._quality_var.get() in {"preview", "export"} else "preview",
            geometry_profile=preset_profile,
            on_scene=self._queue_scene,
            on_error=self._queue_error,
        )

    def _resolve_selected_preset(self) -> ArtisticPreset:
        selected = self._preset_var.get().strip()
        custom = self._custom_presets.get(selected)
        if custom is not None:
            return custom
        return default_preset(selected)

    def _load_custom_presets(self) -> dict[str, ArtisticPreset]:
        try:
            return self._preset_store.load()
        except Exception as exc:  # noqa: BLE001
            self._status_var.set(f"Could not load presets: {exc}")
            return {}

    def _build_settings_tab(self, parent: ttk.Frame) -> None:
        # Label Settings Section
        ttk.Label(parent, text="Label Settings", font=("SF Pro Text", 11, "bold")).pack(anchor="w", pady=(0, 6))

        # Font family
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Font Family", width=13).pack(side="left")
        self._label_font_var = tk.StringVar(value="Arial")
        font_combo = ttk.Combobox(row, textvariable=self._label_font_var, values=["Arial", "Helvetica", "Times", "Courier", "Verdana"], width=15)
        font_combo.pack(side="left")

        # Font size
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Font Size", width=13).pack(side="left")
        self._label_size_var = tk.IntVar(value=12)
        ttk.Spinbox(row, from_=8, to=24, textvariable=self._label_size_var, width=10).pack(side="left")

        # Label visibility toggles
        ttk.Label(parent, text="Show Labels:", font=("SF Pro Text", 10)).pack(anchor="w", pady=(6, 2))
        self._show_place_names_var = tk.BooleanVar(value=True)
        self._show_street_names_var = tk.BooleanVar(value=True)
        self._show_shop_names_var = tk.BooleanVar(value=True)
        self._show_amenity_names_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(parent, text="Place Names (cities, towns)", variable=self._show_place_names_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(parent, text="Street Names", variable=self._show_street_names_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(parent, text="Shop/Business Names", variable=self._show_shop_names_var).pack(anchor="w", pady=1)
        ttk.Checkbutton(parent, text="Amenity Names (cafes, etc.)", variable=self._show_amenity_names_var).pack(anchor="w", pady=1)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(parent, text="Renderer", font=("SF Pro Text", 11, "bold")).pack(anchor="w", pady=(0, 6))

        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Device Scale", width=13).pack(side="left")
        ttk.Entry(row, textvariable=self._device_scale_var, width=10).pack(side="left")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(parent, text="Provider", font=("SF Pro Text", 11, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Label(parent, text="Online-only mode using Overpass API", font=("SF Pro Text", 9)).pack(anchor="w", pady=(0, 4))

        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Endpoint", width=13).pack(side="left")
        ttk.Entry(row, textvariable=self._provider_endpoint_var).pack(side="left", fill="x", expand=True)

        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Req/sec", width=13).pack(side="left")
        ttk.Entry(row, textvariable=self._provider_rps_var, width=10).pack(side="left")

        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Timeout (s)", width=13).pack(side="left")
        ttk.Entry(row, textvariable=self._provider_timeout_var, width=10).pack(side="left")

        ttk.Button(parent, text="Apply Settings", command=self._apply_runtime_settings).pack(fill="x", pady=(8, 0))

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(parent, text="Presets", font=("SF Pro Text", 11, "bold")).pack(anchor="w", pady=(0, 6))

        row = ttk.Frame(parent)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="New Name", width=13).pack(side="left")
        ttk.Entry(row, textvariable=self._new_preset_name_var).pack(side="left", fill="x", expand=True)
        ttk.Button(parent, text="Add Current To Presets", command=self._save_current_as_preset).pack(fill="x", pady=(8, 0))

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(parent, text=f"Cache: {self.config.cache_dir}").pack(anchor="w")

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=10)
        ttk.Label(parent, text="Diagnostics", font=("SF Pro Text", 11, "bold")).pack(anchor="w", pady=(0, 6))
        ttk.Checkbutton(parent, text="Enable diagnostics logging", variable=self._debug_enabled_var).pack(anchor="w", pady=(0, 4))
        ttk.Label(parent, text=f"Log: {self._debug_log_file}").pack(anchor="w")
        ttk.Label(parent, textvariable=self._perf_summary_var, justify="left", wraplength=280).pack(anchor="w", pady=(4, 0))

    def _apply_runtime_settings(self) -> None:
        endpoint = self._provider_endpoint_var.get().strip()
        rps = max(0.05, float(self._provider_rps_var.get()))
        timeout_seconds = max(5.0, float(self._provider_timeout_var.get()))
        device_scale = max(1.0, min(4.0, float(self._device_scale_var.get())))
        label_font_size = max(6, min(24, int(self._label_size_var.get())))

        self.controller.data_source_manager.set_overpass_settings(
            endpoint=endpoint,
            timeout_seconds=timeout_seconds,
            requests_per_second=rps,
        )
        if hasattr(self.renderer, "device_scale"):
            setattr(self.renderer, "device_scale", device_scale)
        if hasattr(self.renderer, "set_label_font_size"):
            self.renderer.set_label_font_size(label_font_size)

        self._status_var.set("Settings applied - Using Overpass data")

    def _save_current_as_preset(self) -> None:
        name = self._new_preset_name_var.get().strip()
        if not name:
            messagebox.showinfo("Preset name", "Please enter a preset name.")
            return
        source = self._resolve_selected_preset()
        self._custom_presets[name] = ArtisticPreset(
            name=name,
            geometry_profile=source.geometry_profile,
            style_profile=deepcopy(source.style_profile),
        )
        try:
            self._preset_store.save(self._custom_presets)
        except OSError as exc:
            messagebox.showerror("Preset save failed", f"Could not save preset file:\n{exc}")
            return
        if name not in self._preset_options:
            self._preset_options.append(name)
            self._preset_options.sort()
            self._refresh_preset_menu()
        self._preset_var.set(name)
        self._new_preset_name_var.set("")
        self._status_var.set(f"Preset saved: {name}")

    def _refresh_preset_menu(self) -> None:
        menu = self._preset_menu["menu"]
        menu.delete(0, "end")
        for name in self._preset_options:
            menu.add_command(label=name, command=tk._setit(self._preset_var, name))

    def _on_location_lookup_clicked(self) -> None:
        query = self._location_query_var.get().strip()
        if not query:
            messagebox.showinfo("Location", "Type a location in plain English first.")
            return

        self._set_busy("Finding coordinates...")

        def _worker() -> None:
            try:
                aoi = self._lookup_location_aoi(query)
                self._pending_queue.put(("aoi", aoi))
            except Exception as exc:  # noqa: BLE001
                self._pending_queue.put(("error", exc))

        threading.Thread(target=_worker, daemon=True).start()

    def _lookup_location_aoi(self, query: str) -> tuple[float, float, float, float]:
        t0 = time.perf_counter()
        params = urlencode({"q": query, "format": "jsonv2", "limit": 1})
        request = Request(
            f"https://nominatim.openstreetmap.org/search?{params}",
            headers={"User-Agent": "Hipparchus/0.1"},
        )
        try:
            with urlopen(request, timeout=10.0) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise RuntimeError(f"Location lookup failed: {exc}")

        self._debug("location_lookup query=%s elapsed_ms=%.1f", query, (time.perf_counter() - t0) * 1000.0)
        if not payload:
            raise RuntimeError(f"No match found for '{query}'")
        bbox = payload[0].get("boundingbox")
        if not bbox or len(bbox) != 4:
            raise RuntimeError("Location lookup did not return a bounding box")

        min_lat = float(bbox[0])
        max_lat = float(bbox[1])
        min_lon = float(bbox[2])
        max_lon = float(bbox[3])
        return (min_lon, min_lat, max_lon, max_lat)

    def _apply_location_preset(self) -> None:
        preset = LOCATION_PRESETS.get(self._location_preset_var.get())
        if preset is None:
            return
        min_lon, min_lat, max_lon, max_lat = preset
        self._aoi_vars["min_lon"].set(f"{min_lon:.5f}")
        self._aoi_vars["min_lat"].set(f"{min_lat:.5f}")
        self._aoi_vars["max_lon"].set(f"{max_lon:.5f}")
        self._aoi_vars["max_lat"].set(f"{max_lat:.5f}")

    def _nudge_aoi(self, x_ratio: float, y_ratio: float) -> None:
        min_lon, min_lat, max_lon, max_lat = self._current_aoi_values()
        span_lon = max_lon - min_lon
        span_lat = max_lat - min_lat
        dx = span_lon * x_ratio
        dy = span_lat * y_ratio
        self._set_aoi(min_lon + dx, min_lat + dy, max_lon + dx, max_lat + dy)

    def _scale_aoi(self, factor: float) -> None:
        min_lon, min_lat, max_lon, max_lat = self._current_aoi_values()
        center_lon = (min_lon + max_lon) * 0.5
        center_lat = (min_lat + max_lat) * 0.5
        half_lon = max(0.0005, (max_lon - min_lon) * 0.5 * factor)
        half_lat = max(0.0005, (max_lat - min_lat) * 0.5 * factor)
        self._set_aoi(center_lon - half_lon, center_lat - half_lat, center_lon + half_lon, center_lat + half_lat)

    def _current_aoi_values(self) -> tuple[float, float, float, float]:
        return (
            float(self._aoi_vars["min_lon"].get()),
            float(self._aoi_vars["min_lat"].get()),
            float(self._aoi_vars["max_lon"].get()),
            float(self._aoi_vars["max_lat"].get()),
        )

    def _set_aoi(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> None:
        self._aoi_vars["min_lon"].set(f"{min_lon:.5f}")
        self._aoi_vars["min_lat"].set(f"{min_lat:.5f}")
        self._aoi_vars["max_lon"].set(f"{max_lon:.5f}")
        self._aoi_vars["max_lat"].set(f"{max_lat:.5f}")

    def _active_base_layers(self) -> list[str]:
        # All possible base layers including road types, natural features, places, and detailed info
        base = [
            "roads_motorway", "roads_trunk", "roads_primary", "roads_secondary",
            "roads_tertiary", "roads_residential", "roads_service", "roads_other",
            "roads", "buildings", "water", "parks", "railways",
            "forests", "fields", "natural", "coastline",
            "places", "shops", "amenities", "landuse", "barriers", "power"
        ]
        return [name for name in base if self._layer_visibility_vars.get(name, tk.BooleanVar(value=True)).get()]

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
                elif kind == "aoi":
                    self._apply_location_aoi(payload)
                elif kind == "image":
                    self._apply_canvas_png(payload)
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
                    self._status_var.set(f"Error: {error_msg[:80]}")
                    self._set_idle("Error")
        except queue.Empty:
            pass

        self._root.after(60, self._drain_callback_queue)

    def _apply_scene(self, scene: RenderScene, cache_state: str) -> None:
        self._current_scene = scene
        self._sync_layer_visibility_to_scene()
        self.renderer.set_scene(scene)
        self.renderer.set_viewport(ViewportState())
        self._scroll_x = 0.5
        self._scroll_y = 0.5
        self._sync_scrollbars()
        self._status_var.set("Rendering preview...")
        self._cache_status_var.set(f"Cache: {cache_state}")
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
                "Fetch+build: "
                f"{elapsed_ms:.1f} ms\nLayers: {len(scene.layers)} | Geometries: {geometry_count}\nBounds: {bounds_text}\nCache: {cache_state}"
            )
        self._schedule_redraw()

    def _apply_location_aoi(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 4:
            self._set_idle("Lookup failed")
            return
        min_lon, min_lat, max_lon, max_lat = payload
        self._set_aoi(float(min_lon), float(min_lat), float(max_lon), float(max_lat))
        self._status_var.set("Coordinates updated from location")
        self._set_idle("Location ready")

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
        self._status_var.set("Rendering preview...")
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
                font=("SF Pro Text", 13),
                justify="center",
            )
            self._status_var.set("Rendered")
            self._set_idle("Renderer fallback")
            return

        self._canvas_image = self._photo_image_from_png(png)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor="nw", image=self._canvas_image)
        self._canvas.configure(scrollregion=(0, 0, width, height))
        self._status_var.set("Rendered")
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
        self._set_idle("Idle")

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

    def _on_mouse_wheel(self, event: tk.Event) -> None:
        factor = 1.12 if event.delta > 0 else 0.89
        self.renderer.zoom(factor)
        self._schedule_redraw()

    def _on_mouse_wheel_linux(self, event: tk.Event) -> None:
        factor = 1.12 if getattr(event, "num", 0) == 4 else 0.89
        self.renderer.zoom(factor)
        self._schedule_redraw()

    def _zoom_view(self, factor: float) -> None:
        """Zoom in or out by the given factor."""
        self.renderer.zoom(factor)
        self._schedule_redraw()
        # Ensure canvas has focus for keyboard shortcuts
        self._canvas.focus_set()

    def _reset_view(self) -> None:
        """Reset zoom and pan to default."""
        from hipparchus.rendering.models import ViewportState
        self.renderer.set_viewport(ViewportState())
        self._scroll_x = 0.5
        self._scroll_y = 0.5
        self._rotation_var.set(0.0)
        self._sync_scrollbars()
        self._schedule_redraw()
        # Ensure canvas has focus for keyboard shortcuts
        self._canvas.focus_set()

    def _rotate_view(self, degrees: float) -> None:
        """Rotate view by given degrees."""
        self.renderer.rotate(degrees)
        new_rotation = (self._rotation_var.get() + degrees) % 360
        if new_rotation > 180:
            new_rotation -= 360
        self._rotation_var.set(new_rotation)
        self._schedule_redraw()
        self._canvas.focus_set()

    def _reset_rotation(self) -> None:
        """Reset rotation to 0 degrees."""
        self.renderer.set_rotation(0.0)
        self._rotation_var.set(0.0)
        self._schedule_redraw()
        self._canvas.focus_set()

    def _on_rotation_changed(self, value: str) -> None:
        """Handle rotation slider change."""
        try:
            degrees = float(value)
            self.renderer.set_rotation(degrees)
            self._schedule_redraw()
        except ValueError:
            pass

    def _on_drag_start(self, event: tk.Event) -> None:
        self._drag_last_xy = (event.x, event.y)
        self._canvas.configure(cursor="fleur")

    def _on_drag_move(self, event: tk.Event) -> None:
        if self._drag_last_xy is None:
            return
        lx, ly = self._drag_last_xy
        dx = event.x - lx
        dy = event.y - ly
        self._drag_last_xy = (event.x, event.y)
        self.renderer.pan(dx, dy)
        self._update_scroll_state(dx=dx, dy=dy)
        self._schedule_redraw()

    def _on_drag_end(self, _: tk.Event) -> None:
        self._drag_last_xy = None
        self._canvas.configure(cursor="")

    def _on_hscroll(self, *args: str) -> None:
        if self._current_scene is None:
            return
        next_value = self._next_scroll_value(self._scroll_x, args)
        dx = (next_value - self._scroll_x) * self._scroll_span_pixels
        self._scroll_x = next_value
        self.renderer.pan(dx, 0.0)
        self._sync_scrollbars()
        self._schedule_redraw()

    def _on_vscroll(self, *args: str) -> None:
        if self._current_scene is None:
            return
        next_value = self._next_scroll_value(self._scroll_y, args)
        dy = (next_value - self._scroll_y) * self._scroll_span_pixels
        self._scroll_y = next_value
        self.renderer.pan(0.0, dy)
        self._sync_scrollbars()
        self._schedule_redraw()

    def _next_scroll_value(self, current: float, args: tuple[str, ...]) -> float:
        if not args:
            return current
        mode = args[0]
        if mode == "moveto" and len(args) > 1:
            return max(0.0, min(1.0, float(args[1])))
        if mode == "scroll" and len(args) > 1:
            units = int(args[1])
            return max(0.0, min(1.0, current + units * self._scroll_step))
        return current

    def _sync_scrollbars(self) -> None:
        thumb = 0.12
        x1 = max(0.0, min(1.0 - thumb, self._scroll_x - thumb * 0.5))
        y1 = max(0.0, min(1.0 - thumb, self._scroll_y - thumb * 0.5))
        self._h_scroll.set(x1, x1 + thumb)
        self._v_scroll.set(y1, y1 + thumb)

    def _update_scroll_state(self, dx: float, dy: float) -> None:
        self._scroll_x = max(0.0, min(1.0, self._scroll_x + (dx / self._scroll_span_pixels)))
        self._scroll_y = max(0.0, min(1.0, self._scroll_y + (dy / self._scroll_span_pixels)))
        self._sync_scrollbars()

    def _set_busy(self, label: str) -> None:
        self._busy_counter += 1
        if self._busy_counter == 1:
            self._progress.start(10)
        self._progress_label_var.set(label)

    def _set_idle(self, label: str) -> None:
        self._busy_counter = max(0, self._busy_counter - 1)
        if self._busy_counter == 0:
            self._progress.stop()
            self._progress_label_var.set(label)

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

    def _on_export_clicked(self) -> None:
        if self._current_scene is None:
            messagebox.showinfo("Export", "No scene to export yet.")
            return

        target = filedialog.asksaveasfilename(
            title="Export SVG",
            defaultextension=".svg",
            filetypes=[("SVG files", "*.svg"), ("All files", "*.*")],
        )
        if not target:
            return

        profile = SVGExportProfile(mode="clean", include_diagnostics=True)
        exporter = SVGExporter(
            scene=self._current_scene,
            width=max(1024, self._canvas.winfo_width()),
            height=max(1024, self._canvas.winfo_height()),
        )
        diagnostics = exporter.export_with_profile(Path(target), profile=profile)
        self._status_var.set(f"Exported {diagnostics.total_paths} paths")

    def _toggle_theme(self) -> None:
        self._theme_mode = "dark" if self._theme_mode == "light" else "light"
        self._apply_theme()
        self._root.title(f"{self.config.app_name} ({self._theme_mode} mode)")

    def _apply_theme(self) -> None:
        style = ttk.Style(master=self._root)
        self._setup_platform_theme(style)
        if platform.system() == "Darwin":
            self._apply_macos_aqua_appearance()
            return

        palette = THEME_PALETTES.get(self._theme_mode, THEME_PALETTES["light"])
        self._root.tk_setPalette(
            background=palette["bg"],
            foreground=palette["text"],
            activeBackground=palette["button_active"],
            activeForeground=palette["text"],
            highlightBackground=palette["border"],
            highlightColor=palette["select"],
            selectBackground=palette["select"],
            selectForeground=palette["select_text"],
        )
        self._root.option_add("*Menu.background", palette["panel_alt"])
        self._root.option_add("*Menu.foreground", palette["text"])
        self._root.option_add("*Menu.activeBackground", palette["button_active"])
        self._root.option_add("*Menu.activeForeground", palette["text"])
        self._root.option_add("*Menu.selectColor", palette["select"])

        style.configure(".", background=palette["bg"], foreground=palette["text"])
        style.configure("TFrame", background=palette["bg"])
        style.configure("TLabel", background=palette["bg"], foreground=palette["text"])
        style.configure(
            "TButton",
            background=palette["button"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            lightcolor=palette["button_active"],
            darkcolor=palette["border"],
            focuscolor=palette["select"],
            padding=5,
        )
        style.configure(
            "TMenubutton",
            background=palette["button"],
            foreground=palette["text"],
            bordercolor=palette["border"],
            arrowcolor=palette["text"],
            focuscolor=palette["select"],
            padding=4,
        )
        style.configure("TCheckbutton", background=palette["bg"], foreground=palette["text"])
        style.configure(
            "TEntry",
            fieldbackground=palette["field"],
            foreground=palette["field_text"],
            insertcolor=palette["field_text"],
            bordercolor=palette["border"],
            lightcolor=palette["button_active"],
            darkcolor=palette["border"],
        )
        style.configure(
            "TCombobox",
            fieldbackground=palette["field"],
            foreground=palette["field_text"],
            background=palette["button"],
            bordercolor=palette["border"],
            arrowcolor=palette["text"],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=palette["field"],
            foreground=palette["field_text"],
            background=palette["button"],
            bordercolor=palette["border"],
            arrowcolor=palette["text"],
        )
        style.configure("Horizontal.TScale", background=palette["bg"], troughcolor=palette["panel_alt"], sliderrelief="flat")
        style.configure("TSeparator", background=palette["border"])
        style.configure("Vertical.TScrollbar", background=palette["button"], troughcolor=palette["panel"], arrowcolor=palette["text"])
        style.configure("Horizontal.TScrollbar", background=palette["button"], troughcolor=palette["panel"], arrowcolor=palette["text"])
        style.map(
            "TButton",
            background=[
                ("disabled", palette["panel_alt"]),
                ("active", palette["button_active"]),
                ("pressed", palette["select"]),
            ],
            foreground=[("disabled", palette["muted"]), ("active", palette["text"])],
        )
        style.map(
            "TMenubutton",
            background=[
                ("disabled", palette["panel_alt"]),
                ("active", palette["button_active"]),
                ("pressed", palette["select"]),
            ],
            foreground=[("disabled", palette["muted"]), ("active", palette["text"])],
            arrowcolor=[("disabled", palette["muted"]), ("active", palette["text"])],
        )
        style.map(
            "TCheckbutton",
            background=[("active", palette["bg"])],
            foreground=[("disabled", palette["muted"]), ("active", palette["text"])],
            indicatorcolor=[("selected", palette["select"]), ("!selected", palette["panel_alt"])],
        )
        style.map(
            "TEntry",
            fieldbackground=[("disabled", palette["panel_alt"]), ("readonly", palette["panel_alt"])],
            foreground=[("disabled", palette["muted"]), ("readonly", palette["text"])],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette["field"]), ("disabled", palette["panel_alt"])],
            foreground=[("readonly", palette["field_text"]), ("disabled", palette["muted"])],
            selectbackground=[("readonly", palette["select"])],
            selectforeground=[("readonly", palette["select_text"])],
        )
        style.map(
            "TSpinbox",
            fieldbackground=[("disabled", palette["panel_alt"])],
            foreground=[("disabled", palette["muted"])],
        )

        for canvas_name in ("_left_sidebar_canvas", "_right_sidebar_canvas"):
            if hasattr(self, canvas_name):
                canvas = getattr(self, canvas_name)
                canvas.configure(background=palette["bg"])
        if hasattr(self, "_canvas"):
            self._canvas.configure(background=palette["canvas_bg"], highlightbackground=palette["canvas_border"])

    def _apply_macos_aqua_appearance(self) -> None:
        """Switch native macOS Aqua appearance without overriding ttk colors."""
        appearance = "darkaqua" if self._theme_mode == "dark" else "aqua"
        try:
            self._root.tk.call("::tk::unsupported::MacWindowStyle", "appearance", ".", appearance)
        except tk.TclError:
            pass

        sidebar_bg = "#1e1e1e" if self._theme_mode == "dark" else "#f5f5f5"
        canvas_border = "#555555" if self._theme_mode == "dark" else "#d0d0d0"
        for canvas_name in ("_left_sidebar_canvas", "_right_sidebar_canvas"):
            if hasattr(self, canvas_name):
                canvas = getattr(self, canvas_name)
                canvas.configure(background=sidebar_bg)
        if hasattr(self, "_canvas"):
            self._canvas.configure(background="#f5f5f5", highlightbackground=canvas_border)

    def run(self) -> None:
        """Run the Tk event loop."""
        self._root.mainloop()
