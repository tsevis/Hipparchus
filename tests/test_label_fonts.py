"""Tests for label font fallback across writing systems."""

from __future__ import annotations

import unittest

try:
    import skia  # type: ignore  # noqa: F401

    SKIA_AVAILABLE = True
except Exception:  # noqa: BLE001
    SKIA_AVAILABLE = False

from hipparchus.rendering.skia_fonts import _family_typeface, _typeface_for_text

# The families offered by the Label Settings combobox.
OFFERED_FAMILIES = ("Arial", "Helvetica", "Times", "Courier", "Verdana")


@unittest.skipUnless(SKIA_AVAILABLE, "skia-python not installed")
class LabelFontFallbackTests(unittest.TestCase):
    def test_latin_needs_no_fallback(self) -> None:
        self.assertIsNone(_typeface_for_text("Kyoto Station"))

    def test_empty_text_needs_no_fallback(self) -> None:
        self.assertIsNone(_typeface_for_text(""))

    def test_greek_is_covered_by_the_default_face(self) -> None:
        """Greek and Cyrillic live in the default face, so no fallback."""
        self.assertIsNone(_typeface_for_text("Αθήνα"))

    def test_japanese_resolves_a_covering_typeface(self) -> None:
        typeface = _typeface_for_text("京都駅")

        self.assertIsNotNone(typeface)
        # A non-zero glyph id is the whole point: zero renders as tofu.
        self.assertNotEqual(typeface.unicharToGlyph(ord("京")), 0)

    def test_mixed_script_resolves_on_the_uncovered_character(self) -> None:
        typeface = _typeface_for_text("Kyoto 京都")

        self.assertIsNotNone(typeface)
        self.assertNotEqual(typeface.unicharToGlyph(ord("京")), 0)

    def test_korean_resolves_a_covering_typeface(self) -> None:
        typeface = _typeface_for_text("서울역")

        self.assertIsNotNone(typeface)
        self.assertNotEqual(typeface.unicharToGlyph(ord("서")), 0)

    def test_lookup_is_cached(self) -> None:
        first = _typeface_for_text("京都")
        second = _typeface_for_text("京都")

        self.assertIs(first, second)


@unittest.skipUnless(SKIA_AVAILABLE, "skia-python not installed")
class LabelFontFamilyTests(unittest.TestCase):
    """Backs the Label Settings font family picker."""

    def _first_resolvable_family(self):
        for family in OFFERED_FAMILIES:
            typeface = _family_typeface(family)
            if typeface is not None:
                return family, typeface
        self.skipTest(f"none of {OFFERED_FAMILIES} installed")

    def test_no_family_requested_means_the_default_face(self) -> None:
        for requested in ("", "   "):
            with self.subTest(requested=requested):
                self.assertIsNone(_family_typeface(requested))

    def test_unknown_family_falls_back_to_the_default_face(self) -> None:
        """A family the system does not have must not blank out every label."""
        self.assertIsNone(_family_typeface("Nonexistent Family QZX"))

    def test_at_least_one_offered_family_resolves(self) -> None:
        resolved = {family: _family_typeface(family) for family in OFFERED_FAMILIES}
        self.assertTrue(any(face is not None for face in resolved.values()), resolved)

    def test_resolved_family_covers_latin(self) -> None:
        _, typeface = self._first_resolvable_family()
        self.assertNotEqual(typeface.unicharToGlyph(ord("A")), 0)

    def test_family_lookup_is_cached(self) -> None:
        family, first = self._first_resolvable_family()
        self.assertIs(first, _family_typeface(family))

    def test_cjk_fallback_is_relative_to_the_chosen_family(self) -> None:
        """Picking Courier must not resurrect tofu: the fallback still applies."""
        _, base = self._first_resolvable_family()

        self.assertIsNone(_typeface_for_text("Kyoto Station", base=base))
        covering = _typeface_for_text("京都駅", base=base)
        self.assertIsNotNone(covering)
        self.assertNotEqual(covering.unicharToGlyph(ord("京")), 0)


if __name__ == "__main__":
    unittest.main()
