"""The session: restoring it, recording changes for undo, saving it on close.

A mixin for `MainWindow`: the methods read and write the window's own state.
"""

from __future__ import annotations

import tkinter as tk

from hipparchus.application import session_edit
from hipparchus.application.quality import quality_label_for, quality_mode_key
from hipparchus.application.session import Area, Session
from hipparchus.application.session_history import SessionHistory
from hipparchus.ui import menubar
from hipparchus.ui.projection_choices import PROJECTION_CHOICES


class SessionMixin:
    """The session: restoring it, recording changes for undo, saving it on close."""

    # -- the session, and undo ------------------------------------------------

    def _restore_session(self) -> None:
        """Open where you left off.

        A saved session is adopted before the history starts, so the state it
        restores is the beginning rather than something ⌘Z can undo into.
        """
        saved = Session.load(self.config.session_file)
        if saved != Session():
            self._apply_session(saved)
        self._history = SessionHistory(self.current_session())
        self._refresh_undo_menu()

    def _watch_for_changes(self) -> None:
        """Notice the choices that change through a variable rather than a call.

        The preset, the palette, the quality and the four coordinates are all
        written from several places — a saved place, a search result, a drawn
        area — and a trace catches every one of them without each having to
        remember to say so.
        """
        for var in (
            self._preset_var,
            self._palette_var,
            self._quality_var,
            *self._aoi_vars.values(),
        ):
            var.trace_add("write", lambda *_: self._record())


    def current_session(self) -> Session:
        """Every choice the window holds, as one value.

        Read rather than tracked, so it cannot drift from what is on screen.
        Pan, zoom and rotation are deliberately absent: they frame the screen,
        never the file.
        """
        settings: dict[str, float] = {}
        choices: dict[str, str] = {}
        for definition in self.source_stack.definitions:
            for setting in self.source_stack.settings_for(definition.source_id):
                field = f"{definition.source_id}.{setting.key}"
                if isinstance(setting.value, bool):
                    # Not a number, and not a plain choice either: `str(True)`
                    # would come back as the *string* "True", which is still
                    # truthy read back as `bool("True")` -- restoring "off"
                    # would silently leave the setting on. Restored explicitly
                    # in `_apply_session`, keyed on the same `kind`.
                    choices[field] = "true" if setting.value else "false"
                elif isinstance(setting.value, (int, float)):
                    settings[field] = float(setting.value)
                else:
                    choices[field] = str(setting.value)

        return Session(
            area=Area(*self._current_aoi_values()),
            place_name=self._location_preset_var.get(),
            enabled_sources=self.source_stack.enabled_ids(),
            source_paths={
                definition.source_id: self.source_stack.path(definition.source_id)
                for definition in self.source_stack.definitions
                if self.source_stack.path(definition.source_id)
            },
            source_settings=settings,
            source_choices=choices,
            preset_name=self._preset_var.get(),
            palette_name=self._palette_var.get(),
            quality_key=quality_mode_key(self._quality_var.get()),
            projection_key=self._projection_var.get(),
            edge_to_edge=bool(self._edge_to_edge_var.get()),
            hidden_layers=tuple(
                layer_id
                for layer_id, var in self._layer_visibility_vars.items()
                if not bool(var.get())
            ),
        )

    def _record(self) -> None:
        """Note whatever just changed, if anything did.

        One place rather than a call at every change point that has to remember
        what to call itself: the name comes from comparing two sessions, which
        is a rule that can be checked without a window.
        """
        if self._restoring:
            return
        after = self.current_session()
        described = session_edit.describe(self._history.current.session, after)
        if described is None:
            return
        announcement = session_edit.announcement_for(described, after)
        if announcement is not None:
            self._status.set_message(announcement)
        self._history.record(
            after, described.action, coalescing_key=described.coalescing_key
        )
        self._refresh_undo_menu()
        self._refresh_render_button()

    def _refresh_undo_menu(self) -> None:
        """Say what ⌘Z would take back, rather than only that it exists."""
        if self._menubar is None:
            return
        undo_name = self._history.undo_action_name
        redo_name = self._history.redo_action_name
        menubar.set_label(
            self._menubar, "undo",
            f"Undo {undo_name}" if undo_name else "Undo",
            enabled=self._history.can_undo,
        )
        menubar.set_label(
            self._menubar, "redo",
            f"Redo {redo_name}" if redo_name else "Redo",
            enabled=self._history.can_redo,
        )

    def _on_undo(self) -> None:
        self._travel(self._history.undo())

    def _on_redo(self) -> None:
        self._travel(self._history.redo())

    def _travel(self, snapshot) -> None:
        if snapshot is None:
            return
        self._apply_session(snapshot.session)
        scene = self._history.scene(snapshot.scene_token)
        if scene is not None:
            self._apply_scene(scene, "undo")
        elif snapshot.scene_token is not None:
            # Honest rather than silent: undo never re-fetches, so a map that
            # has been let go stays gone until Render map draws it again.
            self._status.set_message("That map is no longer held — press Render map to draw it again.")
        self._refresh_undo_menu()

    def _apply_session(self, session: Session) -> None:
        """Put a remembered set of choices back on screen.

        Guarded, because writing to the variables fires the very traces that
        record changes, and a restore is not an edit.
        """
        self._restoring = True
        try:
            if session.area.bbox is not None:
                self._set_aoi(*session.area.bbox)
            self._location_preset_var.set(session.place_name)
            for definition in self.source_stack.definitions:
                self.source_stack.set_enabled(
                    definition.source_id, definition.source_id in session.enabled_sources
                )
                path = session.source_paths.get(definition.source_id, "")
                if path:
                    self.source_stack.set_path(definition.source_id, path)
            for field, value in {**session.source_settings, **session.source_choices}.items():
                source_id, _, key = field.rpartition(".")
                if not source_id:
                    continue
                definition = self.source_stack.definition(source_id)
                setting = definition.setting(key) if definition is not None else None
                if setting is not None and setting.kind == "boolean":
                    # Session storage only ever has strings; recover the type
                    # `current_session` encoded rather than pass "false" on
                    # to a provider field typed `bool`.
                    value = str(value).strip().lower() == "true"
                self.source_stack.set_setting(source_id, key, value)
            self._preset_var.set(session.preset_name)
            self._palette_var.set(session.palette_name)
            self._quality_var.set(quality_label_for(session.quality_key))
            # An unknown mode name — a hand-edited file, or one since renamed —
            # reads as Automatic rather than throwing the session away.
            restored = session.projection_key if session.projection_key in PROJECTION_CHOICES else ""
            self._projection_var.set(restored)
            self._projection_label_var.set(PROJECTION_CHOICES[restored])
            self._edge_to_edge_var.set(session.edge_to_edge)
            for layer_id, var in self._layer_visibility_vars.items():
                var.set(layer_id not in session.hidden_layers)

            if self._sources_panel is not None:
                self._sources_panel.rebuild()
            if self._style_picker is not None:
                self._style_picker.set_selected(session.preset_name)
            self._rebuild_saved_places()
            self._refresh_minimap()
            self._on_visibility_changed()
        finally:
            self._restoring = False

    def _save_session(self) -> None:
        try:
            self.current_session().save(self.config.session_file)
        except OSError as exc:  # noqa: BLE001
            self._logger.warning("could not save the session: %s", exc)

    def _on_close(self) -> None:
        self._save_session()
        # The callback pump reschedules itself every 60 ms; destroying the
        # interpreter with a tick pending prints a Tcl error at the moment of
        # quitting, which is the worst moment to look broken.
        for job in (self._queue_job, self._redraw_job):
            if job is not None:
                try:
                    self._root.after_cancel(job)
                except tk.TclError:
                    pass
        self._queue_job = None
        self._redraw_job = None
        if self._owns_root:
            self._root.destroy()
        else:
            # Somebody else's root. Take this window's widgets off it and leave
            # it standing — `gui_support.reset_root` does the rest.
            for child in self._root.winfo_children():
                child.destroy()
