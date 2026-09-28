import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from image_bridge import launch_edit, launch_generate, load_image_project


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

    def test_launcher_abstraction_reports_unconfigured_program_cleanly(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(launch_generate(temp, executable="").launched)
            self.assertFalse(launch_edit(temp, executable="missing-image-program.exe").launched)


if __name__ == "__main__":
    unittest.main()
