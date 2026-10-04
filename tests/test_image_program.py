import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import image_bridge
import image_program


class ImageProgramTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        env = {k: v for k, v in os.environ.items() if k not in ("IMAGE_PROGRAM_EXE", "IMAGE_BRIDGE_MODE")}
        env.update(YDTS_DATA_DIR=str(self.tmp / "설정 データ"), COVERMORPH_DATA_DIR=str(self.tmp / "covermorph"))
        patcher = mock.patch.dict(os.environ, env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_nothing_configured(self):
        self.assertEqual(image_program.resolve_program(), ("", "none"))
        self.assertEqual(image_program.resolve_mode(), "cli")
        result = image_bridge.launch_generate(self.tmp, "x")
        self.assertFalse(result.launched)
        self.assertIn("연결 설정", result.message)

    def test_saved_program_survives_and_env_still_wins(self):
        exe = self.tmp / "프로그램 東京" / "CoverMorphStudio.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"x")
        image_program.save_program(exe, "json-stdin")
        self.assertEqual(image_program.resolve_program(), (str(exe), "saved"))
        self.assertEqual(image_program.resolve_mode(), "json-stdin")
        self.assertIn("연결됨", image_program.summary())
        with mock.patch.dict(os.environ, {"IMAGE_PROGRAM_EXE": "C:/other.exe"}):
            self.assertEqual(image_program.resolve_program(), ("C:/other.exe", "env"))

    def test_covermorph_auto_discovery(self):
        exe = self.tmp / "cm" / "CoverMorphStudio.exe"
        exe.parent.mkdir()
        exe.write_bytes(b"x")
        (self.tmp / "covermorph").mkdir()
        settings = self.tmp / "covermorph" / "settings.json"
        settings.write_text(json.dumps({"state": {"exe_path": str(exe)}}), encoding="utf-8")
        self.assertEqual(image_program.resolve_program(), (str(exe), "covermorph"))
        settings.write_text("{broken", encoding="utf-8")
        self.assertEqual(image_program.resolve_program(), ("", "none"))


if __name__ == "__main__":
    unittest.main()
