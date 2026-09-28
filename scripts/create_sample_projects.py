"""Create deterministic, text-free Image Bridge sample projects."""
from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1] / "examples"


def write_project(name: str, channel: str, title: str, subtitle: str, episode: str,
                  story: str, style: str, palette: dict, subjects: list,
                  safe_zones: list, composition: dict, scene: str) -> None:
    folder = ROOT / name
    folder.mkdir(parents=True, exist_ok=True)
    height, width = 720, 1280
    y, x = np.mgrid[0:height, 0:width]
    if scene == "tokyo":
        t = (y / height)[..., None]
        top = np.array([45, 34, 54], dtype=np.float32)
        bottom = np.array([126, 87, 101], dtype=np.float32)
        image = np.broadcast_to((top * (1 - t) + bottom * t), (height, width, 3)).copy().astype(np.uint8)
        for index, bx in enumerate(range(15, width, 115)):
            bh = 130 + (index * 67) % 220
            cv2.rectangle(image, (bx, height - bh), (bx + 72, height), (42, 47, 69), -1)
            for wy in range(height - bh + 18, height - 20, 38):
                for wx in range(bx + 12, bx + 68, 25):
                    cv2.rectangle(image, (wx, wy), (wx + 7, wy + 11), (128, 174, 194), -1)
        cv2.circle(image, (930, 230), 148, (87, 98, 130), -1)
        cv2.circle(image, (930, 230), 116, (69, 77, 112), -1)
        cv2.ellipse(image, (775, 526), (116, 194), 0, 180, 360, (32, 44, 67), -1)
        cv2.circle(image, (775, 315), 76, (212, 168, 133), -1)
        cv2.ellipse(image, (1026, 550), (116, 180), 0, 180, 360, (102, 123, 159), -1)
        cv2.circle(image, (1026, 350), 72, (228, 190, 161), -1)
        cv2.line(image, (0, 598), (width, 480), (192, 145, 133), 5, cv2.LINE_AA)
    else:
        t = (x / width)[..., None]
        left = np.array([42, 47, 67], dtype=np.float32)
        right = np.array([103, 111, 139], dtype=np.float32)
        image = np.broadcast_to((left * (1 - t) + right * t), (height, width, 3)).copy().astype(np.uint8)
        cv2.rectangle(image, (0, 510), (width, height), (36, 45, 63), -1)
        cv2.circle(image, (900, 345), 220, (179, 147, 110), -1)
        cv2.circle(image, (900, 345), 194, (61, 61, 72), -1)
        cv2.circle(image, (900, 345), 46, (178, 145, 105), -1)
        cv2.ellipse(image, (318, 569), (176, 95), -9, 0, 360, (175, 129, 82), -1)
        cv2.ellipse(image, (318, 554), (145, 69), -9, 0, 360, (47, 51, 64), -1)
        for bx, by in ((79, 83), (226, 91), (367, 70), (1027, 85), (1141, 111)):
            cv2.rectangle(image, (bx, by), (bx + 84, by + 117), (183, 164, 131), -1)
            cv2.rectangle(image, (bx + 7, by + 8), (bx + 77, by + 108), (67, 75, 91), -1)
    canvas = folder / "canvas_clean.png"
    if not cv2.imwrite(str(canvas), image):
        raise RuntimeError(f"Unable to write {canvas}")
    if not cv2.imwrite(str(folder / "preview_reference.png"), image):
        raise RuntimeError(f"Unable to write preview image in {folder}")
    files = {
        "project_manifest.json": {"schema_version": 1, "channel": channel, "title": title,
            "subtitle": subtitle, "episode": episode, "story_type": story,
            "preferred_typography": style},
        "subject_boxes.json": {"schema_version": 1, "coordinate_space": "normalized",
            "subjects": subjects},
        "safe_zones.json": {"schema_version": 1, "coordinate_space": "normalized",
            "safe_zones": safe_zones},
        "palette.json": palette,
        "composition.json": {"schema_version": 1, "coordinate_space": "normalized",
            "positions": composition},
    }
    for filename, payload in files.items():
        (folder / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(folder)


def main() -> None:
    write_project("tokyo_chill_project", "Tokyo Chill", "雨の夜、君を思う", "A quiet story in Tokyo",
        "EP.014", "ROMANTIC NEON", "Romantic Neon",
        {"fill_color": "#FFF8E9", "stroke_color": "#14213D", "highlight_color": "#FF5E9C",
         "glow_strength": 0.8, "shadow_strength": 0.75, "outline_width": 9},
        [{"role": "protagonist", "bbox": [0.54, 0.22, 0.18, 0.5]},
         {"role": "counterpart", "bbox": [0.75, 0.28, 0.16, 0.48]}],
        [[0.04, 0.08, 0.35, 0.25]],
        {"channel_label": [0.03, 0.03, 0.22, 0.08], "main_title": [0.05, 0.63, 0.62, 0.3],
         "subtitle": [0.05, 0.91, 0.7, 0.06]}, "tokyo")
    write_project("old_pop_lounge_project", "OLD POP LOUNGE", "첫눈에 다시 만난 날", "A winter song from 1978",
        "EP.008", "FIRST SNOW", "First Snow",
        {"colors": {"fill": "#FFF1D0", "stroke": "#241A18", "accent": "#D6A657"},
         "effects": {"glow": 0.35, "shadow": 0.65, "outline_width": 7}},
        [{"role": "protagonist", "bbox": [0.18, 0.2, 0.24, 0.56]}],
        [[0.46, 0.08, 0.48, 0.32]],
        {"channel_label": [0.03, 0.03, 0.26, 0.08], "main_title": [0.48, 0.58, 0.47, 0.31],
         "subtitle": [0.5, 0.91, 0.45, 0.06]}, "oldpop")


if __name__ == "__main__":
    main()
