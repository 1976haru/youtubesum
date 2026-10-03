import tempfile
import unittest
from pathlib import Path

from editor.fonts import EditorSettings, build_catalog, filter_families, missing_glyphs, nearest_weight
from typography.font_registry import FontFace, FontRegistry


def face(family, weight, chars):
    return FontFace(Path(f"C:/fonts/{family}-{weight}.ttf"), 0, family, "Regular", weight, "normal", (),
                    frozenset(ord(char) for char in chars))


LATIN = "AaZz09 Night"
JAPANESE = "あア漢字夜東京の雨思う"
KOREAN = "한글밤서울"


class FontBrowserTests(unittest.TestCase):
    def setUp(self):
        self.registry = FontRegistry((
            face("Yu Gothic", 400, LATIN + JAPANESE), face("Yu Gothic", 700, LATIN + JAPANESE),
            face("Malgun Gothic", 700, LATIN + KOREAN), face("Segoe UI", 400, LATIN),
            face("Arial Black", 900, LATIN), face("@Yu Gothic", 400, JAPANESE)))
        self.catalog = build_catalog(self.registry)

    def test_catalog_groups_weights_and_detects_cjk_coverage(self):
        names = [family.name for family in self.catalog]
        self.assertNotIn("@Yu Gothic", names)
        yu = next(family for family in self.catalog if family.name == "Yu Gothic")
        self.assertEqual((400, 700), yu.weights)
        self.assertTrue(yu.japanese); self.assertFalse(yu.korean); self.assertTrue(yu.latin)
        self.assertEqual("JA EN", yu.scripts)
        self.assertEqual(["Yu Gothic"], [f.name for f in filter_families(self.catalog, "Japanese")])
        self.assertEqual(["Malgun Gothic"], [f.name for f in filter_families(self.catalog, "Korean")])
        self.assertEqual(4, len(filter_families(self.catalog, "Latin")))
        self.assertEqual(["Arial Black"], [f.name for f in filter_families(self.catalog, "All", "black")])

    def test_favorites_recent_and_bold_preference_ordering(self):
        ordered = filter_families(self.catalog, "Latin", favorites=["Segoe UI"], recent=["Malgun Gothic"])
        self.assertEqual(["Segoe UI", "Malgun Gothic"], [f.name for f in ordered[:2]])
        bold = filter_families(self.catalog, "Latin", bold_first=True)
        self.assertNotEqual("Segoe UI", bold[0].name)
        only = filter_families(self.catalog, "All", favorites=["Arial Black"], only_favorites=True)
        self.assertEqual(["Arial Black"], [f.name for f in only])

    def test_fallback_warning_lists_unsupported_characters(self):
        self.assertEqual([], missing_glyphs("Yu Gothic", "東京の雨 Night", self.registry))
        self.assertEqual(["서", "울"], missing_glyphs("Yu Gothic", "東京 서울", self.registry))
        self.assertEqual(list("東京"), missing_glyphs("Segoe UI", "東京 Night", self.registry))
        self.assertEqual(700, nearest_weight("Yu Gothic", 900, self.registry))

    def test_settings_persist_atomically_in_unicode_folder(self):
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "설정 フォルダ" / "editor_settings.json"
            settings = EditorSettings(path)
            settings.use_font("Yu Gothic"); settings.use_font("Malgun Gothic"); settings.use_font("Yu Gothic")
            self.assertTrue(settings.toggle_favorite_font("Meiryo"))
            settings.use_style("romantic_neon")
            reopened = EditorSettings(path)
            self.assertEqual(["Yu Gothic", "Malgun Gothic"], reopened.recent_fonts)
            self.assertEqual(["Meiryo"], reopened.favorite_fonts)
            self.assertEqual(["romantic_neon"], reopened.recent_styles)
            self.assertFalse(reopened.toggle_favorite_font("Meiryo"))
            self.assertEqual([], list(path.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
