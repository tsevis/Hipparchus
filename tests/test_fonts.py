"""The bundled multilingual default and the family picker.

None of this opens a window: loading a typeface and listing font families is a
Skia call, not a Tk one, so it runs in the default suite.
"""

from __future__ import annotations

import unittest

from hipparchus.core.settings_store import UserSettings, clamp
from hipparchus.rendering import skia_fonts

try:
    skia_fonts._import_skia()
    _HAVE_SKIA = True
except Exception:  # noqa: BLE001 - the renderer degrades; the tests skip
    _HAVE_SKIA = False


@unittest.skipUnless(_HAVE_SKIA, "skia-python not installed")
class BundledFontTests(unittest.TestCase):
    def test_noto_sans_is_bundled_and_loads(self) -> None:
        typeface = skia_fonts._bundled_typeface("Noto Sans")
        self.assertIsNotNone(typeface)
        self.assertEqual(typeface.getFamilyName(), "Noto Sans")

    def test_an_unshipped_family_is_not_bundled(self) -> None:
        self.assertIsNone(skia_fonts._bundled_typeface("Definitely Not A Font"))

    def test_the_default_face_is_the_bundled_one(self) -> None:
        typeface = skia_fonts._default_typeface()
        self.assertIsNotNone(typeface)
        self.assertEqual(typeface.getFamilyName(), "Noto Sans")

    def test_the_bundled_face_covers_latin_greek_and_cyrillic(self) -> None:
        typeface = skia_fonts._bundled_typeface("Noto Sans")
        for char in "AΩЯ":
            self.assertNotEqual(typeface.unicharToGlyph(ord(char)), 0, f"missing {char!r}")

    def test_available_families_include_the_bundled_default(self) -> None:
        self.assertIn("Noto Sans", skia_fonts.available_font_families())


class SettingsFontDefaultTests(unittest.TestCase):
    def test_the_default_font_is_the_bundled_one(self) -> None:
        self.assertEqual(UserSettings().label_font_family, "Noto Sans")

    def test_a_blank_font_clamps_to_the_bundled_one(self) -> None:
        self.assertEqual(
            clamp(UserSettings(label_font_family="   ")).label_font_family, "Noto Sans"
        )


class FontChoicesTests(unittest.TestCase):
    def test_the_bundled_default_leads_the_dropdown_and_it_is_deduped(self) -> None:
        from hipparchus.ui import settings_window

        choices = settings_window.font_choices()
        self.assertEqual(choices[0], "Noto Sans")
        self.assertEqual(len(choices), len(set(choices)))


if __name__ == "__main__":
    unittest.main()
