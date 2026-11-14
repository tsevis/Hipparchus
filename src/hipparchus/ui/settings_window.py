"""Preferences, at ⌘, where they belong.

There has been a `settings.json` for a while — the cache ceiling, the rate this
asks shared services at — and no way to see or change it without a text editor.
A file the application reads and the person using it cannot reach is a setting
in name only.

Everything here answers "how does the application behave", not "what does this
map look like". That is why it is a window rather than another section of the
rail beside the sources: the rail is about the map in front of you, and seven
sections of things that are not made it hard to find the ones that are.

**No Apply button.** A change takes effect when it is made and is written to the
file then. A preferences window with a commit step invites the state where what
you see and what the application is using are different things.
"""

from __future__ import annotations

import platform
import subprocess
import tkinter as tk
from tkinter import ttk
from typing import Callable

from hipparchus.core.settings_store import UserSettings, storage_locations
from hipparchus.ui import theme
from hipparchus.ui.icons import IconButton

WIDTH = 460

#: The picker offers every family the system reports, but this curated run —
#: the bundled multilingual default first — is what it falls back to when Skia
#: cannot be asked for the system list.
LABEL_FACES = ("Noto Sans", "Arial", "Helvetica", "Verdana", "Times", "Courier")


def font_choices() -> tuple[str, ...]:
    """Families for the label-face dropdown: the bundled multilingual default
    first, then every family the system reports, de-duplicated."""
    try:
        from hipparchus.rendering.skia_fonts import (
            DEFAULT_FONT_FAMILY,
            available_font_families,
        )

        families = available_font_families()
    except Exception:  # noqa: BLE001 - no Skia to ask; offer the curated run
        return LABEL_FACES
    if not families:
        return LABEL_FACES
    return (DEFAULT_FONT_FAMILY, *(name for name in families if name != DEFAULT_FONT_FAMILY))


class SettingsWindow:
    """The preferences window, built once and reused."""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        config: object,
        settings: Callable[[], UserSettings],
        on_change: Callable[[UserSettings], None],
        on_clear_cache: Callable[[], None],
        cache_summary: Callable[[], str],
    ) -> None:
        self._parent = parent
        self._config = config
        self._settings = settings
        self._on_change = on_change
        self._on_clear_cache = on_clear_cache
        self._cache_summary = cache_summary
        self._window: tk.Toplevel | None = None
        self._writing = False

    # -- opening --------------------------------------------------------------

    def show(self) -> None:
        if self._window is not None and self._window.winfo_exists():
            self._window.deiconify()
            self._window.lift()
            self._refresh()
            return
        self._build()

    def close(self) -> None:
        if self._window is not None and self._window.winfo_exists():
            self._window.withdraw()

    # -- building -------------------------------------------------------------

    def _build(self) -> None:
        window = tk.Toplevel(self._parent)
        window.title("Settings")
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", self.close)
        window.bind("<Escape>", lambda _e: self.close())
        theme.follow_appearance(window)

        body = ttk.Frame(window, padding=16)
        body.pack(fill="both", expand=True)

        current = self._settings()
        self._vars = {
            "cache": tk.StringVar(value=str(current.cache_size_limit_mb)),
            "rps": tk.StringVar(value=f"{current.provider_rps_limit:g}"),
            "font": tk.StringVar(value=current.label_font_family),
            "size": tk.StringVar(value=str(current.label_font_size)),
            "scale": tk.StringVar(value=f"{current.device_scale:g}"),
            "theme": tk.StringVar(value=current.theme_mode),
            # A StringVar so it shares the one trace every other row uses; a
            # BooleanVar would need a second path through _write for one row.
            "splash": tk.StringVar(value="yes" if current.show_about_on_launch else "no"),
        }

        self._cache_section(body)
        self._services_section(body)
        self._appearance_section(body)
        self._storage_section(body)

        for name, var in self._vars.items():
            var.trace_add("write", lambda *_a, key=name: self._write(key))

        self._window = window
        # Asked *after* the layout has been worked out. Before it, a window with
        # four sections in it reports the height of an empty one and opens
        # clipped: everything below the first section was simply not there.
        window.update_idletasks()
        window.geometry(f"{WIDTH}x{window.winfo_reqheight()}")

    def _section(self, parent: ttk.Frame, title: str) -> ttk.Frame:
        ttk.Label(parent, text=title, font=theme.font("heading")).pack(
            anchor="w", pady=(12, 4)
        )
        frame = ttk.Frame(parent)
        frame.pack(fill="x")
        return frame

    def _footnote(self, parent: ttk.Frame, text: str) -> None:
        """What the setting *does*, not what it is called again."""
        ttk.Label(
            parent, text=text, font=theme.font("caption"), wraplength=WIDTH - 40,
            justify="left", foreground=theme.current().muted,
        ).pack(anchor="w", pady=(2, 0))

    def _cache_section(self, parent: ttk.Frame) -> None:
        frame = self._section(parent, "Cache")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Ceiling", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self._vars["cache"], width=10).pack(side="left")
        ttk.Label(row, text="MB", font=theme.font("caption")).pack(side="left", padx=(4, 0))

        self._cache_state = ttk.Label(frame, font=theme.font("caption"))
        self._cache_state.pack(anchor="w", pady=(4, 0))

        ttk.Button(frame, text="Clear cache now", command=self._clear_cache).pack(
            anchor="w", pady=(4, 0)
        )
        self._footnote(
            parent,
            "The oldest answers are dropped when the cache passes this. Fetching "
            "again is a network round trip, not a loss.",
        )
        self._refresh_cache_state()

    def _services_section(self, parent: ttk.Frame) -> None:
        frame = self._section(parent, "Shared services")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Requests a second", width=16).pack(side="left")
        ttk.Entry(row, textvariable=self._vars["rps"], width=10).pack(side="left")
        self._footnote(
            parent,
            "Overpass runs on donated hardware. One a second is its stated "
            "guidance; a source's own settings can still override this.",
        )

    def _appearance_section(self, parent: ttk.Frame) -> None:
        frame = self._section(parent, "Appearance")

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Theme", width=16).pack(side="left")
        ttk.OptionMenu(
            row, self._vars["theme"], self._vars["theme"].get(), "light", "dark"
        ).pack(side="left")

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Label face", width=16).pack(side="left")
        ttk.Combobox(
            row, textvariable=self._vars["font"], values=font_choices(), width=24
        ).pack(side="left", fill="x", expand=True)

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Label size", width=16).pack(side="left")
        ttk.Spinbox(row, from_=6, to=24, textvariable=self._vars["size"], width=8).pack(side="left")

        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Render scale", width=16).pack(side="left")
        ttk.Spinbox(
            row, from_=1.0, to=4.0, increment=0.5, textvariable=self._vars["scale"], width=8
        ).pack(side="left")

        # The splash carries the licence notice, so turning it off is a real
        # choice and belongs where the other choices are. It used to be a
        # checkbox on the splash itself, which the macOS application does not
        # have; keeping the two front doors identical moved it here rather than
        # deleting it.
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="At launch", width=16).pack(side="left")
        ttk.Checkbutton(
            row, text="Show the About window", variable=self._vars["splash"],
            onvalue="yes", offvalue="no",
        ).pack(side="left")

        self._footnote(
            parent,
            "Labels are drawn into the map, so their face and size are part of "
            "the picture. Render scale trades drawing time for sharpness on a "
            "dense display. The About window is where the data licences are "
            "recorded; it stays reachable from the View menu either way.",
        )

    def _storage_section(self, parent: ttk.Frame) -> None:
        frame = self._section(parent, "Where things are kept")
        for label, path in storage_locations(self._config):
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label, width=16).pack(side="left")
            IconButton(
                row, "folder", command=lambda p=path: reveal(p), size=18,
                tooltip=str(path),
            ).pack(side="left")
            ttk.Label(
                row, text=_shorten(str(path)), font=theme.font("caption2"),
                foreground=theme.current().muted,
            ).pack(side="left", padx=(6, 0))
        self._footnote(
            parent,
            "Preferences and saved styles are shared with the macOS app — the "
            "same files, in the same format.",
        )

    # -- reading and writing --------------------------------------------------

    def _write(self, key: str) -> None:
        """A change takes effect as it is made.

        Clamping happens in the store, so a half-typed number is refused
        quietly rather than becoming a setting.
        """
        if self._writing:
            return
        current = self._settings()
        try:
            if key == "cache":
                changed = current.with_changes(cache_size_limit_mb=int(self._vars["cache"].get()))
            elif key == "rps":
                changed = current.with_changes(provider_rps_limit=float(self._vars["rps"].get()))
            elif key == "font":
                changed = current.with_changes(label_font_family=self._vars["font"].get())
            elif key == "size":
                changed = current.with_changes(label_font_size=int(self._vars["size"].get()))
            elif key == "scale":
                changed = current.with_changes(device_scale=float(self._vars["scale"].get()))
            elif key == "theme":
                changed = current.with_changes(theme_mode=self._vars["theme"].get())
            elif key == "splash":
                changed = current.with_changes(
                    show_about_on_launch=self._vars["splash"].get() == "yes"
                )
            else:
                return
        except (TypeError, ValueError):
            # Mid-edit is not an error; the box simply is not a number yet.
            return
        if changed != current:
            self._on_change(changed)

    def _refresh(self) -> None:
        """Put the file's values back in the boxes, without echoing them out."""
        current = self._settings()
        self._writing = True
        try:
            self._vars["cache"].set(str(current.cache_size_limit_mb))
            self._vars["rps"].set(f"{current.provider_rps_limit:g}")
            self._vars["font"].set(current.label_font_family)
            self._vars["size"].set(str(current.label_font_size))
            self._vars["scale"].set(f"{current.device_scale:g}")
            self._vars["theme"].set(current.theme_mode)
            self._vars["splash"].set("yes" if current.show_about_on_launch else "no")
        finally:
            self._writing = False
        self._refresh_cache_state()

    def _refresh_cache_state(self) -> None:
        summary = self._cache_summary()
        self._cache_state.configure(text=summary or "Nothing cached yet.")

    def _clear_cache(self) -> None:
        self._on_clear_cache()
        self._refresh_cache_state()


def reveal(path) -> None:
    """Open a folder, or the folder holding a file.

    Created first if it is not there, so there is something to open — the
    plugins folder in particular does not exist until something is put in it.
    """
    from pathlib import Path

    target = Path(path)
    folder = target if target.is_dir() else target.parent
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    opener = {"Darwin": "open", "Windows": "explorer"}.get(platform.system(), "xdg-open")
    try:
        subprocess.run([opener, str(folder)], check=False)  # noqa: S603
    except OSError:
        pass


def _shorten(path: str, keep: int = 34) -> str:
    """Enough of a path to recognise, from the end that identifies it."""
    return path if len(path) <= keep else "…" + path[-keep:]
