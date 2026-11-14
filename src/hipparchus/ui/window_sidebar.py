"""The right sidebar: style picker, saved styles and the plugin summary.

A mixin for `MainWindow`: the methods read and write the window's own state.
"""

from __future__ import annotations

import platform
from tkinter import messagebox, ttk

from hipparchus.application.palettes import names as palette_names
from hipparchus.application.presets import preset_names
from hipparchus.application.quality import quality_menu_labels
from hipparchus.application.style_catalogue import Catalogue
from hipparchus.ui import theme, tooltip
from hipparchus.ui.disclosure import Disclosure
from hipparchus.ui.icons import IconButton
from hipparchus.ui.panels import LayersPanel, SourcesPanel, StylePicker
from hipparchus.ui.projection_choices import PROJECTION_CHOICES


class SidebarMixin:
    """The right sidebar: style picker, saved styles and the plugin summary."""

    def _build_right_sidebar(self, parent: ttk.Frame) -> None:
        sources_section = Disclosure(parent, "Sources", hint="they stack")
        self._sources_panel = SourcesPanel(
            sources_section.body,
            self.source_stack,
            on_toggle=self._on_source_toggled,
            on_setting=self._on_source_setting_changed,
            on_choose_path=self._choose_source_path,
            on_download=self._download_natural_earth,
            file_reason=self._file_reason,
        )

        self._layers_panel = LayersPanel(parent, on_visibility=self._on_layer_visibility_changed)
        # The layer panel owns visibility now, so the renderer reads its vars.
        self._layer_visibility_vars = self._layers_panel.visibility_vars()

        style_section = Disclosure(parent, "Style", hint="see it, don't read it")
        style_body = style_section.body
        # All sixteen. With nothing to scroll there is no reason to decide for
        # someone which looks they are allowed to see.
        self._style_picker = StylePicker(
            style_body, tuple(preset_names()), on_select=self._on_style_selected
        )
        self._style_picker.set_selected(self._preset_var.get())

        # Still here, because a name is the faster way in when you already know
        # which one you want — and because a saved style has no swatch.
        row = ttk.Frame(style_body)
        row.pack(fill="x", pady=(6, 0))
        ttk.Label(row, text="All styles", font=theme.font("caption")).pack(side="left")
        self._preset_menu = ttk.OptionMenu(row, self._preset_var, self._preset_var.get(), *self._preset_options)
        self._preset_menu.pack(side="left", fill="x", expand=True, padx=(6, 0))

        row = ttk.Frame(style_body)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text="Palette", font=theme.font("caption")).pack(side="left")
        self._palette_menu = ttk.OptionMenu(
            row, self._palette_var, self._palette_var.get(), *palette_names()
        )
        self._palette_menu.pack(side="left", fill="x", expand=True, padx=(6, 0))
        tooltip.attach(
            row,
            "Colour, separate from the style. A preset is a whole sheet — "
            "geometry, weights and colour together — so the same map in other "
            "colours was not a thing you could ask for. A palette replaces the "
            "colour and keeps the geometry. Takes effect on the next Render "
            "map, as a preset does; the fetch behind it is cached, so it costs "
            "no network.",
        )

        # Quality belongs with Style, not in the toolbar: a preset says what the
        # map should look like, quality says how much work to spend getting
        # there, and the second question only arises once the first is answered.
        row = ttk.Frame(style_body)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text="Quality", font=theme.font("caption")).pack(side="left")
        quality_labels = quality_menu_labels()
        self._quality_menu = ttk.OptionMenu(row, self._quality_var, self._quality_var.get(), *quality_labels)
        self._quality_menu.pack(side="left", fill="x", expand=True, padx=(6, 0))
        tooltip.attach(
            row,
            "A preset says what the map should look like; quality says how much "
            "work to spend getting there.",
        )

        # How the round earth is flattened. Automatic is the honest choice and
        # stays the default; it promotes a continent or a world to Equal Earth,
        # an oval with curved edges, which is right for area and wrong for
        # anyone who wanted a rectangle.
        row = ttk.Frame(style_body)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text="Projection", font=theme.font("caption")).pack(side="left")
        self._projection_menu = ttk.OptionMenu(
            row,
            self._projection_label_var,
            self._projection_label_var.get(),
            *PROJECTION_CHOICES.values(),
            command=self._on_projection_chosen,
        )
        self._projection_menu.pack(side="left", fill="x", expand=True, padx=(6, 0))
        tooltip.attach(
            row,
            "How the round earth is flattened. Automatic lets the frame choose, "
            "which draws a whole world as an Equal Earth oval. Rectangular "
            "draws it as a plain rectangle, plate carree, with the poles as "
            "lines — the whole earth edge to edge, at the cost of stretching "
            "the high latitudes.",
        )

        row = ttk.Frame(style_body)
        row.pack(fill="x", pady=(4, 0))
        ttk.Checkbutton(
            row, text="Relief over buildings", variable=self._relief_over_buildings_var,
        ).pack(side="left")
        tooltip.attach(
            row,
            "Lifts the hillshade above the built environment instead of under "
            "it, stopping just short of the labels. Off draws relief the "
            "ordinary way, beneath streets and buildings. Needs Hillshade "
            "ticked on the Elevation source to draw anything.",
        )

        self._build_saved_styles(style_body)

        ttk.Separator(parent, orient="horizontal").pack(fill="x", pady=12)
        self._build_page_panel(parent)
        self._build_diagnostics(parent)

    def _build_saved_styles(self, parent: ttk.Frame) -> None:
        """Keeping a tuned style, and letting go of one.

        The sixteen built-ins are code and cannot be edited. Everything the eye
        is actually for — nudging a colour, turning the illumination up — was
        lost at the next launch, which made the tuning pointless.
        """
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(6, 0))
        IconButton(
            row, "save", command=self._save_current_as_preset, size=20,
            tooltip="Keep the current style, with its derivation sizes, under a name of your own.",
        ).pack(side="left", padx=(0, 4))
        ttk.Button(row, text="Save this style…", command=self._save_current_as_preset).pack(
            side="left", fill="x", expand=True
        )

        self._delete_row = ttk.Frame(parent)
        IconButton(
            self._delete_row, "trash", command=self._delete_current_preset, size=20,
            tooltip="Remove this saved style from presets.json.",
        ).pack(side="left", padx=(0, 4))
        self._delete_button = ttk.Button(
            self._delete_row, text="Delete", command=self._delete_current_preset
        )
        self._delete_button.pack(side="left", fill="x", expand=True)
        self._refresh_delete_button()

        self._build_plugin_summary(parent)

    def _catalogue(self) -> Catalogue:
        """Which styles exist, and where each came from."""
        return Catalogue(
            builtin=tuple(preset_names()),
            plugin=(),
            custom=tuple(sorted(self._custom_presets)),
        )

    def _refresh_delete_button(self) -> None:
        """Offered only for a style of your own — a delete that cannot work is
        worse than no delete at all."""
        name = self._preset_var.get()
        if self._catalogue().can_delete(name):
            self._delete_button.configure(text=f"Delete “{name}”")
            self._delete_row.pack(fill="x", pady=(4, 0))
        else:
            self._delete_row.pack_forget()

    def _delete_current_preset(self) -> None:
        """Asked before, not regretted after.

        Deleting a saved style rewrites `presets.json`. There is no undo for a
        file, and the only copy of a style someone spent an evening tuning can
        go on one stray click.
        """
        name = self._preset_var.get()
        if not self._catalogue().can_delete(name):
            return
        if not messagebox.askyesno(
            "Delete this style?",
            f"Delete “{name}”?\n\nThis removes it from presets.json. It cannot be undone.",
            icon="warning",
            default="no",
        ):
            return

        self._custom_presets.pop(name, None)
        try:
            self._preset_store.save(self._custom_presets)
        except OSError as exc:
            messagebox.showerror("Could not delete", f"presets.json could not be written:\n{exc}")
            return

        self._preset_options = sorted({*preset_names(), *self._custom_presets})
        self._refresh_preset_menu()
        self._preset_var.set(self.default_preset.name)
        self._status.set_message(f"Deleted the style “{name}”")

    def _build_plugin_summary(self, parent: ttk.Frame) -> None:
        """What loaded, and what did not.

        A plugin that failed silently is indistinguishable from one that was
        never installed. The loader has recorded both since it was written and
        the window has never shown either.
        """
        loader_errors = self.plugin_load_errors
        if not self.loaded_plugins and not loader_errors:
            return

        ttk.Label(
            parent,
            text=f"Plugins ({len(self.loaded_plugins)})",
            font=theme.font("caption"),
        ).pack(anchor="w", pady=(10, 2))

        for plugin in self.loaded_plugins:
            row = ttk.Frame(parent)
            row.pack(fill="x")
            IconButton(
                row, "tick-circle", command=lambda: None, size=14,
                colour=theme.current().success,
                background=theme.current().bg, hover=theme.current().bg,
            ).pack(side="left", padx=(0, 4))
            ttk.Label(row, text=plugin.name, font=theme.font("caption")).pack(side="left")

        for note in loader_errors:
            row = ttk.Frame(parent)
            row.pack(fill="x")
            IconButton(
                row, "warning", command=lambda: None, size=14,
                colour=theme.current().warning,
                background=theme.current().bg, hover=theme.current().bg,
            ).pack(side="left", padx=(0, 4), anchor="n")
            ttk.Label(
                row, text=note, font=theme.font("caption2"), wraplength=210, justify="left"
            ).pack(side="left", fill="x", expand=True)

        folder = ttk.Frame(parent)
        folder.pack(fill="x", pady=(4, 0))
        IconButton(
            folder, "folder", command=self._reveal_plugin_folder, size=18,
            tooltip=str(self.config.plugins_dir),
        ).pack(side="left", padx=(0, 4))
        ttk.Button(
            folder, text="Show plugins folder", command=self._reveal_plugin_folder
        ).pack(side="left", fill="x", expand=True)

    def _reveal_plugin_folder(self) -> None:
        """Open the folder, creating it the first time so there is one to open."""
        import subprocess

        path = self.config.plugins_dir
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._status.set_message(f"Could not create {path}: {exc}", error=True)
            return
        opener = {"Darwin": "open", "Windows": "explorer"}.get(platform.system(), "xdg-open")
        try:
            subprocess.run([opener, str(path)], check=False)  # noqa: S603
        except OSError as exc:
            self._status.set_message(f"Could not open {path}: {exc}", error=True)
