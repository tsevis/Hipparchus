# Working on Hipparchus

## GUI tests must not open windows

This is a Tkinter application. A test that builds a widget builds a **real
window on the machine running the suite** — and on macOS creating one bounces an
icon in the Dock, can flash on screen, and `focus_force` pulls the keyboard out
of whatever the person is typing in. The suite gets run while somebody is
working. Nothing in it is worth interrupting them for.

**Every test that creates a `tk.Tk()`, a `Toplevel`, or calls
`HipparchusApp.bootstrap()` must call `require_gui()` from `tests/gui_support.py`
first.** It skips unless asked:

```bash
pytest                             # silent; the default
HIPPARCHUS_GUI_TESTS=1 pytest      # opens real windows, deliberately
```

**Turning the flag on puts windows on the screen, and there is no way around it
on macOS.** `gui_support.show_offscreen` moves a window to a negative
coordinate, which the window server overrides by pulling it back onto the
display. It reduces flashing; it does not prevent windows.

**Never run the GUI suite, and never launch the application, without asking
first — and never offer that command to the user as a harmless way to check
something.** It is not harmless. If the interface needs looking at, say so and
let them choose the moment.

## Where the rules live

The window is wiring. Anything that can be decided without a widget is decided
in `src/hipparchus/application/` and tested there — `session_history` decides
what undo restores, `session_edit` what the Edit menu calls it, `readiness` why
Render map will not work, `world_view` where the locator is looking. A rule kept
in widget code can only be checked by a person opening the panel and looking at
it, which on this project means it cannot be checked at all.

## The working files

The plans, briefs and reviews this project is built from live in `documents/`,
which is **deliberately not in the repository** — it is ignored, and the files
exist only on the author's machine. They are the thinking rather than the
product, and several of them describe unreleased work on the macOS side.

If you are working here and that directory is present, read it: the current
working file records each phase as it lands, **including what went wrong**, and
the mistakes are the part that has repeatedly turned out to be worth keeping.
If it is absent, this file and the repository are the whole of what you have.

## Tests: born red, or not born (CRITICAL)

**Never write a test that passes the first time you run it.** If it has not
failed, it has not tested anything. Delete it.

The red run is the only thing that proves the test can speak. Skipping it
produces documentation written with `assert`, paid for on every run, forever.

Before writing any test, answer in one sentence: **what bug does this catch that
nothing else catches?** No answer → no test. Coverage is a diagnostic, never a
target.

**Forbidden outright:** tests that check markdown against code; tests that sweep
the repository (`rglob`/`os.walk`/`glob`/`iterdir` — lint rules in a test
costume, 31–96s each, they belong in ruff or a pre-commit hook); tests that
cannot fail in the environment that runs them (anything that skips in CI).
