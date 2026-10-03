import json
import time
import unittest

import cv2
import numpy as np

from editor.document import (BackgroundLayer, BadgeLayer, History, ImageLayer, OverlayLayer, ShapeLayer,
                             TextLayer, ThumbnailDocument, layer_from_dict)
from typography.layer_renderer import LayerRenderer, downscale, layout_text, shaped
from typography.shaping_engine import shape_text


def sample_document():
    document = ThumbnailDocument(channel="Tokyo Chill", candidate_type="A_PERSON")
    document.add(BackgroundLayer(source="asset://bg", width=1280, height=720, name="Background"))
    document.add(OverlayLayer(kind="gradient_black", x=0, y=400, width=900, height=320, name="Title gradient"))
    document.add(TextLayer(text="雨の夜、君を思う", x=60, y=440, width=760, height=200, font_size=92,
                           highlight_word="君", role="main_title", name="Title"))
    document.add(BadgeLayer(text="EP.014", x=1040, y=24, width=200, height=60, role="episode_badge"))
    return document


def background():
    image = np.full((720, 1280, 3), (70, 50, 40), np.uint8)
    cv2.circle(image, (900, 300), 160, (180, 150, 120), -1)
    return image


class DocumentModelTests(unittest.TestCase):
    def test_serialization_round_trip_preserves_every_layer_type(self):
        document = sample_document()
        document.add(ShapeLayer(shape="ellipse", x=10, y=10, width=40, height=40, rotation=12.5))
        document.add(ImageLayer(source="C:/한글 経路/logo.png", x=5, y=5, width=50, height=50))
        payload = json.loads(json.dumps(document.to_dict(), ensure_ascii=False))
        restored = ThumbnailDocument.from_dict(payload)
        self.assertEqual(document.to_dict(), restored.to_dict())
        self.assertEqual(["background", "overlay", "text", "badge", "shape", "image"],
                         [layer.type for layer in restored.ordered()])
        self.assertIsInstance(restored.by_role("main_title"), TextLayer)
        with self.assertRaises(ValueError):
            layer_from_dict({"type": "hologram"})

    def test_layer_ordering_move_duplicate_and_delete(self):
        document = sample_document()
        title = document.by_role("main_title")
        badge = document.by_role("episode_badge")
        self.assertTrue(document.move(title.id, 1))
        self.assertGreater(title.z_index, badge.z_index)
        self.assertFalse(document.move(title.id, 1))
        clone = document.duplicate(title.id)
        self.assertEqual(title.z_index + 1, clone.z_index)
        self.assertNotEqual(title.id, clone.id)
        self.assertEqual((title.x + 24, title.y + 24), (clone.x, clone.y))
        self.assertEqual("", clone.role)
        document.remove(clone.id)
        self.assertEqual(list(range(len(document.layers))), [layer.z_index for layer in document.ordered()])
        plate = document.add(OverlayLayer(kind="plate"), below=title.id)
        self.assertEqual(title.z_index - 1, plate.z_index)

    def test_undo_redo_snapshots(self):
        document = sample_document()
        history = History()
        title = document.by_role("main_title")
        history.push(document.to_dict()); title.font_size = 120
        history.push(document.to_dict()); title.x = 300
        restored = ThumbnailDocument.from_dict(history.undo(document.to_dict()))
        self.assertEqual(120, restored.by_role("main_title").font_size)
        self.assertEqual(60, restored.by_role("main_title").x)
        restored = ThumbnailDocument.from_dict(history.undo(restored.to_dict()))
        self.assertEqual(92, restored.by_role("main_title").font_size)
        self.assertIsNone(history.undo(restored.to_dict()))
        redone = ThumbnailDocument.from_dict(history.redo(restored.to_dict()))
        self.assertEqual(120, redone.by_role("main_title").font_size)
        history.push(redone.to_dict())
        self.assertFalse(history.can_redo)


class LayerRendererTests(unittest.TestCase):
    def test_reference_scaled_shaping_matches_direct_harfbuzz(self):
        for text in ("雨の夜、君を思う", "첫눈에 다시 만난 날", "Tokyo Night 東京"):
            direct = shape_text(text, 73.5, "Tokyo Chill", None, 900, 1.5)
            scaled = shaped(text, 73.5, "Tokyo Chill", "", 900, 1.5)
            self.assertAlmostEqual(direct.advance, scaled.advance, places=3)
            for a, b in zip(direct.runs, scaled.runs):
                self.assertEqual(a.glyphs, b.glyphs)
                for (ax, ay), (bx, by) in zip(a.positions, b.positions):
                    self.assertAlmostEqual(ax, bx, places=3); self.assertAlmostEqual(ay, by, places=3)

    def test_mixed_script_text_layer_uses_fallback_families(self):
        layer = TextLayer(text="東京の夜 서울 Night", width=1200, font_size=80, font_family="Segoe UI")
        layout = layout_text(layer)
        self.assertGreaterEqual(len(layout.families), 2)
        self.assertIn("東", layout.fallback_chars)
        self.assertNotIn("N", layout.fallback_chars)

    def test_text_properties_change_pixels_and_move_reuses_cache(self):
        renderer = LayerRenderer()
        document = sample_document(); images = {"asset://bg": background()}
        first = renderer.render(document, images)
        self.assertEqual((720, 1280, 3), first.shape)
        title = document.by_role("main_title")
        for attribute, value in (("font_size", 110), ("outline_width", 16), ("fill", "#FF2050"),
                                 ("glow_opacity", 0.8), ("shadow_opacity", 0.0), ("letter_spacing", 6.0),
                                 ("secondary_outline_width", 5.0), ("alignment", "right")):
            before = renderer.render(document, images)
            setattr(title, attribute, value)
            if attribute == "glow_opacity":
                title.glow_blur = 16
            after = renderer.render(document, images)
            self.assertGreater(float(cv2.absdiff(before, after).mean()), 0.01, attribute)
        misses = renderer.stats["raster_misses"]
        title.x += 40; title.rotation = 8
        moved = renderer.render(document, images)
        self.assertEqual(misses, renderer.stats["raster_misses"])
        self.assertGreater(float(cv2.absdiff(after, moved).mean()), 0.05)

    def test_overlays_shapes_visibility_and_opacity(self):
        renderer = LayerRenderer()
        document = sample_document(); images = {"asset://bg": background()}
        for kind in ("gradient_white", "plate", "label_strip", "vignette", "blur_plate"):
            layer = document.add(OverlayLayer(kind=kind, x=700, y=100, width=400, height=300, color="#FFFFFF"))
            hidden = renderer.render(document, images, skip_ids={layer.id})
            shown = renderer.render(document, images)
            self.assertGreater(float(cv2.absdiff(hidden, shown).mean()), 0.05, kind)
            layer.opacity = 0.0
            np.testing.assert_array_equal(hidden, renderer.render(document, images))
            document.remove(layer.id)
        shape = document.add(ShapeLayer(shape="rounded", fill="#FF0000", x=0, y=0, width=50, height=50))
        image = renderer.render(document, images)
        self.assertGreater(image[25, 25, 2], 200)
        shape.visible = False
        self.assertLess(renderer.render(document, images)[25, 25, 2], 200)

    def test_export_and_preview_share_one_renderer(self):
        renderer = LayerRenderer()
        document = sample_document(); images = {"asset://bg": background()}
        editor_frame = renderer.render(document, images)
        export_frame = LayerRenderer().render(document.clone(), images)
        np.testing.assert_array_equal(editor_frame, export_frame)
        self.assertEqual((191, 340, 3), downscale(editor_frame, 340).shape)
        self.assertEqual((101, 180, 3), downscale(editor_frame, 180).shape)

    def test_below_selection_cache_is_pixel_identical(self):
        renderer = LayerRenderer()
        document = sample_document(); images = {"asset://bg": background()}
        title = document.by_role("main_title")
        document.add(OverlayLayer(kind="blur_plate", x=600, y=60, width=300, height=120))
        for step in range(3):
            title.x += 7; title.font_size += 2
            cached = renderer.render(document, images, split_at=title.id)
            np.testing.assert_array_equal(LayerRenderer().render(document, images), cached)
        document.by_role("episode_badge").text = "EP.200"
        np.testing.assert_array_equal(LayerRenderer().render(document, images),
                                      renderer.render(document, images, split_at=title.id))
        gradient = next(layer for layer in document.layers if layer.type == "overlay")
        gradient.strength = 0.2  # a change below the split invalidates the cache
        np.testing.assert_array_equal(LayerRenderer().render(document, images),
                                      renderer.render(document, images, split_at=title.id))

    def test_live_property_update_is_interactive(self):
        renderer = LayerRenderer()
        document = sample_document(); images = {"asset://bg": background()}
        renderer.render(document, images)
        title = document.by_role("main_title")
        timings = []
        for size in (94, 96, 98, 100):
            title.font_size = size
            start = time.perf_counter(); renderer.render(document, images, split_at=title.id)
            timings.append((time.perf_counter() - start) * 1000)
        drag = []
        for step in range(5):
            title.x += 3
            start = time.perf_counter(); renderer.render(document, images, split_at=title.id)
            drag.append((time.perf_counter() - start) * 1000)
        # Generous CI bound; measured ~60-100 ms for property edits and ~25 ms for drags.
        self.assertLess(sorted(timings)[len(timings) // 2], 400)
        self.assertLess(sorted(drag)[len(drag) // 2], 150)


if __name__ == "__main__":
    unittest.main()
