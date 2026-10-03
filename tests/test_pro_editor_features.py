import json
import os
import shutil
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from editor.document import OverlayLayer, TextLayer

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


class InlineThread:
    def __init__(self, target, **_kwargs):
        self.target = target

    def start(self):
        self.target()


class ProEditorFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from app import App
            cls.app = App()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk desktop is unavailable: {exc}")
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name) / "브리지 プロジェクト space"
        shutil.copytree(EXAMPLES / "tokyo_chill_project", cls.folder)
        cls.editor = cls.app.pro_editor
        cls.app.notebook.select(cls.editor)
        cls.app.update()
        cls.editor.open_project_folder(str(cls.folder), synchronous=True)
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()
        cls.temp.cleanup()

    def pump(self):
        for _ in range(3):
            self.app.update()
        if self.editor._render_job is not None:
            self.editor.render_now()

    def key(self, keysym, state=0, widget=None):
        # Tk delivers synthesized key events to the OS-focused widget only, so drive the editor's
        # key handler directly with an explicit source widget (deterministic without desktop focus).
        event = SimpleNamespace(keysym=keysym, state=state, widget=widget or self.editor.canvas)
        result = self.editor._on_key(event)
        self.pump()
        return result

    def test_layer_panel_visibility_lock_rename_reorder_duplicate_delete(self):
        editor = self.editor
        editor.select_slot("A")
        document = editor.document
        subtitle = document.by_role("subtitle")
        editor.select_layer(subtitle.id); self.pump()
        self.assertEqual((subtitle.id,), editor.tree.selection())
        before = editor.frame_bgr.copy()
        editor.toggle_visibility(subtitle.id); self.pump()
        self.assertFalse(subtitle.visible)
        self.assertGreater(float(cv2.absdiff(before, editor.frame_bgr).mean()), 0.01)
        editor.toggle_visibility(subtitle.id); editor.toggle_lock(subtitle.id); self.pump()
        self.assertTrue(subtitle.locked)
        x = subtitle.x
        self.key("Right")
        self.assertEqual(x, subtitle.x)  # locked layers ignore nudges
        editor.toggle_lock(subtitle.id)
        editor.rename_layer("부제 · 영어")
        self.assertEqual("부제 · 영어", editor.tree.item(subtitle.id, "values")[2])
        z = subtitle.z_index
        editor.move_layer(1); self.assertEqual(z + 1, subtitle.z_index)
        editor.move_layer(-1); self.assertEqual(z, subtitle.z_index)
        count = len(document.layers)
        self.key("d", state=0x0004)  # Ctrl+D
        self.assertEqual(count + 1, len(editor.document.layers))
        clone = editor.selected_layer()
        self.assertNotEqual(subtitle.id, clone.id)
        self.key("Delete")
        self.assertEqual(count, len(editor.document.layers))
        self.key("z", state=0x0004)  # Ctrl+Z restores the deleted duplicate
        self.assertEqual(count + 1, len(editor.document.layers))
        self.key("y", state=0x0004)  # Ctrl+Y deletes it again
        self.assertEqual(count, len(editor.document.layers))
        editor.select_layer(subtitle.id)
        self.assertIsNone(self.key("Delete", widget=editor._text_widget))  # typing in the text box
        self.assertIsNone(self.key("d", state=0x0004, widget=editor._text_widget))
        self.assertEqual(count, len(editor.document.layers))

    def test_overlays_effects_palettes_styles_and_channel_preset(self):
        editor = self.editor
        editor.select_slot("B")
        title = editor.document.by_role("main_title")
        editor.select_layer(title.id)
        for kind in ("gradient_black", "gradient_white", "plate", "label_strip", "vignette", "blur_plate"):
            layer = editor.add_overlay(kind)
            self.assertIsInstance(layer, OverlayLayer)
            self.assertEqual(kind, layer.kind)
            if kind != "vignette":
                self.assertLess(layer.z_index, editor.document.by_role("main_title").z_index)
            editor.set_property("strength", 0.3, layer); editor.set_property("blur", 30.0, layer)
            editor.set_property("radius", 12.0, layer); self.pump()
            self.assertEqual((0.3, 30.0, 12.0), (layer.strength, layer.blur, layer.radius))
            editor.delete_layer()
        editor.select_layer(editor.document.by_role("main_title").id)
        editor.apply_effect("이중 외곽선")
        title = editor.document.by_role("main_title")
        self.assertEqual(6.0, title.secondary_outline_width)
        editor.apply_palette("#FFFFFF", "#0B1F33", "#5FD3FF")
        self.assertEqual(("#FFFFFF", "#0B1F33", "#5FD3FF"), (title.fill, title.outline_color, title.highlight_color))
        editor._build_style_cards(); self.pump()
        self.assertEqual(12, len(editor._style_photos))
        editor.apply_style("Warm Gold", "OLD POP LOUNGE")
        self.assertIn("OLD POP LOUNGE|Warm Gold", editor.settings.recent_styles)
        editor.apply_channel_preset("OLD POP LOUNGE")
        self.assertEqual("OLD POP LOUNGE", editor.document.channel)
        self.assertEqual("B_MEMORY", editor.document.candidate_type)
        self.assertEqual(title.text, editor.document.by_role("main_title").text)
        editor.undo()
        self.assertEqual("Tokyo Chill", editor.document.channel)
        text = editor.add_text()
        self.assertIsInstance(text, TextLayer)
        self.assertIsNotNone(editor.add_badge()); self.assertIsNotNone(editor.add_shape())

    def test_shared_metadata_copy_and_reset_across_candidates(self):
        editor = self.editor
        editor.select_slot("A")
        episode = editor.document.by_role("episode_badge")
        editor.select_layer(episode.id)
        editor.shared_lock.set(True); editor.state.shared_lock = True
        editor.set_property("text", "EP.777"); self.pump()
        for slot in "BC":
            self.assertEqual("EP.777", editor.state.documents[slot].by_role("episode_badge").text)
        title = editor.document.by_role("main_title")
        editor.select_layer(title.id)
        editor.set_property("font_size", 77.0); editor._flush_edit()
        editor.copy_layer_to_others()
        self.assertEqual(77.0, editor.state.documents["C"].by_role("main_title").font_size)
        editor.select_slot("C"); editor.reset_slot()
        self.assertNotEqual(77.0, editor.document.by_role("main_title").font_size)
        editor.select_slot("A")
        self.assertEqual(77.0, editor.document.by_role("main_title").font_size)

    def test_reference_panel_extracts_palette_and_guide_is_editor_only(self):
        editor = self.editor
        editor.select_slot("A")
        reference = Path(self.temp.name) / "참고 thumb.png"
        Image.new("RGB", (640, 360), (200, 40, 90)).save(reference)
        editor.load_reference(str(reference))
        palette = editor.extract_reference_palette()
        self.assertEqual(3, len(palette))
        clean = editor.renderer.render(editor.document, editor.state.images)
        editor.make_reference_guide(); self.pump()
        self.assertTrue(editor.show_reference.get())
        exported = editor.export_current(str(Path(self.temp.name) / "guide check.png"))
        decoded = cv2.imdecode(np.fromfile(str(exported), np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(clean, decoded)  # guide ghost never reaches the export
        editor.show_reference.set(False)

    def test_bridge_generate_replaces_background_and_keeps_text_layers(self):
        editor = self.editor
        editor.select_slot("A")
        title = editor.document.by_role("main_title")
        editor.select_layer(title.id)
        editor.set_property("text", "수동 편집 제목"); editor._flush_edit()
        layers_before = {slot: [layer.to_dict() for layer in document.ordered() if layer.type != "background"]
                         for slot, document in editor.state.documents.items()}
        background_before = editor.state.background_image("A").copy()
        exe = Path(self.temp.name) / "fake image program.exe"; exe.touch()

        def fake_run(args, **_kwargs):
            canvas = np.full((720, 1280, 3), (30, 140, 200), np.uint8)
            cv2.imencode(".png", canvas)[1].tofile(str(self.folder / "canvas_clean.png"))
            (self.folder / "subject_boxes.json").write_text(json.dumps({"subjects": [
                {"role": "protagonist", "bbox": [0.0, 0.5, 0.75, 0.5]}]}), encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="ok", stderr="")

        editor.image_prompt.set("rainy Tokyo station, 東京")
        with patch.dict(os.environ, {"IMAGE_PROGRAM_EXE": str(exe), "IMAGE_BRIDGE_MODE": "cli"}), \
                patch("image_bridge.subprocess.run", side_effect=fake_run), \
                patch("editor.ui.threading.Thread", InlineThread), \
                patch.object(editor, "_ask_relayout", return_value="keep") as ask:
            editor.bridge_generate()
            editor._poll_queue()
        ask.assert_called_once()
        self.assertFalse(np.array_equal(background_before, editor.state.background_image("A")))
        for slot, document in editor.state.documents.items():
            self.assertEqual(layers_before[slot],
                             [layer.to_dict() for layer in document.ordered() if layer.type != "background"])
        self.assertIn("충돌", editor.bridge_status.get())
        moved_before = editor.document.by_role("main_title").to_dict()
        editor.bridge_refresh(choice="relayout")
        moved_after = editor.document.by_role("main_title").to_dict()
        self.assertEqual(moved_before["text"], moved_after["text"])
        self.assertNotEqual((moved_before["x"], moved_before["y"]), (moved_after["x"], moved_after["y"]))
        failed = SimpleNamespace(launched=False, message="Image program timed out; previous outputs restored.")
        with patch("editor.ui.messagebox.showerror"):
            editor._bridge_finished("edit", failed)
        self.assertIn("기존", editor.bridge_status.get())

    def test_ctrl_s_saves_atomically_and_autosave_writes_project(self):
        editor = self.editor
        path = Path(self.temp.name) / "단축키 保存" / "thumbnail_project.json"
        editor.state.project_path = path
        self.key("s", state=0x0004)
        self.assertTrue(path.is_file())
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(set("ABC"), set(payload["candidates"]))
        editor._dirty = True
        editor.autosave.set(True)
        editor._autosave_tick()
        self.assertFalse(editor._dirty)
        editor.autosave.set(False); editor._schedule_autosave()
        self.assertEqual([], list(path.parent.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
