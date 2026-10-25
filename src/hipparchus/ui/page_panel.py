"""Page: paper, orientation, resolution, and the SVG's furniture.

The paper drives all three exports, not only the SVG. It is stated in inches,
so pixels are inches x dpi for the PNG, points are inches x 72 for the PDF,
and the SVG keeps taking pixels because that is what a viewport is. A sheet
asked for at 24 x 36 is the same sheet in every format.

The furniture is off by default and asked for per export rather than
remembered as map state -- the map is the product, and nothing here changes
it, which is why none of it lands in the session or in undo.

A mixin rather than a widget class: `_page_spec`/`_canvas_size` are read by
the toolbar's export methods too (`_export_raster`, `_refresh_page_cost`), and
`_canvas_size` reaches into the map canvas's own widget. That coupling
predates this move -- the two were always one conceptual unit, physically
adjacent in the file they came from -- and untangling it is a redesign, not
the pure move this phase is.
"""

from __future__ import annotations

from tkinter import ttk

from hipparchus.application.line_weight import MAX_LINE_WEIGHT, MIN_LINE_WEIGHT
from hipparchus.application.page_size import PageSpec, PaperSize, Resolution
from hipparchus.application.sheet_scale import REFERENCE_HEIGHT, REFERENCE_WIDTH
from hipparchus.export.profiles import MapComposition
from hipparchus.ui import theme, tooltip
from hipparchus.ui.disclosure import Disclosure


class PagePanelMixin:
    """`MainWindow`'s Page section: paper, furniture, and the export arithmetic that reads them."""

    def _build_page_panel(self, parent: ttk.Frame) -> None:
        """The page: paper, orientation, resolution, and the SVG's furniture.

        The paper drives all three exports, not only the SVG. It is stated in
        inches, so pixels are inches x dpi for the PNG, points are inches x 72
        for the PDF, and the SVG keeps taking pixels because that is what a
        viewport is. A sheet asked for at 24 x 36 is the same sheet in every
        format.

        The furniture below is off by default and asked for per export rather
        than remembered as map state — the map is the product, and nothing here
        changes it, which is why none of it lands in the session or in undo.
        """
        body = Disclosure(parent, "Page", hint="paper, and what rides on it").body

        row = ttk.Frame(body)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Paper", width=11, font=theme.font("caption")).pack(side="left")
        ttk.OptionMenu(
            row, self._paper_preset_var, self._paper_preset_var.get(),
            *PaperSize.names(), command=lambda _: self._refresh_page_cost(),
        ).pack(side="left", fill="x", expand=True)

        # The Custom sheet's two numbers. Shown always rather than hidden
        # behind the Paper choice: a field that appears and disappears makes
        # the panel jump, and these read as inert when another sheet is picked.
        row = ttk.Frame(body)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Custom in", width=11, font=theme.font("caption")).pack(side="left")
        ttk.Entry(row, textvariable=self._custom_width_var, width=6).pack(side="left")
        ttk.Label(row, text="x", font=theme.font("caption")).pack(side="left", padx=4)
        ttk.Entry(row, textvariable=self._custom_height_var, width=6).pack(side="left")
        self._custom_aspect_label = ttk.Label(row, text="", font=theme.font("caption"))
        self._custom_aspect_label.pack(side="left", padx=6)
        for var in (self._custom_width_var, self._custom_height_var):
            var.trace_add("write", lambda *_: self._refresh_page_cost())

        row = ttk.Frame(body)
        row.pack(fill="x", pady=2)
        ttk.Checkbutton(
            row,
            text="Edge to edge",
            variable=self._edge_to_edge_var,
            command=self._refresh_page_cost,
        ).pack(side="left")
        tooltip.attach(
            row,
            "Give the exported sheet the map's own proportions and let the map "
            "run right to its edges. Off, the map is centred on the sheet you "
            "chose — which is what you want for paper, and what leaves a bar "
            "above and below a wide map like a rectangular world.",
        )

        row = ttk.Frame(body)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Orientation", width=11, font=theme.font("caption")).pack(side="left")
        ttk.OptionMenu(
            row, self._paper_orientation_var, self._paper_orientation_var.get(),
            *PageSpec.ORIENTATIONS, command=lambda _: self._refresh_page_cost(),
        ).pack(side="left", fill="x", expand=True)

        row = ttk.Frame(body)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Resolution", width=11, font=theme.font("caption")).pack(side="left")
        ttk.OptionMenu(
            row, self._paper_dpi_var, self._paper_dpi_var.get(),
            *(str(dpi) for dpi in Resolution.all()),
            command=lambda _: self._refresh_page_cost(),
        ).pack(side="left", fill="x", expand=True)

        # Absolute, not the preset's relative weights: a highway still reads
        # heavier than a footpath at either end, but a poster wants both
        # heavier than a screen preview does.
        row = ttk.Frame(body)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Line weight", width=11, font=theme.font("caption")).pack(side="left")
        ttk.Scale(
            row, from_=MIN_LINE_WEIGHT, to=MAX_LINE_WEIGHT, orient="horizontal",
            variable=self._line_weight_var, command=lambda _=None: self._refresh_line_weight_label(),
        ).pack(side="left", fill="x", expand=True)
        self._line_weight_label = ttk.Label(row, text="1.0×", font=theme.font("caption"), width=5)
        self._line_weight_label.pack(side="left", padx=(6, 0))
        tooltip.attach(
            row,
            "How heavy every stroke reads on the exported sheet, from the "
            "preset's own widths (1x) to a quarter as thin or four times as "
            "heavy. The preset's relative weights — a highway over a "
            "footpath — hold at every setting; this only scales all of them "
            "together, for the medium the map is going onto.",
        )
        self._refresh_line_weight_label()

        # What it costs, before it is spent. A PDF ignores this line entirely —
        # it carries physical size and no pixels — which is why it says so.
        ttk.Label(
            body, textvariable=self._page_cost_var, font=theme.font("caption"),
            foreground=theme.current().muted, wraplength=260, justify="left",
        ).pack(anchor="w", pady=(1, 4))
        self._refresh_page_cost()

        ttk.Checkbutton(
            body, text="Title block", variable=self._include_title_var,
            command=self._refresh_title_fields,
        ).pack(anchor="w", pady=1)

        # The title fields appear with the title block, because two empty boxes
        # for a block that is switched off are two questions nobody asked.
        self._title_fields = ttk.Frame(body)
        for label, var in (("Title", self._map_title_var), ("Subtitle", self._map_subtitle_var)):
            row = ttk.Frame(self._title_fields)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label, width=11, font=theme.font("caption")).pack(side="left")
            ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        self._refresh_title_fields()

        for text, var, why in (
            ("Scale bar", self._include_scale_bar_var,
             "A bar of known ground length, labelled in the projection's own units."),
            ("North arrow", self._include_north_arrow_var, ""),
            ("Legend", self._include_legend_var,
             "The first ten visible layers, named as the layer panel names them."),
            ("Background", self._include_background_var,
             "Off exports a transparent SVG for compositing. Dark presets need it on."),
        ):
            check = ttk.Checkbutton(body, text=text, variable=var)
            check.pack(anchor="w", pady=1)
            if why:
                tooltip.attach(check, why)

    def _refresh_title_fields(self) -> None:
        if bool(self._include_title_var.get()):
            self._title_fields.pack(fill="x", pady=(2, 0))
        else:
            self._title_fields.pack_forget()

    def _refresh_line_weight_label(self) -> None:
        self._line_weight_label.configure(text=f"{self._line_weight_var.get():.2g}×")

    def _export_composition(self) -> MapComposition:
        return MapComposition(
            title=self._map_title_var.get().strip(),
            subtitle=self._map_subtitle_var.get().strip(),
            include_title=bool(self._include_title_var.get()),
            include_scale_bar=bool(self._include_scale_bar_var.get()),
            include_north_arrow=bool(self._include_north_arrow_var.get()),
            include_legend=bool(self._include_legend_var.get()),
            paper_preset=self._paper_preset_var.get(),
            orientation=self._paper_orientation_var.get(),
        )

    def _page_spec(self) -> PageSpec:
        """The page the controls describe, as one value.

        All the arithmetic lives in `application/page_size.py`, where it can be
        checked. This reads three widgets and hands them over.
        """
        try:
            dpi = int(float(self._paper_dpi_var.get()))
        except (TypeError, ValueError):
            dpi = Resolution.DEFAULT
        # A half-typed number is not a sheet: a field mid-edit keeps the
        # default rather than collapsing the page to nothing, and `PageSpec`
        # clamps whatever survives to something drawable.
        def _inches(var: object, fallback: float) -> float:
            try:
                return float(str(var.get()).strip())  # type: ignore[attr-defined]
            except (TypeError, ValueError, AttributeError):
                return fallback

        return PageSpec(
            paper_name=self._paper_preset_var.get(),
            orientation=self._paper_orientation_var.get(),
            dpi=dpi,
            custom_width_inches=_inches(self._custom_width_var, 20.0),
            custom_height_inches=_inches(self._custom_height_var, 12.0),
        )

    def _canvas_size(self) -> tuple[int, int]:
        """What Canvas means: the size the window already has.

        Unless the map is asked to fill the sheet, in which case the sheet
        takes the map's own proportions. A 2:1 world on a 4:3 canvas is
        letterboxed, and that bar is sheet the map never reaches rather than
        margin -- no margin setting can remove it, only a sheet of the right
        shape can. The margin and the shape go together, which is why this
        also tells the renderer to bleed.
        """
        width = max(REFERENCE_WIDTH, self._canvas.winfo_width())
        height = max(REFERENCE_HEIGHT, self._canvas.winfo_height())

        bleed = bool(self._edge_to_edge_var.get())
        renderer = getattr(self, "renderer", None)
        if renderer is not None:
            renderer.edge_to_edge = bleed
        if not bleed or renderer is None:
            return (width, height)

        aspect = renderer.scene_aspect()
        if aspect is None:
            # Nothing drawn yet, so nothing to take the shape of. The sheet
            # asked for is still a sheet.
            return (width, height)

        # Keep the longer edge asked for, so "about this big" stays about that
        # big whichever way the map is turned.
        longest = max(width, height)
        if aspect >= 1:
            return (longest, max(1, round(longest / aspect)))
        return (max(1, round(longest * aspect)), longest)

    def _export_dimensions(self) -> tuple[int, int]:
        """Pixels, for the PNG and for the SVG viewport."""
        return self._page_spec().pixel_size(*self._canvas_size())

    def _export_points(self) -> tuple[float, float]:
        """Points, for the PDF. A different question from `_export_dimensions`,
        and answering it with the same number was the bug that made every A4
        export a page 34.4 x 48.7 inches."""
        return self._page_spec().point_size(*self._canvas_size())

    def _refresh_page_cost(self) -> None:
        """What the chosen page costs, under the controls that chose it.

        A bitmap has a size somebody can run out of and a PDF does not, so the
        line says which of the two it is describing.
        """
        spec = self._page_spec()
        canvas = self._canvas_size()
        detail = spec.describe(*canvas)
        if spec.exceeds_bitmap_limit(*canvas):
            detail += " — too large for PNG; SVG and PDF have no pixels to run out of"
        self._page_cost_var.set(detail)
        # The ratio, beside the two fields that make it, so a reader asking for
        # 5:3 can see whether they got it without doing the division.
        label = getattr(self, "_custom_aspect_label", None)
        if label is not None:
            aspect = spec.custom_aspect_description
            label.configure(text=f"{aspect} · turns with neither orientation" if aspect else "")
