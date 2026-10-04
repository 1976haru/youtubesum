import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from image_bridge import launch_edit, launch_generate, load_image_project, refresh_project


class ImageBridgeTests(unittest.TestCase):
    def _project(self, root: Path):
        image = root / "canvas_clean.png"
        Image.new("RGB", (640, 360), (70, 90, 120)).save(image)
        Image.new("RGB", (640, 360), (20, 30, 40)).save(root / "preview_reference.png")
        (root / "subject_boxes.json").write_text(json.dumps({
            "image_size": {"width": 1280, "height": 720},
            "subjects": [{"role": "protagonist", "bbox": [0.2, 0.25, 0.2, 0.4]},
                         {"role": "counterpart", "bbox": [0.65, 0.3, 0.15, 0.35]}]}), encoding="utf-8")
        (root / "safe_zones.json").write_text(json.dumps({
            "canvas_size": [1280, 720], "zones": [[0.05, 0.1, 0.25, 0.2]]}), encoding="utf-8")
        (root / "palette.json").write_text(json.dumps({
            "colors": {"fill": "#FFF1D0", "stroke": "#242018", "accent": "#ED8B43"},
            "effects": {"glow": 0.35, "shadow": 0.72, "outline_width": 8}}), encoding="utf-8")
        (root / "composition.json").write_text(json.dumps({
            "positions": {"main_title": [0.1, 0.65, 0.6, 0.25]}}), encoding="utf-8")
        (root / "project_manifest.json").write_text(json.dumps({
            "project": {"channel": "OLD POP LOUNGE", "title": "첫눈에 다시 만난 날",
                        "subtitle": "A song from 1978", "episode": 12,
                        "story_type": "FIRST SNOW", "preferred_typography": "First Snow"}}), encoding="utf-8")

    def test_parser_maps_boxes_palette_manifest_and_composition(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self._project(root)
            project = load_image_project(root)
        self.assertEqual("canvas_clean.png", project.source_image.name)
        self.assertEqual("preview_reference.png", project.reference_image.name)
        self.assertEqual((64, 72, 320, 144), project.safe_zones[0]["bbox"])
        self.assertEqual((128, 90, 128, 144), project.subject_boxes[0]["bbox"])
        self.assertEqual((0.3, 0.45), tuple(round(v, 2) for v in project.subject_points["protagonist"]))
        self.assertEqual("#FFF1D0", project.palette["fill_color"])
        self.assertEqual(0.35, project.palette["glow_strength"])
        self.assertEqual((128, 468, 768, 180), project.composition["positions"]["main_title"])
        self.assertEqual("OLD POP LOUNGE", project.manifest["channel"])
        self.assertEqual("First Snow", project.manifest["preferred_typography"])
        self.assertTrue(all(project.status[key] for key in ("clean_canvas", "reference", "subjects", "safe_zones", "palette", "composition", "manifest")))

    def test_missing_sidecars_fall_back_to_local_image_and_legacy_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            Image.new("RGB", (320, 180), (30, 50, 80)).save(root / "cover.png")
            project = load_image_project(root)
            self.assertEqual("cover.png", project.source_image.name)
            self.assertFalse(project.status["manifest"])
            Image.new("RGB", (320, 180), (10, 20, 30)).save(root / "cleaned_canvas.png")
            (root / "safe_zone.json").write_text('{"zones": [[0.1, 0.1, 0.2, 0.2]]}', encoding="utf-8")
            project = load_image_project(root)
            self.assertEqual("cleaned_canvas.png", project.source_image.name)
            self.assertTrue(project.status["clean_canvas"])
            self.assertTrue(project.status["safe_zones"])

    def test_invalid_sidecar_schema_is_reported_without_aborting_project_load(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self._project(root)
            (root / "subject_boxes.json").write_text('{"image_size":{"width":"bad","height":0},"subjects":[{"bbox":{"x1":"nope"}}]}', encoding="utf-8")
            (root / "safe_zones.json").write_text('{"canvas_size":"not-a-size","zones":"invalid"}', encoding="utf-8")
            project = load_image_project(root)
            self.assertEqual((), project.subject_boxes)
            self.assertEqual((), project.safe_zones)
            self.assertFalse(project.status["subjects"])
            self.assertFalse(project.status["safe_zones"])
            self.assertTrue(project.warnings)

    def test_launcher_abstraction_reports_unconfigured_program_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(launch_generate(temp, executable="").launched)
            self.assertFalse(launch_edit(temp, executable="missing-image-program.exe").launched)
            exe = Path(temp) / "fake.exe"; exe.touch()
            with patch.dict(os.environ, {"IMAGE_BRIDGE_MODE": "unsupported", "IMAGE_PROJECT_ROOT": temp}):
                rooted = launch_generate(None, executable=exe)
                self.assertEqual(Path(temp).resolve(), rooted.project_dir)
                self.assertIn("Unsupported IMAGE_BRIDGE_MODE", rooted.message)

    def test_cli_subprocess_contract_captures_logs_and_refreshes_sidecars(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self._project(root)
            exe = root / "fake image.exe"; exe.touch()
            observed = {}

            def fake_run(args, **kwargs):
                observed["args"] = args; observed.update(kwargs)
                self.assertIn("--project-dir", args); self.assertIn(str(root), args)
                self.assertEqual("Rainy station, 東京", args[args.index("--prompt") + 1])
                Image.new("RGB", (640, 360), (90, 50, 20)).save(root / "canvas_clean.png")
                (root / "project_manifest.json").write_text('{"channel":"Tokyo Chill","title":"New output"}', encoding="utf-8")
                return SimpleNamespace(returncode=0, stdout="generated ok", stderr="")

            with patch.dict(os.environ, {"IMAGE_BRIDGE_MODE": "cli"}), patch("image_bridge.subprocess.run", side_effect=fake_run):
                result = launch_generate(root, "Rainy station, 東京", {"channel": "Tokyo Chill", "title": "Input title"}, executable=exe)
            self.assertTrue(result.launched, result.message)
            self.assertEqual(0, result.return_code)
            self.assertEqual("generated ok", result.stdout)
            self.assertTrue(observed["capture_output"])
            self.assertTrue(observed["text"])
            self.assertEqual("New output", result.project.manifest["title"])
            self.assertEqual("New output", refresh_project(root).manifest["title"])

    def test_json_stdin_edit_contract_passes_context_and_instruction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self._project(root); exe = root / "fake.exe"; exe.touch()
            observed = {}

            def fake_run(args, **kwargs):
                observed["args"] = args; observed["input"] = json.loads(kwargs["input"])
                Image.new("RGB", (640, 360), (100, 80, 60)).save(root / "canvas_clean.png")
                return SimpleNamespace(returncode=0, stdout="edited", stderr="")

            with patch.dict(os.environ, {"IMAGE_BRIDGE_MODE": "json-stdin"}), patch("image_bridge.subprocess.run", side_effect=fake_run):
                result = launch_edit(root, "keep the faces; soften background", {"channel": "OLD POP LOUNGE"}, executable=exe)
            self.assertTrue(result.launched, result.message)
            self.assertEqual([str(exe), "--image-bridge"], observed["args"])
            self.assertEqual("edit", observed["input"]["action"])
            self.assertEqual("keep the faces; soften background", observed["input"]["edit_instruction"])
            self.assertEqual("OLD POP LOUNGE", observed["input"]["channel"])

    def test_nonzero_and_timeout_restore_previous_outputs(self):
        for outcome in ("failure", "timeout"):
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory() as temp:
                root = Path(temp); self._project(root); exe = root / "fake.exe"; exe.touch()
                canvas = root / "canvas_clean.png"; before = canvas.read_bytes()

                def fake_run(args, **kwargs):
                    Image.new("RGB", (640, 360), (250, 1, 1)).save(canvas)
                    if outcome == "timeout":
                        raise subprocess.TimeoutExpired(args, 1, output="partial", stderr="still working")
                    return SimpleNamespace(returncode=7, stdout="", stderr="image error")

                with patch("image_bridge.subprocess.run", side_effect=fake_run):
                    result = launch_generate(root, executable=exe, timeout=1)
                self.assertFalse(result.launched)
                self.assertEqual(before, canvas.read_bytes())
                self.assertIn("restored", result.message)
                self.assertEqual(outcome == "timeout", result.timed_out)

    def test_missing_canvas_is_rejected_and_partial_sidecars_are_preserved_with_warning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self._project(root); exe = root / "fake.exe"; exe.touch()
            canvas = root / "canvas_clean.png"; before = canvas.read_bytes()
            with patch("image_bridge.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")):
                missing = launch_generate(root, executable=exe)
            self.assertFalse(missing.launched)
            self.assertEqual(before, canvas.read_bytes())

            previous_safe = (root / "safe_zones.json").read_text(encoding="utf-8")
            def partial_run(args, **kwargs):
                Image.new("RGB", (640, 360), (120, 110, 100)).save(canvas)
                (root / "safe_zones.json").unlink()
                return SimpleNamespace(returncode=0, stdout="partial outputs", stderr="")

            with patch("image_bridge.subprocess.run", side_effect=partial_run):
                partial = launch_edit(root, "desaturate", executable=exe)
            self.assertTrue(partial.launched, partial.message)
            self.assertEqual(previous_safe, (root / "safe_zones.json").read_text(encoding="utf-8"))
            self.assertTrue(any("safe_zones.json" in warning for warning in partial.warnings))


if __name__ == "__main__":
    unittest.main()
