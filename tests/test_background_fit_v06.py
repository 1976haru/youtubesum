import unittest

import cv2
import numpy as np

from typography.background_fit import (analyze_text_region, contrast_ratio, readability_report,
                                       suggest_text_style)


def busy_bright():
    rng = np.random.default_rng(3)
    image = np.full((720, 1280, 3), 225, np.uint8)
    noise = rng.integers(0, 255, (720, 1280, 3), dtype=np.uint8)
    image[300:720] = noise[300:720]
    return image


def calm_dark():
    image = np.zeros((720, 1280, 3), np.uint8)
    image[:] = (60, 30, 25)  # deep navy (BGR)
    cv2.circle(image, (980, 300), 160, (150, 170, 220), -1)
    return image


class BackgroundFitTests(unittest.TestCase):
    def test_region_analysis_reports_luminance_busyness_palette_and_face_overlap(self):
        dark = analyze_text_region(calm_dark(), (40, 420, 700, 240), subject_boxes=[(820, 140, 320, 320)])
        self.assertLess(dark.mean_luminance, 0.3)
        self.assertLess(dark.edge_density, 0.05)
        self.assertEqual(5, len(dark.palette))
        self.assertEqual(0.0, dark.subject_overlap)
        overlapping = analyze_text_region(calm_dark(), (800, 200, 400, 200), subject_boxes=[(820, 140, 320, 320)])
        self.assertGreater(overlapping.subject_overlap, 0.5)
        busy = analyze_text_region(busy_bright(), (40, 420, 700, 240))
        self.assertGreater(busy.edge_density, 0.10)

    def test_fit_suggestion_keeps_channel_identity_and_reaches_good_contrast(self):
        analysis = analyze_text_region(calm_dark(), (40, 420, 700, 240))
        tokyo = suggest_text_style(analysis, "Tokyo Chill", "fit", {"font_size": 100})
        old_pop = suggest_text_style(analysis, "OLD POP LOUNGE", "fit", {"font_size": 100})
        self.assertEqual("#FFFFFF", tokyo["fill"])
        self.assertEqual("#FFF4DC", old_pop["fill"])  # warm cream, calm
        self.assertGreater(tokyo["glow_opacity"], old_pop["glow_opacity"])
        self.assertLessEqual(old_pop["glow_opacity"], 0.1)
        self.assertGreater(old_pop["outline_width"], tokyo["outline_width"])
        for style in (tokyo, old_pop):
            report = readability_report({"font_size": 100, **style}, analysis)
            self.assertEqual("GOOD", report["contrast_level"])
            self.assertGreater(contrast_ratio(style["fill"], style["outline_color"]), 4.5)

    def test_busy_bright_background_gets_dark_ink_and_plate(self):
        analysis = analyze_text_region(busy_bright(), (40, 420, 700, 240))
        style = suggest_text_style(analysis, "Tokyo Chill", "fit", {"font_size": 96})
        self.assertIsNotNone(style["plate"])
        self.assertEqual("gradient_black", style["plate"]["kind"])
        old_pop = suggest_text_style(analysis, "OLD POP LOUNGE", "fit", {"font_size": 96})
        self.assertEqual("plate", old_pop["plate"]["kind"])
        palette = {"fill_color": "#FFF1D0", "stroke_color": "#241A18", "highlight_color": "#D6A657"}
        with_palette = suggest_text_style(analyze_text_region(calm_dark(), (40, 420, 700, 240)),
                                          "OLD POP LOUNGE", "fit", {"font_size": 96}, palette)
        self.assertEqual(("#FFF1D0", "#241A18", "#D6A657"),
                         (with_palette["fill"], with_palette["outline_color"], with_palette["highlight_color"]))

    def test_stronger_softer_and_contrast_only(self):
        analysis = analyze_text_region(calm_dark(), (40, 420, 700, 240))
        current = {"font_size": 90, "outline_width": 8, "shadow_opacity": 0.5, "glow_opacity": 0.2, "glow_blur": 10,
                   "fill": "#202020", "outline_color": "#000000"}
        stronger = suggest_text_style(analysis, "Tokyo Chill", "stronger", current)
        softer = suggest_text_style(analysis, "Tokyo Chill", "softer", current)
        self.assertGreater(stronger["outline_width"], 8); self.assertLess(softer["outline_width"], 8)
        self.assertGreater(stronger["shadow_opacity"], softer["shadow_opacity"])
        self.assertIsNotNone(stronger["plate"]); self.assertIsNone(softer["plate"])
        contrast_only = suggest_text_style(analysis, "Tokyo Chill", "contrast", current)
        self.assertEqual({"fill", "outline_color"}, set(contrast_only))
        self.assertEqual("POOR", readability_report(current, analysis)["contrast_level"])
        self.assertEqual("GOOD", readability_report({**current, **contrast_only}, analysis)["contrast_level"])

    def test_readability_meter_340_180_and_face_warning(self):
        analysis = analyze_text_region(calm_dark(), (800, 200, 400, 200), subject_boxes=[(820, 140, 320, 320)])
        report = readability_report({"font_size": 100, "fill": "#FFFFFF", "outline_width": 10,
                                     "outline_color": "#000000"}, analysis)
        self.assertTrue(report["face_warning"])
        self.assertEqual("WARNING", report["level"])
        self.assertEqual("GOOD", report["level340"]); self.assertEqual("GOOD", report["level180"])
        small = readability_report({"font_size": 30, "fill": "#FFFFFF"}, analysis)
        self.assertEqual("POOR", small["level340"]); self.assertEqual("POOR", small["level"])
        label = readability_report({"font_size": 36, "fill": "#FFFFFF"}, analysis, role="label")
        self.assertEqual("GOOD", label["level340"])


if __name__ == "__main__":
    unittest.main()
