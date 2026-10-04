import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from editor.document import ShapeLayer, TextLayer
from editor.project import (SLOTS, copy_layer_to, copy_typography_layout, export_candidate, find_collisions, ink_box,
                            generate_project, load_project, propagate_shared, relayout_to_safe, replace_backgrounds,
                            reset_candidate, save_project, sync_text_height)
from typography.layer_renderer import LayerRenderer, layout_text
from typography.linebreak_engine import legal_breaks


def write_unicode(path, image):
    ok, data = cv2.imencode(".png", image)
    assert ok
    data.tofile(str(path))


def source_image():
    y, x = np.indices((720, 1280))
    image = np.dstack(((x // 5) % 256, (y // 3) % 256, 90 + (x + y) % 60)).astype(np.uint8)
    cv2.circle(image, (900, 300), 120, (200, 190, 230), -1)
    return image


TEXTS = {"title": "雨の夜、君を思う", "subtitle": "A quiet story", "episode": "EP.014", "story": "ROMANTIC"}


class ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name) / "프로젝트 東京 space"
        cls.root.mkdir()
        cls.source = cls.root / "원본 画像.png"
        write_unicode(cls.source, source_image())
        cls.source_digest = hashlib.sha256(cls.source.read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def make(self, channel="Tokyo Chill", style="Romantic Neon", texts=TEXTS):
        return generate_project(self.source, channel, style, dict(texts))

    def test_generator_layouts_become_editable_documents(self):
        state = self.make()
        self.assertEqual(SLOTS, tuple(state.documents))
        codes = [state.documents[slot].candidate_type for slot in SLOTS]
        self.assertEqual(["A_PERSON", "B_EMOTION", "C_STORY"], codes)
        for slot in SLOTS:
            document = state.documents[slot]
            roles = {layer.role for layer in document.layers}
            self.assertTrue({"background", "title_backdrop", "main_title", "subtitle", "channel_label",
                             "story_label", "episode_badge"} <= roles)
            title = document.by_role("main_title")
            self.assertEqual("雨の夜、君を思う", title.text)
            self.assertAlmostEqual(layout_text(title).content_height, title.height, places=0)
            self.assertIsNotNone(state.background_image(slot))
        aligns = {state.documents[slot].by_role("main_title").alignment for slot in SLOTS}
        self.assertGreaterEqual(len(aligns), 2)
        old_pop = self.make("OLD POP LOUNGE", "Warm Gold", {**TEXTS, "title": "첫눈에 다시 만난 날"})
        self.assertEqual(["A_PERSON", "B_MEMORY", "C_SCENERY"],
                         [old_pop.documents[slot].candidate_type for slot in SLOTS])
        for line in layout_text(old_pop.documents["A"].by_role("main_title")).lines:
            self.assertFalse(line.startswith(("시", "난", "날")) and len(line) == 1)

    def test_ink_box_tracks_glyph_extents_not_the_wrap_box(self):
        layer = TextLayer(text="短い", x=100, y=100, width=800, height=120, font_size=80, alignment="left")
        sync_text_height(layer)
        x, y, w, h = ink_box(layer)
        self.assertAlmostEqual(100, x, delta=1)
        self.assertLess(w, 260)
        layer.alignment = "right"
        self.assertAlmostEqual(900, ink_box(layer)[0] + ink_box(layer)[2], delta=1)
        layer.rotation = 90
        rx, ry, rw, rh = ink_box(layer)
        self.assertLess(rw, rh)  # rotated about the layer centre
        self.assertGreater(ry, layer.y - 400)

    def test_korean_titles_break_only_between_words(self):
        text = "첫눈에 다시 만난 날"
        breaks = legal_breaks(text)
        self.assertEqual({4, 7, 10, 11}, set(breaks))
        mixed = legal_breaks("東京の夜、君を思う")
        self.assertIn(5, mixed)  # Japanese breaks are unchanged

    def test_candidates_are_independent_and_copy_reset_shared(self):
        state = self.make()
        a_title = state.documents["A"].by_role("main_title")
        b_before = state.documents["B"].by_role("main_title").to_dict()
        a_title.font_size = 140; a_title.fill = "#00FF00"
        self.assertEqual(b_before, state.documents["B"].by_role("main_title").to_dict())
        self.assertEqual(["B", "C"], copy_layer_to(state, "A", a_title.id))
        for slot in ("B", "C"):
            copied = state.documents[slot].by_role("main_title")
            self.assertEqual(140, copied.font_size); self.assertNotEqual(a_title.id, copied.id)
            self.assertEqual(1, sum(layer.role == "main_title" for layer in state.documents[slot].layers))
        star = state.documents["A"].add(ShapeLayer(name="star", x=10, y=10, width=30, height=30))
        copy_layer_to(state, "A", star.id, ("C",))
        self.assertTrue(any(layer.name == "star" for layer in state.documents["C"].layers))
        self.assertFalse(any(layer.name == "star" for layer in state.documents["B"].layers))
        background_b = state.documents["B"].background().source
        copy_typography_layout(state, "A", ("B",))
        self.assertEqual(background_b, state.documents["B"].background().source)
        self.assertTrue(any(layer.name == "star" for layer in state.documents["B"].layers))
        reset_candidate(state, "B")
        self.assertEqual(b_before["font_size"], state.documents["B"].by_role("main_title").font_size)
        self.assertEqual(background_b, state.documents["B"].background().source)
        episode = state.documents["A"].by_role("episode_badge")
        episode.text = "EP.099"
        self.assertEqual(["B", "C"], propagate_shared(state, "A", episode))
        self.assertEqual("EP.099", state.documents["C"].by_role("episode_badge").text)
        state.shared_lock = False
        episode.text = "EP.100"
        self.assertEqual([], propagate_shared(state, "A", episode))
        undo = state.histories["B"].undo(state.documents["B"].to_dict())
        self.assertIsNotNone(undo)

    def test_bridge_background_replacement_preserves_text_layers(self):
        state = self.make()
        title = state.documents["A"].by_role("main_title")
        title.text = "手動で直した題"; title.x = 321; title.rotation = -6
        before = {slot: [layer.to_dict() for layer in state.documents[slot].ordered() if layer.type != "background"]
                  for slot in SLOTS}
        new_bg = np.full((720, 1280, 3), (20, 120, 220), np.uint8)
        collisions = replace_backgrounds(state, {slot: new_bg for slot in SLOTS},
                                         subjects={"A": [[0.2, 0.55, 0.5, 0.4]]}, safe_zones={"A": []})
        for slot in SLOTS:
            after = [layer.to_dict() for layer in state.documents[slot].ordered() if layer.type != "background"]
            self.assertEqual(before[slot], after)
            np.testing.assert_array_equal(new_bg, state.background_image(slot))
        self.assertTrue(any(item["kind"] == "subject" for item in collisions["A"]))
        self.assertEqual([[256.0, 396.0, 640.0, 288.0]], state.documents["A"].subject_boxes)
        moved = relayout_to_safe(state.documents["A"])
        self.assertIn(title.id, moved)
        self.assertLess(len(find_collisions(state.documents["A"])), len(collisions["A"]))
        self.assertEqual("手動で直した題", title.text)

    def test_project_save_reopen_with_korean_japanese_paths_never_touches_source(self):
        state = self.make()
        title = state.documents["B"].by_role("main_title")
        title.text = "저장 テスト"; title.rotation = 12.5; title.font_family = "Yu Gothic"
        state.selected_slot = "B"; state.selected_layers["B"] = title.id; state.zoom = "75%"
        state.subject_points = {"protagonist": [0.3, 0.4]}
        project_path = self.root / "저장 폴더 保存" / "thumbnail_project.json"
        save_project(state, project_path)
        self.assertEqual(self.source_digest, hashlib.sha256(self.source.read_bytes()).hexdigest())
        payload = json.loads(project_path.read_text(encoding="utf-8"))
        for key in ("document_version", "project_path", "candidates", "source_background", "bridge", "palette",
                    "subject_points", "selected_candidate", "selected_layers", "editor_zoom", "app_version"):
            self.assertIn(key, payload)
        self.assertEqual(3, len(list((project_path.parent / "thumbnail_project_assets").glob("*.png"))))
        reopened = load_project(project_path)
        for slot in SLOTS:
            self.assertEqual(state.documents[slot].to_dict(), reopened.documents[slot].to_dict())
            np.testing.assert_array_equal(state.background_image(slot), reopened.background_image(slot))
        self.assertEqual(("B", title.id, "75%"), (reopened.selected_slot, reopened.selected_layers["B"], reopened.zoom))
        renderer = LayerRenderer()
        np.testing.assert_array_equal(renderer.render(state.documents["B"], state.images),
                                      renderer.render(reopened.documents["B"], reopened.images))
        exported = export_candidate(reopened, "B", self.root / "내보내기 出力" / "B.png")
        decoded = cv2.imdecode(np.fromfile(str(exported), np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(renderer.render(reopened.documents["B"], reopened.images), decoded)
        save_project(reopened, project_path)  # re-save is idempotent for content-addressed assets
        self.assertEqual(3, len(list((project_path.parent / "thumbnail_project_assets").glob("*.png"))))
        with self.assertRaises(ValueError):
            bogus = self.root / "bogus.json"; bogus.write_text("{}", encoding="utf-8"); load_project(bogus)


if __name__ == "__main__":
    unittest.main()
