import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from motion_engine import render
from thumbnail_engine import generate_candidates


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
            made = generate_candidates(source, output_dir, "Tokyo Chill")
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
            self.assertEqual("0.3", manifest["version"]); self.assertEqual(3, len(manifest["candidates"]))

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


if __name__ == "__main__":
    unittest.main()
