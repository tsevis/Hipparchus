"""Local source files: choosing them, and fetching Natural Earth when it is missing.

A mixin for `MainWindow`: the methods read and write the window's own state.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox

from hipparchus.application import natural_earth_download as ned


class SourceFilesMixin:
    """Local source files: choosing them, and fetching Natural Earth when it is missing."""

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _choose_source_path(self, provider_id: str) -> None:
        self._choose_source_path_impl(provider_id)

    def _choose_source_path_impl(self, provider_id: str) -> None:
        filetypes = {
            "local_osm_pbf": [("OSM PBF", "*.osm.pbf"), ("GeoJSON/JSON", "*.geojson *.json"), ("All files", "*.*")],
            "vector_tiles": [("Vector tile sources", "*.mbtiles *.pmtiles *.geojson *.json"), ("All files", "*.*")],
            "natural_earth": [("Natural Earth/vector files", "*.shp *.gpkg *.geojson *.json"), ("All files", "*.*")],
            "overture": [("Overture/GeoParquet", "*.parquet *.geojson *.json"), ("All files", "*.*")],
            "terrain_dem": [("Terrain/contours", "*.tif *.tiff *.geojson *.json"), ("All files", "*.*")],
        }.get(provider_id, [("All files", "*.*")])
        if provider_id == "natural_earth":
            selected = filedialog.askdirectory(title="Choose Natural Earth folder")
            if not selected:
                selected = filedialog.askopenfilename(title="Choose Natural Earth file", filetypes=filetypes)
        else:
            selected = filedialog.askopenfilename(title="Choose map source", filetypes=filetypes)
        if not selected:
            return
        # Two places need to agree: the stack decides whether the source can be
        # ticked, and the manager does the reading. There used to be a third —
        # a set of path variables that Apply Settings wrote from — and nothing
        # reads them now that the button is gone.
        self.source_stack.set_path(provider_id, selected)
        self.controller.data_source_manager.set_optional_source_path(provider_id, selected)
        if self._sources_panel is not None:
            self._sources_panel.rebuild()
        self._status.set_message(f"{provider_id}: {selected}")
        self._record()

    def _download_natural_earth(
        self, provider_id: str, *, on_done: Callable[[], None] | None = None
    ) -> None:
        """Fetch the Natural Earth layers, off the UI thread, then point the
        source at them. The data is a download, not a checkout, so an empty
        folder is offered a way to fill itself rather than only a file dialog.

        ``on_done`` runs after the data is in place — used by the large-area
        flow to draw the map the moment its source becomes available.
        """
        self._natural_earth_on_done = on_done
        root = self._repo_root()
        pending = ned.missing(root)
        if not pending:
            self._natural_earth_installed(provider_id)
            self._status.set_message("Natural Earth data is already installed.")
            return
        if not messagebox.askyesno(
            "Download Natural Earth data",
            f"Download {len(pending)} Natural Earth layers — coastline, countries, "
            "lakes and places at 1:110m and 1:10m — from naturalearthdata.com?\n\n"
            "It is a few tens of megabytes and only needs doing once.",
        ):
            return
        self._status.set_message("Downloading Natural Earth data…")

        def worker() -> None:
            def report(done: int, total: int, layer: ned.Layer) -> None:
                self._pending_queue.put(
                    ("run", lambda d=done, t=total, name=layer.stem:
                        self._status.set_message(f"Natural Earth: {name} ({d}/{t})"))
                )

            try:
                ned.install(root, on_progress=report)
                self._pending_queue.put(("run", lambda: self._natural_earth_installed(provider_id)))
            except Exception as exc:  # noqa: BLE001 - reported to the user, not swallowed
                self._pending_queue.put(("error", RuntimeError(f"Natural Earth download failed: {exc}")))

        threading.Thread(target=worker, daemon=True).start()

    def _natural_earth_installed(self, provider_id: str) -> None:
        """Point the Natural Earth source at the freshly downloaded folder."""
        folder = str(self._repo_root() / "datasets" / "natural_earth")
        self.source_stack.set_path(provider_id, folder)
        self.controller.data_source_manager.set_optional_source_path(provider_id, folder)
        if self._sources_panel is not None:
            self._sources_panel.rebuild()
        self._status.set_message("Natural Earth data ready — tick Natural Earth to draw with it.")
        self._record()
        # A follow-up waiting on the data — the large-area flow drawing the map
        # once its source exists. Cleared first, so it runs once.
        follow_up, self._natural_earth_on_done = getattr(self, "_natural_earth_on_done", None), None
        if follow_up is not None:
            follow_up()

    def _maybe_offer_natural_earth(self) -> None:
        """Once, on a launch with the data absent: offer to fetch it.

        Marked as asked before the question is put, so a decline, an error or a
        closed dialog all count: a person mapping cities from Overpass is not
        asked again at every launch. Sources → Natural Earth → Download stays.
        """
        if self._settings.natural_earth_prompted or not ned.missing(self._repo_root()):
            return
        self._apply_settings(self._settings.with_changes(natural_earth_prompted=True))
        if messagebox.askyesno(
            "Natural Earth data",
            "Hipparchus can draw whole countries, continents and the world from "
            "Natural Earth data, and the locator sharpens with it. The data is "
            "not bundled — download it now? A few tens of megabytes, once.\n\n"
            "You can also do this any time from Sources → Natural Earth → Download.",
        ):
            self._download_natural_earth("natural_earth")
