"""Loading skia, and finding a typeface that can draw a given piece of text."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class SkiaUnavailableError(RuntimeError):
    """Raised when skia-python is required but not installed."""


_SKIA_MODULE: Any | None = None


def _import_skia() -> Any:
    global _SKIA_MODULE
    if _SKIA_MODULE is not None:
        return _SKIA_MODULE
    try:
        import skia  # type: ignore
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise SkiaUnavailableError(
            "skia-python is not installed. Install with: pip install skia-python"
        ) from exc
    _SKIA_MODULE = skia
    return _SKIA_MODULE


# Label font fallback. The default typeface is Latin-only, so a Japanese or
# Korean place name renders as tofu boxes. Skia's font manager can match a
# typeface that covers a specific character; results are cached per 256-point
# Unicode block so the lookup runs a handful of times, not once per label.
_UNSET = object()
_DEFAULT_TYPEFACE: Any = _UNSET
_FALLBACK_TYPEFACES: dict[int, Any] = {}
_FAMILY_TYPEFACES: dict[str, Any] = {}

# Fonts shipped with the app, by family name. Bundling the default means a
# machine without it still draws labels in a known face, the same face on every
# platform, rather than whatever the OS happens to call default. Noto Sans
# covers Latin, Greek and Cyrillic; the per-block fallback below reaches the OS
# for the scripts it does not, so a Japanese or Arabic name still renders.
_FONTS_DIR = Path(__file__).resolve().parents[1] / "ui" / "assets" / "fonts"
_BUNDLED_FONT_FILES: dict[str, str] = {"Noto Sans": "NotoSans-Regular.ttf"}
DEFAULT_FONT_FAMILY = "Noto Sans"
_BUNDLED_TYPEFACES: dict[str, Any] = {}


def _bundled_typeface(family: str) -> Any:
    """The shipped typeface for a family, or None if it is not one we ship."""
    if family not in _BUNDLED_FONT_FILES:
        return None
    if family not in _BUNDLED_TYPEFACES:
        skia = _import_skia()
        path = _FONTS_DIR / _BUNDLED_FONT_FILES[family]
        try:
            _BUNDLED_TYPEFACES[family] = (
                skia.Typeface.MakeFromFile(str(path)) if path.exists() else None
            )
        except Exception:  # noqa: BLE001 - a missing font is not a crash
            _BUNDLED_TYPEFACES[family] = None
    return _BUNDLED_TYPEFACES[family]


def available_font_families() -> tuple[str, ...]:
    """Every family the picker may offer: the bundled ones and the system's.

    Sorted and de-duplicated. Degrades to just the bundled families when Skia is
    unavailable, so the dropdown is never empty.
    """
    families = set(_BUNDLED_FONT_FILES)
    try:
        skia = _import_skia()
        manager = skia.FontMgr()
        for index in range(manager.countFamilies()):
            name = manager.getFamilyName(index)
            if name:
                families.add(name)
    except Exception:  # noqa: BLE001 - no Skia, no system list
        pass
    return tuple(sorted(families))


def _family_typeface(family: str) -> Any:
    """Return the typeface for a requested family, or None to use the default.

    A bundled family is loaded from its shipped file; otherwise the system is
    asked. None covers both "nothing requested" and "the system does not have
    it", so an unavailable family degrades to the default face rather than
    blanking every label.
    """
    requested = family.strip()
    if not requested:
        return None
    bundled = _bundled_typeface(requested)
    if bundled is not None:
        return bundled
    if requested not in _FAMILY_TYPEFACES:
        skia = _import_skia()
        try:
            _FAMILY_TYPEFACES[requested] = skia.FontMgr().matchFamilyStyle(requested, skia.FontStyle())
        except Exception:  # noqa: BLE001 - font matching is best effort
            _FAMILY_TYPEFACES[requested] = None
    return _FAMILY_TYPEFACES[requested]


def _default_typeface() -> Any:
    """Return the typeface used for Latin labels, or None if unavailable.

    The bundled default first, so labels look the same on every machine; the
    system's own default only if the shipped font is somehow missing.
    """
    global _DEFAULT_TYPEFACE
    if _DEFAULT_TYPEFACE is _UNSET:
        _DEFAULT_TYPEFACE = _bundled_typeface(DEFAULT_FONT_FAMILY)
        if _DEFAULT_TYPEFACE is None:
            skia = _import_skia()
            try:
                _DEFAULT_TYPEFACE = skia.FontMgr().matchFamilyStyleCharacter(
                    "", skia.FontStyle(), ["und"], ord("A")
                )
            except Exception:  # noqa: BLE001 - font matching is best effort
                _DEFAULT_TYPEFACE = None
    return _DEFAULT_TYPEFACE


def _typeface_for_text(text: str, base: Any = None) -> Any:
    """Return a typeface covering ``text``, or None when ``base`` suffices.

    Only the first character the base face cannot render decides the fallback:
    a mixed "Kyoto 京都" label is drawn entirely in the CJK face, which also
    covers Latin.

    ``base`` is the face the label would otherwise use, so coverage is judged
    against the family the user picked. Courier lacks kanji just as the default
    face does, and both must still fall back. Defaults to the Latin face.
    """
    if not text:
        return None
    default = base if base is not None else _default_typeface()
    if default is None:
        return None
    for char in text:
        code_point = ord(char)
        if code_point < 0x80 or default.unicharToGlyph(code_point):
            continue
        block = code_point >> 8
        if block not in _FALLBACK_TYPEFACES:
            skia = _import_skia()
            try:
                _FALLBACK_TYPEFACES[block] = skia.FontMgr().matchFamilyStyleCharacter(
                    "", skia.FontStyle(), ["und"], code_point
                )
            except Exception:  # noqa: BLE001 - fall back to the default face
                _FALLBACK_TYPEFACES[block] = None
        return _FALLBACK_TYPEFACES[block]
    return None
