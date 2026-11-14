"""About, Settings, and saving the current look as a preset.

A mixin for `MainWindow`: the methods read and write the window's own state.
"""

from __future__ import annotations

import tkinter as tk
from copy import deepcopy
from tkinter import messagebox, simpledialog

from hipparchus.application.presets import ArtisticPreset, preset_names
from hipparchus.application.style_catalogue import seeded_name, validate_name
from hipparchus.core.settings_store import UserSettings
from hipparchus.ui.about_window import AboutWindow
from hipparchus.ui.settings_window import SettingsWindow


class PreferencesMixin:
    """About, Settings, and saving the current look as a preset."""

    def _open_about(self) -> None:
        """What this is, and what it owes. Reachable whenever it is wanted."""
        self._about_window().show()

    def _about_window(self) -> AboutWindow:
        if self._about is None:
            self._about = AboutWindow(
                self._root,
                show_on_launch=lambda: self._settings.show_about_on_launch,
            )
        return self._about

    def _show_about_at_launch(self) -> None:
        """The splash, once, before anything else asks for attention."""
        self._about_window().show_on_launch_if_wanted()

    def _open_settings(self) -> None:
        """Preferences, at ⌘, where they belong."""
        if self._settings_window is None:
            self._settings_window = SettingsWindow(
                self._root,
                config=self.config,
                settings=lambda: self._settings,
                on_change=self._apply_settings,
                on_clear_cache=self._clear_cache,
                cache_summary=lambda: self._status.cache,
            )
        self._settings_window.show()

    def _apply_settings(self, settings: UserSettings) -> None:
        """Adopt a preference the moment it changes, and write it down.

        No Apply button: a preferences window with a commit step invites the
        state where what you see and what the application is using are
        different things.
        """
        previous, self._settings = self._settings, settings
        try:
            self._settings_store.save(settings)
        except OSError as exc:  # noqa: BLE001
            self._logger.warning("could not save settings: %s", exc)

        self.controller.data_source_manager.set_overpass_settings(
            requests_per_second=settings.provider_rps_limit
        )
        if hasattr(self.renderer, "device_scale"):
            self.renderer.device_scale = settings.device_scale
        if hasattr(self.renderer, "set_label_font_family"):
            self.renderer.set_label_font_family(settings.label_font_family)
        if hasattr(self.renderer, "set_label_font_size"):
            self.renderer.set_label_font_size(settings.label_font_size)

        if settings.theme_mode != previous.theme_mode:
            self._theme_mode = settings.theme_mode
            self._apply_theme()
        # The label setters only mark the picture cache dirty, so without this a
        # font change sits invisible until the next fetch.
        self._schedule_redraw()

    def _clear_cache(self) -> None:
        """Empty the cache, and say what that came to."""
        try:
            removed = self.controller.data_source_manager.clear_cache()
        except Exception as exc:  # noqa: BLE001
            self._status.set_message(f"Could not clear the cache: {exc}", error=True)
            return
        self._status.set_cache("empty")
        self._status.set_message(
            f"Cache cleared ({removed} entries)" if removed else "Cache cleared"
        )

    def _canvas_surround_color(self) -> str:
        """Colour for the preview canvas outside the rendered image.

        The render is aspect-fitted, so bare canvas shows around it. Matching
        the scene's ground keeps that margin continuous with the map instead of
        ringing a dark preset in light grey. Falls back to the theme before any
        scene exists.
        """
        scene = getattr(self, "_current_scene", None)
        if scene is not None:
            return scene.background.to_hex()
        return "#2b2b2b" if self._theme_mode == "dark" else "#f5f5f5"

    def _save_current_as_preset(self) -> None:
        """Ask for a name, seeded with the likely one, and refuse a bad one.

        The commonest save is a variation on the style being looked at, so the
        box already contains it; saving over your own keeps its name, because
        that is how a style gets tuned.
        """
        catalogue = self._catalogue()
        current = self._preset_var.get()
        suggested = seeded_name(current, is_custom=catalogue.kind_of(current) == "custom")

        name = simpledialog.askstring(
            "Save this style",
            "It will appear in All styles, and in the Mac app — the two share this file.",
            initialvalue=suggested,
            parent=self._root,
        )
        if name is None:
            return

        refusal = validate_name(
            name, builtin=tuple(preset_names()), existing=tuple(self._custom_presets)
        )
        if refusal is not None:
            messagebox.showinfo("That name will not do", refusal)
            return

        name = name.strip()
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
        self._status.set_message(f"Saved the style “{name}”")

    def _refresh_preset_menu(self) -> None:
        """Built-in, then anything plugins brought, then your own — separated,
        because "which of these can I delete?" is a question the list should
        answer without being asked."""
        catalogue = self._catalogue()
        menu = self._preset_menu["menu"]
        menu.delete(0, "end")
        first = True
        for group in (catalogue.builtin, catalogue.plugin, catalogue.custom):
            if not group:
                continue
            if not first:
                menu.add_separator()
            for name in group:
                menu.add_command(label=name, command=tk._setit(self._preset_var, name))
            first = False
