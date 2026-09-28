import hashlib
import json
import subprocess
import tempfile
import unittest
import tkinter as tk
from unittest.mock import patch
from pathlib import Path

import cv2
import numpy as np

from motion_engine import _ffmpeg_executable, render
from thumbnail_engine import _crop_resize, _map_point_to_full_frame, create_candidate_images, generate_candidates


def write_unicode(path, image):
    ok, data = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("fixture encoding failed")
    data.tofile(str(path))


class CandidateValidation(unittest.TestCase):
    def run_case(self, input_name, output_name):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw:
            root = Path(raw); source_dir = root / input_name; output_dir = root / output_name
            source_dir.mkdir()
            y, x = np.indices((900, 1400))
            image = np.dstack(((x % 256), (y % 256), ((x + y) % 256))).astype(np.uint8)
            source = source_dir / "東京 서울 원본.png"; write_unicode(source, image)
            before = hashlib.sha256(source.read_bytes()).hexdigest()
            made = generate_candidates(source, output_dir, "Tokyo Chill", "텍스트 없는 원본 이미지")
            self.assertEqual(3, len(made)); self.assertEqual(before, hashlib.sha256(source.read_bytes()).hexdigest())
            jpgs = sorted(output_dir.glob("*.jpg")); manifests = list(output_dir.glob("*manifest.json"))
            self.assertEqual(3, len(jpgs)); self.assertEqual(1, len(manifests))
            decoded = []
            for path in jpgs:
                data = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
                self.assertEqual((720, 1280), data.shape[:2]); decoded.append(data)
            differences = [float(np.mean(cv2.absdiff(decoded[i], decoded[j]))) for i, j in ((0, 1), (0, 2), (1, 2))]
            self.assertTrue(all(value > 2.0 for value in differences), differences)
            manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
            self.assertEqual("0.3.1", manifest["version"]); self.assertEqual(3, len(manifest["candidates"]))

    def test_ascii_paths(self):
        self.run_case("ascii input", "ascii output")

    def test_korean_japanese_space_paths(self):
        self.run_case("한글 입력 東京 space", "결과 保存 폴더")

    def test_motion_korean_japanese_path(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw:
            root = Path(raw) / "모션 東京 space"; root.mkdir()
            source = root / "입력 画像.png"; output = root / "출력 動画.mp4"
            image = np.full((180, 320, 3), (60, 100, 180), dtype=np.uint8)
            write_unicode(source, image)
            render(source, output, "Tokyo Chill - Rain", duration=0.2, fps=2, width=320, height=180)
            self.assertTrue(output.exists()); self.assertGreater(output.stat().st_size, 0)

    def test_motion_uses_bundled_encoder_without_path_ffmpeg(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw:
            root = Path(raw); source = root / "모션 입력.png"; output = root / "모션 출력.mp4"
            write_unicode(source, np.full((360, 640, 3), (60, 100, 180), dtype=np.uint8))
            with patch("motion_engine.shutil.which", return_value=None):
                render(source, output, "Tokyo Chill - Rain", duration=1, fps=2, width=640, height=360)
            self.assertTrue(output.exists()); self.assertGreater(output.stat().st_size, 0)
            probe = subprocess.run([_ffmpeg_executable(), "-v", "error", "-i", str(output), "-f", "null", "-"], capture_output=True)
            self.assertEqual(0, probe.returncode, probe.stderr.decode(errors="replace"))

    def test_completed_thumbnail_is_full_frame_and_never_crops(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw:
            source = Path(raw) / "completed.png"
            y, x = np.indices((720, 1280))
            image = np.dstack((x % 256, y % 256, (x + y) % 256)).astype(np.uint8)
            image[20:130, 70:700] = (255, 255, 255)  # baked-in title block
            image[600:680, 1080:1250] = (10, 240, 240)  # logo/episode block
            write_unicode(source, image)
            with patch("thumbnail_engine._safe_crop", side_effect=AssertionError("completed mode must not crop")), \
                 patch("thumbnail_engine._crop_resize", side_effect=AssertionError("completed mode must not crop")):
                candidates = create_candidate_images(source, "Tokyo Chill", protagonist=(0.30, 0.50), counterpart=(0.72, 0.50))
            self.assertEqual(["A_PERSON", "B_EMOTION", "C_STORY"], [c.code for c in candidates])
            self.assertEqual((720, 1280), candidates[2].image.shape[:2])
            np.testing.assert_array_equal(image, candidates[2].image)
            for candidate in candidates[:2]:
                self.assertIn("크롭 금지", candidate.composition)
                self.assertEqual((720, 1280), candidate.image.shape[:2])
            self.assertGreater(float(np.mean(cv2.absdiff(candidates[0].image, candidates[1].image))), 0.1)
            base = candidates[2].image
            for cx in (0.30, 0.72):
                x0, x1 = int(cx * 1280) - 60, int(cx * 1280) + 60
                self.assertGreater(float(np.mean(cv2.absdiff(candidates[1].image[300:420, x0:x1], base[300:420, x0:x1]))), 0.05)
            main_roi = cv2.absdiff(candidates[0].image[300:420, 0:500], base[300:420, 0:500]).mean()
            other_roi = cv2.absdiff(candidates[0].image[300:420, 800:1100], base[300:420, 800:1100]).mean()
            self.assertGreater(float(main_roi), float(other_roi))

    def test_raw_mode_retains_safe_crop_and_protagonist_overrides_detection(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw:
            source = Path(raw) / "raw.png"
            image = np.full((900, 1600, 3), 100, dtype=np.uint8)
            image[:, :800] = (70, 70, 70); image[:, 800:] = (180, 180, 180)
            write_unicode(source, image)
            with patch("thumbnail_engine._detect_faces", return_value=[(720, 320, 120, 140)]):
                candidates = create_candidate_images(source, "Tokyo Chill", "텍스트 없는 원본 이미지", protagonist=(0.24, 0.48))
            self.assertEqual(3, len(candidates))
            with patch("thumbnail_engine._detect_faces", return_value=[(720, 320, 120, 140)]), \
                 patch("thumbnail_engine._crop_resize", wraps=_crop_resize) as crop_resize:
                create_candidate_images(source, "Tokyo Chill", "텍스트 없는 원본 이미지")
            crop_resize.assert_called()
            self.assertEqual((720, 1280), candidates[0].image.shape[:2])
            self.assertIn("수동 지정 인물", candidates[0].composition)
            self.assertGreater(float(np.mean(cv2.absdiff(candidates[0].image, candidates[1].image))), 0.1)

    def test_normalized_manual_point_controls_emphasis_after_resize(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw:
            source = Path(raw) / "coordinates.png"
            y, x = np.indices((360, 640))
            checker = ((x // 8 + y // 8) % 2 * 100 + 70).astype(np.uint8)
            image = np.dstack((checker, np.roll(checker, 2, axis=0), np.roll(checker, 3, axis=1)))
            write_unicode(source, image)
            left = create_candidate_images(source, "Tokyo Chill", protagonist=(0.25, 0.30))[0].image
            right = create_candidate_images(source, "Tokyo Chill", protagonist=(0.75, 0.30))[0].image
            self.assertEqual((720, 1280), left.shape[:2])
            self.assertGreater(float(np.mean(cv2.absdiff(left, right))), 0.1)

    def test_manual_point_maps_through_no_crop_letterboxing(self):
        mapped = _map_point_to_full_frame((0.10, 0.50), (1000, 800, 3))
        self.assertGreater(mapped[0], 0.10)
        self.assertAlmostEqual(0.50, mapped[1], places=5)

    def test_manual_point_overrides_face_detector(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw:
            source = Path(raw) / "profile.png"
            y, x = np.indices((360, 640))
            checker = ((x // 8 + y // 8) % 2 * 100 + 70).astype(np.uint8)
            write_unicode(source, np.dstack((checker, checker, checker)))
            point = (0.72, 0.40)
            with patch("thumbnail_engine._detect_faces", return_value=[(70, 70, 100, 140)]):
                first = create_candidate_images(source, "Tokyo Chill", protagonist=point)[0].image
            with patch("thumbnail_engine._detect_faces", return_value=[(470, 80, 110, 130)]):
                second = create_candidate_images(source, "Tokyo Chill", protagonist=point)[0].image
            np.testing.assert_array_equal(first, second)

    def test_gui_manual_point_selection_and_source_reset(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw:
            first = Path(raw) / "first.png"; second = Path(raw) / "second.png"
            image = np.full((360, 640, 3), 120, dtype=np.uint8)
            write_unicode(first, image); write_unicode(second, image)
            try:
                from app import App
                app = App()
            except tk.TclError as exc:
                self.skipTest(f"Tk desktop is unavailable: {exc}")
            try:
                app.src.set(str(first)); app.update()
                self.assertEqual("글자/로고 보호 ON · 크롭 금지", app.mode_guard.get())
                app.select_point("protagonist"); app.update()
                app.selection_canvas.event_generate("<Button-1>", x=250, y=220); app.update()
                self.assertGreaterEqual(len(app.selection_canvas.find_all()), 3)
                app.selection_apply_button.invoke(); app.update()
                self.assertAlmostEqual(0.25, app.protagonist[0], places=2)
                app.select_point("counterpart"); app.update()
                app.selection_canvas.event_generate("<Button-1>", x=700, y=300); app.update()
                app.selection_apply_button.invoke(); app.update()
                self.assertIsNotNone(app.counterpart)
                app.src.set(str(second)); app.update()
                self.assertIsNone(app.protagonist); self.assertIsNone(app.counterpart)
                app.source_mode.set("텍스트 없는 원본 이미지")
                self.assertEqual("원본 이미지 모드 · 안전 크롭 허용", app.mode_guard.get())
            finally:
                app.destroy()

    def test_one_and_multiple_faces_are_supported(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as raw:
            source = Path(raw) / "people.png"
            y, x = np.indices((900, 1400))
            image = np.dstack((x % 256, y % 256, (x + y) % 256)).astype(np.uint8)
            write_unicode(source, image)
            for boxes in ([(500, 260, 150, 190)], [(400, 270, 130, 170), (720, 250, 150, 190)]):
                with patch("thumbnail_engine._detect_faces", return_value=boxes):
                    candidates = create_candidate_images(source, "Tokyo Chill", "텍스트 없는 원본 이미지")
                self.assertEqual(3, len(candidates))
                self.assertTrue(all(candidate.image.shape[:2] == (720, 1280) for candidate in candidates))
                self.assertIn(f"얼굴 {len(boxes)}명 보호", candidates[0].composition)
            with patch("thumbnail_engine._detect_faces", return_value=[(30, 240, 150, 190), (1210, 250, 150, 190)]):
                wide_group = create_candidate_images(source, "Tokyo Chill", "텍스트 없는 원본 이미지")
            self.assertIn("전체 원본 안전 구도", wide_group[0].composition)


if __name__ == "__main__":
    unittest.main()
