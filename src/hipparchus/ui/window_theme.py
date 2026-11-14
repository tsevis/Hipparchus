"""Light and dark: restyling the window when the theme changes.

A mixin for `MainWindow`: the methods read and write the window's own state.
"""

from __future__ import annotations

import platform
from tkinter import ttk

from hipparchus.ui import icons, theme


class ThemeMixin:
    """Light and dark: restyling the window when the theme changes."""

    def _restyle_icons(self) -> None:
        """Keep the drawn icons in step with the current appearance."""
        palette = theme.palette(self._theme_mode)
        icons.restyle_all(
            colour=palette.text,
            background=palette.panel_alt,
            hover=palette.button_active,
        )
        if getattr(self, "_locator_window", None) is not None:
            self._locator_window.restyle()
        self._refresh_minimap()

    def _toggle_theme(self) -> None:
        # The title does not carry the appearance. Which mode you are in is
        # visible in every pixel of the window; saying it again in the title bar
        # is furniture, and it made the window's name change under anything
        # that reads it.
        self._theme_mode = "dark" if self._theme_mode == "light" else "light"
        self._apply_theme()

    def _apply_theme(self) -> None:
        # Said once, here, so everything drawn later — a swatch border, a
        # tooltip's ground, an icon — reads the same appearance rather than
        # each keeping its own copy of which one is in force.
        theme.set_mode(self._theme_mode)
        style = ttk.Style(master=self._root)
        self._setup_platform_theme(style)
        self._restyle_icons()
        if platform.system() == "Darwin":
            self._apply_macos_aqua_appearance()
            return

        palette = theme.palette(self._theme_mode)
        self._root.tk_setPalette(
            background=palette.bg,
            foreground=palette.text,
            activeBackground=palette.button_active,
            activeForeground=palette.text,
            highlightBackground=palette.border,
            highlightColor=palette.select,
            selectBackground=palette.select,
            selectForeground=palette.select_text,
        )
        self._root.option_add("*Menu.background", palette.panel_alt)
        self._root.option_add("*Menu.foreground", palette.text)
        self._root.option_add("*Menu.activeBackground", palette.button_active)
        self._root.option_add("*Menu.activeForeground", palette.text)
        self._root.option_add("*Menu.selectColor", palette.select)

        style.configure(".", background=palette.bg, foreground=palette.text)
        style.configure("TFrame", background=palette.bg)
        style.configure("TLabel", background=palette.bg, foreground=palette.text)
        style.configure(
            "TButton",
            background=palette.button,
            foreground=palette.text,
            bordercolor=palette.border,
            lightcolor=palette.button_active,
            darkcolor=palette.border,
            focuscolor=palette.select,
            padding=5,
        )
        style.configure(
            "TMenubutton",
            background=palette.button,
            foreground=palette.text,
            bordercolor=palette.border,
            arrowcolor=palette.text,
            focuscolor=palette.select,
            padding=4,
        )
        style.configure("TCheckbutton", background=palette.bg, foreground=palette.text)
        style.configure(
            "TEntry",
            fieldbackground=palette.field,
            foreground=palette.field_text,
            insertcolor=palette.field_text,
            bordercolor=palette.border,
            lightcolor=palette.button_active,
            darkcolor=palette.border,
        )
        style.configure(
            "TCombobox",
            fieldbackground=palette.field,
            foreground=palette.field_text,
            background=palette.button,
            bordercolor=palette.border,
            arrowcolor=palette.text,
        )
        style.configure(
            "TSpinbox",
            fieldbackground=palette.field,
            foreground=palette.field_text,
            background=palette.button,
            bordercolor=palette.border,
            arrowcolor=palette.text,
        )
        style.configure("Horizontal.TScale", background=palette.bg, troughcolor=palette.panel_alt, sliderrelief="flat")
        style.configure("TSeparator", background=palette.border)
        style.configure("Vertical.TScrollbar", background=palette.button, troughcolor=palette.panel, arrowcolor=palette.text)
        style.configure("Horizontal.TScrollbar", background=palette.button, troughcolor=palette.panel, arrowcolor=palette.text)
        style.map(
            "TButton",
            background=[
                ("disabled", palette.panel_alt),
                ("active", palette.button_active),
                ("pressed", palette.select),
            ],
            foreground=[("disabled", palette.muted), ("active", palette.text)],
        )
        style.map(
            "TMenubutton",
            background=[
                ("disabled", palette.panel_alt),
                ("active", palette.button_active),
                ("pressed", palette.select),
            ],
            foreground=[("disabled", palette.muted), ("active", palette.text)],
            arrowcolor=[("disabled", palette.muted), ("active", palette.text)],
        )
        style.map(
            "TCheckbutton",
            background=[("active", palette.bg)],
            foreground=[("disabled", palette.muted), ("active", palette.text)],
            indicatorcolor=[("selected", palette.select), ("!selected", palette.panel_alt)],
        )
        style.map(
            "TEntry",
            fieldbackground=[("disabled", palette.panel_alt), ("readonly", palette.panel_alt)],
            foreground=[("disabled", palette.muted), ("readonly", palette.text)],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette.field), ("disabled", palette.panel_alt)],
            foreground=[("readonly", palette.field_text), ("disabled", palette.muted)],
            selectbackground=[("readonly", palette.select)],
            selectforeground=[("readonly", palette.select_text)],
        )
        style.map(
            "TSpinbox",
            fieldbackground=[("disabled", palette.panel_alt)],
            foreground=[("disabled", palette.muted)],
        )

        for canvas_name in ("_left_sidebar_canvas", "_right_sidebar_canvas"):
            if hasattr(self, canvas_name):
                canvas = getattr(self, canvas_name)
                canvas.configure(background=palette.bg)
        if hasattr(self, "_canvas"):
            self._canvas.configure(background=palette.canvas_bg, highlightbackground=palette.canvas_border)

    def _apply_macos_aqua_appearance(self) -> None:
        """Switch native macOS Aqua appearance without overriding ttk colors."""
        # Per window, not per application: a Toplevel opened later keeps the
        # appearance it was born with, which is why the splash and the settings
        # window came up light in front of a dark main window.
        for held in (self._root, self._about, self._settings_window, self._locator_window):
            opened = getattr(held, "_window", held) if held is not None else None
            if opened is not None:
                theme.follow_appearance(opened, self._theme_mode)

        sidebar_bg = "#1e1e1e" if self._theme_mode == "dark" else "#f5f5f5"
        canvas_border = "#555555" if self._theme_mode == "dark" else "#d0d0d0"
        for canvas_name in ("_left_sidebar_canvas", "_right_sidebar_canvas"):
            if hasattr(self, canvas_name):
                canvas = getattr(self, canvas_name)
                canvas.configure(background=sidebar_bg)
        if hasattr(self, "_canvas"):
            self._canvas.configure(background=self._canvas_surround_color(), highlightbackground=canvas_border)
