import unittest

import numpy as np
from PIL import Image, ImageChops

from typography_engine import (PRESETS_BY_CHANNEL, TYPOGRAPHY_PRESETS, choose_keyword,
                               contrast_mode, draw_thumbnail_title, preset_names, split_title)


class TypographyEngineTests(unittest.TestCase):
    def test_twelve_named_presets_are_grouped_six_per_channel(self):
        tokyo = ("Japanese Impact", "Romantic Neon", "Urban Story", "Soft Memory", "Night Drive", "Heartbeat Clean")
        old = ("Senior Classic", "Warm Gold", "First Snow", "Autumn Lounge", "Christmas Glow", "Calm Blue Memory")
        self.assertEqual(tokyo, preset_names("Tokyo Chill"))
        self.assertEqual(old, preset_names("OLD POP LOUNGE"))
        self.assertEqual(12, len(TYPOGRAPHY_PRESETS))
        self.assertEqual(6, len(PRESETS_BY_CHANNEL["Tokyo Chill"]))
        self.assertEqual(6, len(PRESETS_BY_CHANNEL["OLD POP LOUNGE"]))

    def test_title_auto_split_and_single_keyword_selection(self):
        self.assertEqual(("Tokyo night", "memories remain"), split_title("Tokyo night memories remain", True))
        self.assertEqual(("東京の思い出 한글", "mixed title"), split_title("東京の思い出 한글 mixed title", True))
        self.assertEqual(("東京の思い出 한글 mixed title",), split_title("東京の思い出 한글 mixed title", False))
        self.assertEqual("思い出", choose_keyword("東京の思い出 한글 mixed title"))
        self.assertEqual("Tokyo", choose_keyword("Tokyo night memories", "Tokyo"))

    def test_contrast_auto_selects_ink_for_bright_and_dark_backgrounds(self):
        bright = np.full((720, 1280, 3), 242, dtype=np.uint8)
        dark = np.full((720, 1280, 3), 12, dtype=np.uint8)
        self.assertEqual("dark", contrast_mode(bright, (40, 80, 900, 220)))
        self.assertEqual("light", contrast_mode(dark, (40, 80, 900, 220)))

    def test_preset_effects_keyword_emphasis_and_two_lines_are_visible(self):
        base = Image.new("RGB", (1280, 720), (22, 34, 60))
        impact = base.copy()
        impact_info = draw_thumbnail_title(impact, "東京の思い出 한글 neon city", (60, 420, 920, 250),
            "japanese_impact", True, True, "思い出", "Large", "left", "person")
        neon = base.copy()
        neon_info = draw_thumbnail_title(neon, "東京の思い出 한글 neon city", (60, 420, 920, 250),
            "romantic_neon", True, True, "思い出", "Large", "left", "emotion")
        self.assertEqual(2, len(impact_info["lines"]))
        self.assertEqual("思い出", impact_info["keyword"])
        self.assertGreater(impact_info["outline_width"], neon_info["outline_width"])
        self.assertNotEqual(0, ImageChops.difference(impact, neon).getbbox())
        self.assertEqual("person", impact_info["variant"])
        self.assertEqual("emotion", neon_info["variant"])

    def test_senior_title_size_is_larger_at_same_requested_size(self):
        base = Image.new("RGB", (1280, 720), (40, 36, 31))
        tokyo = draw_thumbnail_title(base.copy(), "思い出の夜", (40, 400, 900, 260), "cinematic_chill", size_option="Medium")
        senior = draw_thumbnail_title(base.copy(), "思い出の夜", (40, 400, 900, 260), "senior_classic", size_option="Medium")
        self.assertGreater(senior["font_size"], tokyo["font_size"])


if __name__ == "__main__":
    unittest.main()
