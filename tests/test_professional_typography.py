import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from layout_engine import render_candidate_text
from typography.font_registry import FontRegistry, get_font_registry
from typography.linebreak_engine import NO_LINE_END, NO_LINE_START, choose_line_break, legal_breaks
from typography.shaping_engine import shape_text
from typography.svg_badge_renderer import badge_svg, render_svg_png
from typography.storage_assets import load_image_storage_assets
from typography.text_renderer_skia import render_title
from typography.text_style import preset_names
from typography.background_fit import analyze_background, apply_adaptive_backdrop


JAPANESE_SNAPSHOT = (
    ("\u6625\u306e\u99c5\u3067\u541b\u3092\u5f85\u3063\u3066\u3044\u305f", ("\u6625\u306e\u99c5\u3067\u541b\u3092", "\u5f85\u3063\u3066\u3044\u305f")),
    ("\u96e8\u306e\u591c\u306b\u3001\u3082\u3046\u4e00\u5ea6\u4f1a\u3048\u305f\u3002", ("\u96e8\u306e\u591c\u306b\u3001", "\u3082\u3046\u4e00\u5ea6\u4f1a\u3048\u305f\u3002")),
    ("\u5098\u3072\u3068\u3064\u3001\u8ddd\u96e2\u306f\u30bc\u30ed\u3002", ("\u5098\u3072\u3068\u3064\u3001", "\u8ddd\u96e2\u306f\u30bc\u30ed\u3002")),
    ("\u3042\u306e\u65e5\u306e\u7d04\u675f\u3092\u3001\u4eca\u3082\u899a\u3048\u3066\u3044\u308b", ("\u3042\u306e\u65e5\u306e\u7d04\u675f\u3092\u3001", "\u4eca\u3082\u899a\u3048\u3066\u3044\u308b")),
    ("\u6771\u4eac\u306e\u591c\u666f\u304c\u3075\u305f\u308a\u3092\u5305\u3080", ("\u6771\u4eac\u306e", "\u591c\u666f\u304c\u3075\u305f\u308a\u3092\u5305\u3080")),
    ("\u6700\u7d42\u96fb\u8eca\u306e\u7a93\u306b\u6620\u308b\u6a2a\u9854", ("\u6700\u7d42\u96fb\u8eca\u306e", "\u7a93\u306b\u6620\u308b\u6a2a\u9854")),
    ("\u5fd8\u308c\u305f\u3075\u308a\u3092\u3057\u305f\u521d\u604b\u306e\u540d\u524d", ("\u5fd8\u308c\u305f\u3075\u308a\u3092\u3057\u305f", "\u521d\u604b\u306e\u540d\u524d")),
    ("\u3055\u3088\u306a\u3089\u306e\u3042\u3068\u3001\u5b63\u7bc0\u304c\u5909\u308f\u3063\u305f", ("\u3055\u3088\u306a\u3089\u306e\u3042\u3068\u3001", "\u5b63\u7bc0\u304c\u5909\u308f\u3063\u305f")),
    ("\u541b\u304c\u7b11\u3046\u3068\u8857\u306e\u706f\u308a\u304c\u306b\u3058\u3080", ("\u541b\u304c\u7b11\u3046\u3068\u8857\u306e", "\u706f\u308a\u304c\u306b\u3058\u3080")),
    ("\u79cb\u98a8\u3068\u30b3\u30fc\u30d2\u30fc\u3001\u5e30\u308a\u9053\u306e\u8a18\u61b6", ("\u79cb\u98a8\u3068\u30b3\u30fc\u30d2\u30fc\u3001", "\u5e30\u308a\u9053\u306e\u8a18\u61b6")),
    ("\u96ea\u306e\u964d\u308b\u671d\u306b\u5c4a\u3044\u305f\u624b\u7d19", ("\u96ea\u306e\u964d\u308b\u671d\u306b", "\u5c4a\u3044\u305f\u624b\u7d19")),
    ("\u3075\u305f\u308a\u3060\u3051\u306e\u79d8\u5bc6\u306e\u5834\u6240", ("\u3075\u305f\u308a\u3060\u3051\u306e", "\u79d8\u5bc6\u306e\u5834\u6240")),
    ("\u99c5\u306e\u30db\u30fc\u30e0\u3067\u59cb\u307e\u3063\u305f\u7269\u8a9e", ("\u99c5\u306e\u30db\u30fc\u30e0\u3067", "\u59cb\u307e\u3063\u305f\u7269\u8a9e")),
    ("\u9060\u56de\u308a\u3057\u305f\u5e30\u308a\u9053\u306e\u5c0f\u3055\u306a\u5947\u8de1", ("\u9060\u56de\u308a\u3057\u305f\u5e30\u308a\u9053\u306e", "\u5c0f\u3055\u306a\u5947\u8de1")),
    ("\u7720\u308c\u306a\u3044\u591c\u306b\u8074\u304f\u30e9\u30d6\u30bd\u30f3\u30b0", ("\u7720\u308c\u306a\u3044\u591c\u306b", "\u8074\u304f\u30e9\u30d6\u30bd\u30f3\u30b0")),
    ("\u9759\u304b\u306a\u6d77\u8fba\u3067\u4ea4\u308f\u3057\u305f\u7d04\u675f", ("\u9759\u304b\u306a\u6d77\u8fba\u3067", "\u4ea4\u308f\u3057\u305f\u7d04\u675f")),
    ("\u96e8\u4e0a\u304c\u308a\u306e\u8857\u89d2\u3067\u518d\u4f1a\u3057\u305f", ("\u96e8\u4e0a\u304c\u308a\u306e", "\u8857\u89d2\u3067\u518d\u4f1a\u3057\u305f")),
    ("\u6700\u5f8c\u306e\u685c\u304c\u6563\u308b\u524d\u306b\u4f1d\u3048\u305f\u3044", ("\u6700\u5f8c\u306e\u685c\u304c", "\u6563\u308b\u524d\u306b\u4f1d\u3048\u305f\u3044")),
    ("\u7b11\u9854\u306e\u5411\u3053\u3046\u306b\u96a0\u3057\u305f\u6d99", ("\u7b11\u9854\u306e\u5411\u3053\u3046\u306b", "\u96a0\u3057\u305f\u6d99")),
    ("\u4e8c\u4eba\u306e\u8ddd\u96e2\u304c\u5c11\u3057\u305a\u3064\u8fd1\u3065\u304f", ("\u4e8c\u4eba\u306e\u8ddd\u96e2\u304c", "\u5c11\u3057\u305a\u3064\u8fd1\u3065\u304f")),
)


class ProfessionalTypographyTests(unittest.TestCase):
    def test_japanese_linebreak_20_title_snapshot_and_kinsoku(self):
        width = lambda text: sum(1.0 if ord(char) > 0x2E7F else 0.56 for char in text)
        for title, expected in JAPANESE_SNAPSHOT:
            with self.subTest(title=title):
                choice = choose_line_break(title, width, 12, 3)
                self.assertEqual(expected, choice.lines)
                self.assertEqual(title, "".join(choice.lines))
                self.assertLessEqual(len(choice.lines), 3)
                for left, right in zip(choice.lines, choice.lines[1:]):
                    self.assertNotIn(left[-1], NO_LINE_END)
                    self.assertNotIn(right[0], NO_LINE_START)

    def test_mixed_cjk_uses_installed_fallback_and_harfbuzz_glyph_runs(self):
        registry = get_font_registry()
        japanese = registry.resolve("\u601d", "Tokyo Chill")
        korean = registry.resolve("\ud55c", "Tokyo Chill")
        self.assertTrue(japanese.supports("\u601d"))
        self.assertTrue(korean.supports("\ud55c"))
        shaped = shape_text("Tokyo \u601d\u3044\u51fa \ud55c\uae00", 72,
                            "Tokyo Chill", registry=registry)
        self.assertGreater(shaped.advance, 0)
        self.assertTrue(shaped.runs)
        self.assertTrue(all(run.glyphs and run.positions for run in shaped.runs))
        self.assertGreaterEqual(len({run.face.family for run in shaped.runs}), 2)

    def test_340px_preview_renders_readable_mixed_title(self):
        base = np.full((720, 1280, 3), (32, 42, 58), dtype=np.uint8)
        base[:, :440] = (210, 190, 150)
        result = render_title(base, "\u96e8\u306e\u591c\u306b \uc11c\uc6b8\uc758 \ubc24",
            (52, 400, 860, 245), "Japanese Impact", "Tokyo Chill",
            highlight_word="\u96e8\u306e\u591c", max_lines=3, supersample=2)
        preview = cv2.resize(result.image, (340, 191), interpolation=cv2.INTER_AREA)
        self.assertGreater(np.mean(cv2.absdiff(preview, cv2.resize(base, (340, 191)))), 4.0)
        self.assertGreater(result.bbox[2], 200)
        self.assertGreaterEqual(len(result.lines), 2)
        self.assertIn("\u96e8\u306e\u591c", result.keyword)
        self.assertTrue(result.fallback_families)

    def test_layouts_render_distinct_abcs_and_svg_badge_exports_png(self):
        base = np.full((720, 1280, 3), (26, 36, 54), dtype=np.uint8)
        cv2.circle(base, (930, 310), 140, (80, 135, 175), -1)
        outputs = [render_candidate_text(base.copy(), "Tokyo Chill", code, "STORY", "EP.014",
            "\u50d5\u3089\u306e\u7269\u8a9e \uc11c\uc6b8", "A city memory", "Japanese Impact",
            keyword="\u7269\u8a9e")[0] for code in ("A_PERSON", "B_EMOTION", "C_STORY")]
        previews = [cv2.resize(output, (340, 191), interpolation=cv2.INTER_AREA) for output in outputs]
        changes = [float(cv2.absdiff(previews[a], previews[b]).mean() / 255.0)
                   for a, b in ((0, 1), (0, 2), (1, 2))]
        self.assertTrue(all(change >= 0.018 for change in changes), changes)
        overlay = render_svg_png(badge_svg("EP.014 · MEMORY", "ribbon"))
        self.assertEqual((76, 280, 4), overlay.shape)
        self.assertGreater(int(overlay[:, :, 3].max()), 0)

    def test_storage_sidecars_prefer_clean_canvas_and_parse_regions(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw)
            source = folder / "source.png"
            source.touch()
            (folder / "cleaned_canvas.png").touch()
            (folder / "safe_zone.json").write_text(json.dumps({"safe_zones": [[0.1, 0.1, 0.2, 0.2]]}), encoding="utf-8")
            (folder / "subject_boxes.json").write_text(json.dumps({"protagonist": {"bbox": [0.3, 0.2, 0.1, 0.4]}}), encoding="utf-8")
            (folder / "reference_thumb.png").touch()
            assets = load_image_storage_assets(source)
            self.assertEqual("image-storage", assets.source_kind)
            self.assertEqual("cleaned_canvas.png", assets.source_image.name)
            self.assertEqual(1, len(assets.safe_zones))
            self.assertEqual(1, len(assets.subject_boxes))
            self.assertEqual("reference_thumb.png", assets.reference_thumbnail.name)
        self.assertEqual(6, len(preset_names("Tokyo Chill")))
        self.assertEqual(6, len(preset_names("OLD POP LOUNGE")))

    def test_background_fit_scores_busy_regions_and_adds_adaptive_overlay(self):
        y, x = np.indices((720, 1280))
        checker = (((x // 8 + y // 8) % 2) * 190 + 25).astype(np.uint8)
        busy = np.dstack((checker, np.roll(checker, 3, axis=1), np.roll(checker, 5, axis=0)))
        analysis = analyze_background(busy, (50, 350, 850, 240), [(0.2, 0.52, 0.16, 0.25)])
        fitted, reported = apply_adaptive_backdrop(busy, (50, 350, 850, 240), subject_boxes=[(0.2, 0.52, 0.16, 0.25)])
        self.assertLess(analysis.readability, 0.68)
        self.assertTrue(analysis.recommend_soft_plate)
        self.assertTrue(analysis.recommend_gradient)
        self.assertEqual(analysis.dominant_color, reported.dominant_color)
        self.assertGreater(float(cv2.absdiff(fitted, busy).mean()), 0.5)

    def test_project_storage_new_sidecar_names_are_detected(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw); source = folder / "source.png"; source.touch()
            (folder / "canvas_clean.png").touch(); (folder / "preview_reference.png").touch()
            (folder / "safe_zones.json").write_text('{"zones": [[0.1, 0.2, 0.3, 0.4]]}', encoding="utf-8")
            (folder / "palette.json").write_text('{"fill_color": "#F0E0D0"}', encoding="utf-8")
            (folder / "composition.json").write_text('{"positions": {"main_title": [20, 30, 400, 160]}}', encoding="utf-8")
            assets = load_image_storage_assets(source)
            self.assertEqual("canvas_clean.png", assets.source_image.name)
            self.assertEqual("preview_reference.png", assets.reference_thumbnail.name)
            self.assertEqual(1, len(assets.safe_zones))
            self.assertEqual("#F0E0D0", assets.palette["fill_color"])
            self.assertIn("positions", assets.composition)


if __name__ == "__main__":
    unittest.main()
