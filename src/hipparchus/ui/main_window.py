"""Main Tkinter window with Art-first Beta interactions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import logging
import platform
from pathlib import Path
import queue
import tkinter as tk
from tkinter import ttk

from hipparchus.application import places
from hipparchus.application.controller import ApplicationController
from hipparchus.application.layer_inventory import fetch_layers
from hipparchus.application.page_size import Resolution
from hipparchus.application.palette_sheet import recoloured
from hipparchus.application.palettes import PRESET_OWN, named as palette_named
from hipparchus.core.fetch_progress import CancellationToken, FetchReporter
from hipparchus.application.source_stack import SourceStack
from hipparchus.ui import actions, menubar, theme
from hipparchus.ui.disclosure import Disclosure
from hipparchus.ui.frame_panel import FramePanelMixin
from hipparchus.ui.map_canvas import MapCanvas
from hipparchus.ui.page_panel import PagePanelMixin
from hipparchus.ui.status_bar import StatusBar
from hipparchus.ui.projection_choices import PROJECTION_CHOICES
from hipparchus.ui.toolbar import ToolbarMixin
from hipparchus.ui.window_canvas import CanvasMixin
from hipparchus.ui.window_preferences import PreferencesMixin
from hipparchus.ui.window_session import SessionMixin
from hipparchus.ui.window_sidebar import SidebarMixin
from hipparchus.ui.window_sources import SourceFilesMixin
from hipparchus.ui.window_theme import ThemeMixin
from hipparchus.ui.panels import LayersPanel, SourcesPanel, StylePicker
from hipparchus.application.presets import (
    ArtisticPreset,
    GeometryPipelineProfile,
    default_preset,
    preset_names,
    resolve_preset_name,
)
from hipparchus.application.quality import (
    quality_label_for,
)
from hipparchus.application.session import DEFAULT_QUALITY, Session

from hipparchus.application.session_history import SessionHistory
from hipparchus.application.preset_store import PresetStore
from hipparchus.core.config import AppConfig
from hipparchus.core.settings_store import SettingsStore
from hipparchus.plugins.interfaces import LoadedPlugin
from hipparchus.rendering.engine import Renderer
from hipparchus.rendering.models import RenderScene

# The saved places live in `application/places.py`, where the bounding
# boxes are checked and where the ⌘1…⌘9 run is derived from the same list
# the sidebar shows — two literals could not drift apart if they are one.

LEFT_SIDEBAR_WIDTH = 360
RIGHT_SIDEBAR_WIDTH = 300
SIDEBAR_CONTENT_PADDING = 10

SOURCE_HELP: dict[str, str] = {
    "local_osm_pbf": "Local .osm.pbf extract, or GeoJSON fallback.",
    "vector_tiles": "PMTiles, MBTiles, MVT export, GeoJSON, or JSON.",
    "natural_earth": "Folder of Natural Earth shapefiles, or a vector file.",
    "overture": "GeoParquet places/buildings extract, GeoJSON, or JSON.",
    "terrain_dem": "GeoTIFF DEM for contours, or contour GeoJSON/JSON.",
}

SAMPLE_SOURCE_PATHS: dict[str, str] = {
    "vector_tiles": "datasets/pmtiles/firenze.pmtiles",
    "natural_earth": "datasets/natural_earth",
    "overture": "datasets/overture/demo_overture_places_buildings.parquet",
    "terrain_dem": "datasets/dem/athens_z11_1158_790.tif",
}


# `SourceLibraryPreset` and its eleven bundles are gone: they were the
# vocabulary the composing source stack replaced, and the last code that
# reached them went with the settings rail.

# Paper used to be a table of pixel sizes here — "A4" meant 2480 x 3508, which
# is A4 at 300 dpi with the 300 left implicit. It gave the PNG the right answer
# and the PDF a page 34.4 x 48.7 inches, because Skia reads those numbers as
# points. The sheets are stated in inches now, in `application/page_size.py`,
# where one description serves all three exporters and the arithmetic can be
# checked without a window.

# The palette, the accent and the type scale live in `ui/theme.py`, where they
# can be checked: that body text clears a contrast floor on its own ground, and
# that the accent drawn on the map is chosen against the map.


def _load_app_icon(path: str) -> "tk.PhotoImage | None":
    """The window/taskbar icon, or nothing. Absent is absent."""
    location = Path(path)
    if not location.is_file():
        return None
    try:
        return tk.PhotoImage(file=str(location))
    except tk.TclError:  # pragma: no cover - a Tk without PNG support
        return None


@dataclass
class MainWindow(
    FramePanelMixin,
    PagePanelMixin,
    ToolbarMixin,
    SessionMixin,
    SidebarMixin,
    PreferencesMixin,
    CanvasMixin,
    SourceFilesMixin,
    ThemeMixin,
):
    """Primary application window with sidebar layout."""

    config: AppConfig
    loaded_plugins: list[LoadedPlugin]
    controller: ApplicationController
    renderer: Renderer
    default_preset: ArtisticPreset = field(default_factory=default_preset)
    #: What the plugin loader could not load, and why. Recorded since the
    #: loader was written and never once shown.
    plugin_load_errors: list[str] = field(default_factory=list)
    #: The window to build in, or `None` to make one — which is what the
    #: application does. The test suite hands in the one root a run is allowed:
    #: a second Tk root is a second window on somebody's screen, and on macOS
    #: it is also a hang or a crash depending on the order they are made in.
    root: tk.Tk | None = None

    def __post_init__(self) -> None:
        #: Whether closing this window should take the interpreter's root with
        #: it. False when the root was handed in: it outlives this window.
        self._owns_root = self.root is None
        self._root = self.root if self.root is not None else tk.Tk()
        # Kept on the instance -- Tk drops a PhotoImage with no surviving
        # Python reference, icon and all, the moment this method returns.
        self._app_icon_image = _load_app_icon(self.config.app_icon)
        if self._app_icon_image is not None:
            self._root.iconphoto(True, self._app_icon_image)
        self._theme_mode = self.config.theme_mode
        # Before anything is built. `theme.current()` is what every raw Tk
        # widget reads for its own colours — the Locator's canvas, the map's
        # controls, the status bar — and it answers from module state that only
        # the appearance toggle used to set. So a window *started* in dark mode
        # got dark ttk styling over light hand-drawn widgets, and the Locator
        # sat in the corner as a white box until somebody toggled the theme
        # twice.
        theme.set_mode(self._theme_mode)
        self._current_scene: RenderScene | None = None
        #: The area the map on screen was drawn for. What tells a pan apart
        #: from a choice when Render map is pressed — see `area_to_fetch`.
        self._rendered_area: tuple[float, float, float, float] | None = None
        self._canvas_image: tk.PhotoImage | None = None
        self._canvas_image_tempfile: Path | None = None
        self._pending_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._drag_last_xy: tuple[int, int] | None = None
        self._select_origin: tuple[int, int] | None = None
        self._select_rect: int | None = None
        self._select_armed = False
        self._redraw_job: str | None = None
        self._queue_job: str | None = None
        self._render_request_id = 0
        self._render_inflight = False
        self._fetch_started_at: float | None = None
        self._debug_enabled_var = tk.BooleanVar(value=True)
        #: The same answer, readable from any thread. Kept in step by a trace
        #: on the variable, which runs on the UI thread where it is safe.
        self._debug_enabled = True
        self._debug_enabled_var.trace_add(
            "write", lambda *_args: self._follow_debug_setting()
        )
        self._perf_summary_var = tk.StringVar(value="No diagnostics yet.")
        self._debug_log_file = self.config.cache_dir / "hipparchus_debug.log"

        self._layer_visibility_vars: dict[str, tk.BooleanVar] = {}
        self._settings_store = SettingsStore(self.config.settings_file)
        self._settings = self._settings_store.load()
        self._preset_store = PresetStore(self.config.presets_file)
        self._custom_presets = self._load_custom_presets()
        self._preset_options = sorted({*preset_names(), *self._custom_presets.keys()})
        # The default profile's label rather than a literal: the menu opening
        # on Fast Preview while the session defaults to Print Export would show
        # one thing and draw another.
        self._quality_var = tk.StringVar(value=quality_label_for(DEFAULT_QUALITY))
        # A forced projection, by mode name; "" is the honest choice, which
        # promotes a world frame to Equal Earth and its curved edges. Two vars
        # because the menu shows labels and the session stores mode names, and
        # one `StringVar` cannot hold both.
        self._projection_var = tk.StringVar(value="")
        self._projection_label_var = tk.StringVar(value=PROJECTION_CHOICES[""])
        # Not part of the session: a drawing choice for the next Render map,
        # like the page-panel Include toggles, rather than a fact about the
        # map worth undoing back to.
        self._relief_over_buildings_var = tk.BooleanVar(value=False)
        self._paper_preset_var = tk.StringVar(value="Canvas")
        self._paper_orientation_var = tk.StringVar(value="Landscape")
        # A choice from four rather than a field: a field invites 1200 dpi on a
        # poster, which is 1.2 gigapixels and several minutes of drawing before
        # it fails. Only reached when a paper other than Canvas is chosen.
        self._paper_dpi_var = tk.StringVar(value=str(Resolution.DEFAULT))
        # The Custom sheet, in inches. 20 x 12 is 5:3, which at 150 dpi is
        # 3000 x 1800 — the shape a whole-earth sheet is most often asked for.
        self._custom_width_var = tk.StringVar(value="20")
        self._custom_height_var = tk.StringVar(value="12")
        # Off by default: a sheet is usually a sheet, and someone printing to
        # A3 wants A3 rather than the map's own proportions.
        self._edge_to_edge_var = tk.BooleanVar(value=False)
        self._page_cost_var = tk.StringVar(value="")
        self._map_title_var = tk.StringVar(value="")
        self._map_subtitle_var = tk.StringVar(value="")
        self._include_title_var = tk.BooleanVar(value=False)
        self._include_scale_bar_var = tk.BooleanVar(value=False)
        self._include_north_arrow_var = tk.BooleanVar(value=False)
        self._include_legend_var = tk.BooleanVar(value=False)
        # On by default so what the preview shows is what the export contains.
        # Off gives a transparent SVG for compositing over other artwork.
        self._include_background_var = tk.BooleanVar(value=True)
        # Absolute, not the preset's relative weights -- see
        # application/line_weight.py. 1.0 leaves every export exactly as the
        # preset states it.
        self._line_weight_var = tk.DoubleVar(value=1.0)
        self._map_models = self.controller.data_source_manager.get_map_models()
        self._map_model_label_to_id = {str(model["label"]): str(model["id"]) for model in self._map_models}
        self._map_model_id_to_label = {str(model["id"]): str(model["label"]) for model in self._map_models}
        self._map_models_by_id = {str(model["id"]): tuple(model["providers"]) for model in self._map_models}
        # A map is built from sources, and sources stack. This replaces the
        # model dropdown, the source library and the relief toggle, which were
        # three vocabularies for one idea.
        self.source_stack = SourceStack()
        for provider_id, existing in self.controller.data_source_manager.get_optional_source_paths().items():
            if existing:
                self.source_stack.set_path(provider_id, existing)
        if self.config.start_sources:
            # An explicit list replaces the defaults rather than adding to them,
            # so a launch can ask for terrain alone.
            for definition in self.source_stack.definitions:
                self.source_stack.set_enabled(definition.source_id, False)
            for source_id in self.config.start_sources:
                self.source_stack.set_enabled(source_id, True)
        self._sources_panel: SourcesPanel | None = None
        self._layers_panel: LayersPanel | None = None
        self._style_picker: StylePicker | None = None
        self._layer_summary = ""
        self._fetch_cancel: CancellationToken | None = None
        self._fetch_reporter: FetchReporter | None = None
        self._preset_var = tk.StringVar(
            value=resolve_preset_name(self.config.start_preset, self._preset_options, self.default_preset.name)
        )
        self._composition_var = tk.StringVar(value="OpenStreetMap")
        self._location_preset_var = tk.StringVar(value="London Center")
        # Shared by the frame rail's caption and the toolbar's area readout --
        # one fact, wanted in two places, so one variable rather than two kept
        # in step by hand. Created here, not where the rail first uses it, so
        # the toolbar (built first) can read it too.
        self._minimap_caption = tk.StringVar(value="")
        # Colour, separate from the style. A preset is a whole sheet, so "the
        # same map in other colours" was not something that could be asked for.
        self._palette_var = tk.StringVar(value=PRESET_OWN)
        device_scale = self._auto_device_scale()
        if hasattr(self.renderer, "device_scale"):
            setattr(self.renderer, "device_scale", device_scale)

        self._aoi_vars = {
            "min_lon": tk.StringVar(value="-0.15"),
            "min_lat": tk.StringVar(value="51.48"),
            "max_lon": tk.StringVar(value="-0.02"),
            "max_lat": tk.StringVar(value="51.56"),
        }

        self._logger = self._configure_diagnostics_logger()

        # Undo, and what it is allowed to take back. `_restoring` guards the
        # write-back: putting a remembered session on screen fires the very
        # traces that record changes, and a restore is not an edit.
        self._restoring = False
        self._menubar = None
        self._render_tip = None
        self._toolbar_cancel_button = None
        self._locator_window = None
        self._settings_window = None
        self._about = None
        self._history = SessionHistory(Session())

        self._build_window()
        self._build_layout()
        self._apply_theme()
        self._refresh_minimap()
        self._build_menus()
        self._restore_session()
        self._watch_for_changes()
        self._refresh_render_button()
        # Closing the window is the last chance to remember what it was doing.
        self._root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._root.after(120, self._show_about_at_launch)
        self._queue_job = self._root.after(50, self._drain_callback_queue)
        if self.config.start_area or self.config.fetch_on_start:
            self._root.after(300, self._maybe_fetch_on_start)
        # After the splash, not on top of it: the one-time offer to fetch the
        # world data, made only when it is absent and only once.
        self._root.after(1200, self._maybe_offer_natural_earth)

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
        # From the config rather than written here, so the size it opens at and
        # the size it may be dragged to cannot disagree — the minimum used to be
        # a pair of literals larger than a 13-inch laptop's whole screen.
        self._root.minsize(self.config.min_width, self.config.min_height)

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

    def _follow_debug_setting(self) -> None:
        """Copy the menu's answer somewhere the worker threads may read it."""
        try:
            self._debug_enabled = bool(self._debug_enabled_var.get())
        except tk.TclError:  # pragma: no cover - the window is going away
            self._debug_enabled = False

    def _debug(self, message: str, *args: object) -> None:
        """Log a line, if debug logging is on.

        Reads a plain bool rather than the Tk variable behind it, because this
        is called from the fetch and render threads. Asking a `BooleanVar` for
        its value calls into the Tcl interpreter, and doing that from any thread
        but the one that made it raises "main thread is not in main loop" —
        which the render worker then caught and turned into a modal error
        dialogue, on top of whatever the person was doing.
        """
        if not self._debug_enabled:
            return
        self._logger.info(message, *args)

    def _build_layout(self) -> None:
        root = self._root
        root.grid_rowconfigure(0, weight=0)  # Top bar - fixed height
        root.grid_rowconfigure(1, weight=1)  # Main content - expands
        root.grid_rowconfigure(2, weight=0)  # Status bar - fixed height
        root.grid_columnconfigure(0, weight=1)

        top = ttk.Frame(root, padding=(14, 10, 14, 10))
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        top.grid_columnconfigure(1, weight=0)

        ttk.Label(top, text="Hipparchus", font=theme.font("title")).grid(row=0, column=0, sticky="w")
        ttk.Button(top, text="Dark/Light", command=self._toggle_theme).grid(row=0, column=1, sticky="e")

        self._build_toolbar_controls(top)

        # Resizable, not the fixed-width columns this used to be: a sash
        # between each pane rather than a width set once at launch and never
        # touched again. Collapsible sections (ui/disclosure.py) solve "the
        # rail is too long"; this solves "the rail is too narrow" — the style
        # picker sat below the fold at the 1100-wide default because there
        # was no way to ask for more room, only to scroll past what a
        # populated Layers panel put in the way.
        self._panes = ttk.PanedWindow(root, orient="horizontal")
        self._panes.grid(row=1, column=0, sticky="nsew")

        left_outer, self._left_sidebar_canvas, left = self._create_scrollable_frame(self._panes, LEFT_SIDEBAR_WIDTH)
        self._panes.add(left_outer, weight=0)

        center = ttk.Frame(self._panes, padding=12)
        center.grid_rowconfigure(1, weight=1)
        center.grid_columnconfigure(0, weight=1)
        self._panes.add(center, weight=1)

        right_outer, self._right_sidebar_canvas, right = self._create_scrollable_frame(self._panes, RIGHT_SIDEBAR_WIDTH)
        self._panes.add(right_outer, weight=0)

        # One row per source rather than one line for the lot: a fetch can take
        # five minutes while a single line says "Idle", and a failure that looks
        # like a wait is a five-minute lie.
        self._status = StatusBar(
            root, on_cancel=self._on_cancel_fetch, mark_path=self.config.makers_mark
        )
        self._status.grid(row=2, column=0, sticky="ew")

        self._build_left_sidebar(left)
        self._build_center_canvas(center)
        self._build_right_sidebar(right)

        # Sash positions matching the widths this used to be fixed at, set
        # once every pane holds real content so the panes have something to
        # measure the split against.
        root.update_idletasks()
        self._panes.sashpos(0, LEFT_SIDEBAR_WIDTH)
        self._panes.sashpos(1, max(LEFT_SIDEBAR_WIDTH + 200, root.winfo_width() - RIGHT_SIDEBAR_WIDTH))

    def _build_menus(self) -> None:
        """Hand the menu bar the window's verbs.

        Every one of them is a control that also exists on screen: a shortcut
        for something with no button is a secret, not a feature. The menu and
        the button call the same function rather than each doing it themselves
        — two copies of an action become two behaviours within a release.

        The menu also owns the key bindings, so an item cannot advertise ⌘E and
        bind nothing: Tk's ``accelerator=`` draws the shortcut and binds
        nothing at all.
        """
        self._actions = actions.Actions()
        for key, handler in (
            ("undo", self._on_undo),
            ("redo", self._on_redo),
            ("render_map", self._on_fetch_clicked),
            ("cancel_fetch", self._on_cancel_fetch),
            ("open_locator", self._open_locator),
            ("search_place", self._focus_place_search),
            ("draw_area", self._arm_area_selection),
            ("paste_coordinates", self._paste_coordinates),
            ("export_svg", self._on_export_clicked),
            ("export_pdf", self._on_export_pdf),
            ("export_png", self._on_export_png),
            ("export_geojson", self._on_export_geojson),
            ("zoom_in", lambda: self._zoom_view(1.5)),
            ("zoom_out", lambda: self._zoom_view(0.67)),
            ("fit_window", self._reset_view),
            ("rotate_left", lambda: self._rotate_view(-15)),
            ("rotate_right", lambda: self._rotate_view(15)),
            ("reset_rotation", self._reset_rotation),
            ("toggle_theme", self._toggle_theme),
            ("settings", self._open_settings),
            ("about", self._open_about),
        ):
            self._actions.register(key, handler)

        self._menubar = menubar.build(
            self._root, self._actions, on_place=self._use_saved_place
        )
        self._refresh_undo_menu()

    def _build_center_canvas(self, parent: ttk.Frame) -> None:
        """The map, which owns its own viewport and its own pointing.

        Everything that was here — pan, zoom, the marquee, the control stack,
        the keyboard — lives in `ui/map_canvas.py` now, where it can be tested
        against a real canvas without a render pipeline behind it.
        """
        ttk.Label(parent, text="Map Preview", font=theme.font("heading")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )

        self._map = MapCanvas(
            parent,
            renderer=self.renderer,
            scene=lambda: self._current_scene,
            background=self._canvas_surround_color,
            on_redraw=self._schedule_redraw,
            on_area_drawn=self._on_area_drawn,
            on_status=self._status.set_message,
        )
        self._map.grid(row=1, column=0, sticky="nsew")
        self._canvas = self._map.widget

        self._canvas.create_text(
            450,
            280,
            text="Fetch an area to render artistic map structures",
            fill=theme.current().muted,
            font=theme.font("lead"),
            justify="center",
            tags=("placeholder",),
        )

    def _file_reason(self, source_id: str) -> str:
        """Why a chosen file cannot be read, in the source's own row.

        The manager has computed this all along and the window showed it only
        as a paragraph at the foot of the rail — which left the one format this
        cannot read looking like a format it silently ignored.
        """
        statuses = self.controller.data_source_manager.get_provider_statuses()
        status = statuses.get(source_id)
        if status is None or status.available:
            return ""
        return status.detail or "This file cannot be read."

    # -- source stack callbacks ---------------------------------------------
    def _on_source_toggled(self, source_id: str, enabled: bool) -> None:
        self.source_stack.set_enabled(source_id, enabled)
        if self._sources_panel is not None:
            # A source needing a file refuses to tick, so the panel is rebuilt
            # from the stack rather than trusting the click.
            self._sources_panel.rebuild()
        self._composition_var.set(self.source_stack.summary())
        self._status.set_message(f"Sources: {self.source_stack.summary()}")
        self._record()
        self._refresh_render_button()

    def _on_source_setting_changed(self, source_id: str, key: str, value: object) -> None:
        self.source_stack.set_setting(source_id, key, value)
        self.controller.data_source_manager.apply_source_settings(
            source_id, self.source_stack.provider_overrides(source_id)
        )
        self._status.set_message(f"{source_id}: {key} = {value}")
        self._record()

    def _on_projection_chosen(self, label: str) -> None:
        """Turn the menu's label back into the mode name the builder speaks."""
        for mode, shown in PROJECTION_CHOICES.items():
            if shown == label:
                self._projection_var.set(mode)
                break
        self._status.set_message(f"Projection: {label} — takes effect on the next Render map.")
        self._record()

    def _on_layer_visibility_changed(self, layer_id: str, visible: bool) -> None:
        self.renderer.set_layer_visibility(layer_id, visible)
        self._schedule_redraw()
        self._record()

    def _on_style_selected(self, name: str) -> None:
        self._preset_var.set(name)
        self._refresh_delete_button()

    def _resolve_selected_preset(self) -> ArtisticPreset:
        """The chosen style, in the chosen colours.

        Recoloured here rather than at the render call, so that what is drawn,
        what is exported and what "Save this style" keeps are one thing. A
        palette of "the preset's own" resolves to nothing and leaves it alone.
        """
        selected = self._preset_var.get().strip()
        custom = self._custom_presets.get(selected)
        preset = custom if custom is not None else default_preset(selected)
        return recoloured(preset, palette_named(self._palette_var.get()))

    def _cartographic_geometry_profile(self, profile: GeometryPipelineProfile) -> GeometryPipelineProfile:
        return replace(
            profile,
            derive_voronoi=False,
            derive_delaunay=False,
            derive_hex_grid=False,
            derive_circle_packing=False,
            relief_over_buildings=bool(self._relief_over_buildings_var.get()),
        )

    def _load_custom_presets(self) -> dict[str, ArtisticPreset]:
        try:
            return self._preset_store.load()
        except Exception as exc:  # noqa: BLE001
            self._status.set_message(f"Could not load presets: {exc}")
            return {}

    def _build_diagnostics(self, parent: ttk.Frame) -> None:
        """Put away, behind a disclosure.

        Genuinely useful and genuinely not part of making a map, so it stops
        occupying the rail between the styles and the export. Starts
        collapsed, unlike the sections above it -- this is the one part of
        the rail that is not about the map at all.
        """
        section = Disclosure(parent, "Diagnostics", start_expanded=False)
        self._diagnostics = section.body
        ttk.Checkbutton(
            self._diagnostics, text="Enable diagnostics logging",
            variable=self._debug_enabled_var,
        ).pack(anchor="w", pady=(4, 2))
        ttk.Label(
            self._diagnostics, text=f"Log: {self._debug_log_file}",
            font=theme.font("caption2"), wraplength=250, justify="left",
        ).pack(anchor="w")
        row = ttk.Frame(self._diagnostics)
        row.pack(fill="x", pady=(4, 0))
        ttk.Button(row, text="Copy", command=self._copy_diagnostics).pack(
            side="left", fill="x", expand=True, padx=(0, 3)
        )
        ttk.Button(row, text="Save…", command=self._save_diagnostics).pack(
            side="left", fill="x", expand=True, padx=(3, 0)
        )
        ttk.Label(
            self._diagnostics, textvariable=self._perf_summary_var, justify="left",
            wraplength=250, font=theme.font("caption2"),
        ).pack(anchor="w", pady=(4, 0))

    def _maybe_fetch_on_start(self) -> None:
        """Preselect a start area and/or auto-fetch on launch (screenshot workflow)."""
        area = self.config.start_area
        if area:
            if places.by_name(area) is not None:
                self._location_preset_var.set(area)
                self._apply_location_preset()
            else:
                self._logger.warning(
                    "HIPPARCHUS_START_AREA '%s' is not a known area preset; ignoring. Known: %s",
                    area,
                    ", ".join(places.names()),
                )
        if self.config.fetch_on_start:
            self._on_fetch_clicked()

    def _active_base_layers(self) -> list[str]:
        """The layers to fetch: the standard set, minus anything unticked."""
        def visible(layer_id: str) -> bool:
            variable = self._layer_visibility_vars.get(layer_id)
            return True if variable is None else bool(variable.get())

        return list(fetch_layers(visible))

    def run(self) -> None:
        """Run the Tk event loop."""
        self._root.mainloop()
