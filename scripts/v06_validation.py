"""v0.6 manual-validation run: four channel scenarios through the real Pro Editor GUI.

For each scenario it opens the project folder in the editor, applies a realistic edit
(display font + 배경에 맞춤), captures the actual window, exports 1280x720 / 340 / 180
images, records the readability meter, measures live slider/drag latency with real Tk
events, and builds a before (legacy v0.5.1 renderer) / after (v0.6 editor) sheet.

    py -3.10 scripts\\v06_validation.py            -> build\\v06_validation\\
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import App  # noqa: E402

from editor.io_utils import write_image  # noqa: E402
from editor.project import ink_box  # noqa: E402
from editor.selftest import _canvas_point, _pump, _stamp, capture_window  # noqa: E402
from thumbnail_engine import TEMPLATE_MODE, create_candidate_images  # noqa: E402
from typography.background_fit import analyze_text_region, readability_report  # noqa: E402
from typography.layer_renderer import downscale  # noqa: E402
from typography.text_style import get_preset  # noqa: E402

OUT = ROOT / "build" / "v06_validation"


def _figure(image, cx, cy, scale, body, skin, hair=None):
    cv2.ellipse(image, (cx, cy + int(210 * scale)), (int(120 * scale), int(200 * scale)), 0, 180, 360, body, -1, cv2.LINE_AA)
    cv2.circle(image, (cx, cy), int(74 * scale), skin, -1, cv2.LINE_AA)
    if hair is not None:
        cv2.ellipse(image, (cx, cy - int(22 * scale)), (int(78 * scale), int(56 * scale)), 0, 180, 360, hair, -1, cv2.LINE_AA)


def _write_project(folder: Path, image, manifest, subjects, safe_zones, palette=None):
    folder.mkdir(parents=True, exist_ok=True)
    write_image(folder / "canvas_clean.png", image)
    write_image(folder / "preview_reference.png", image)
    files = {"project_manifest.json": {"schema_version": 1, **manifest},
             "subject_boxes.json": {"schema_version": 1, "coordinate_space": "normalized", "subjects": subjects},
             "safe_zones.json": {"schema_version": 1, "coordinate_space": "normalized", "safe_zones": safe_zones}}
    if palette:
        files["palette.json"] = palette
    for name, payload in files.items():
        (folder / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def tokyo_one_person(folder: Path) -> None:
    height, width = 720, 1280
    t = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    image = (np.array([60, 28, 22], np.float32) * (1 - t) + np.array([120, 70, 64], np.float32) * t)
    image = np.broadcast_to(image, (height, width, 3)).astype(np.uint8).copy()
    for index, x in enumerate(range(-20, width, 140)):
        top = 180 + (index * 97) % 230
        cv2.rectangle(image, (x, top), (x + 110, height), (48, 32, 30), -1)
        for wy in range(top + 20, height - 30, 34):
            for wx in range(x + 12, x + 100, 26):
                if (wx * 7 + wy) % 5:
                    cv2.rectangle(image, (wx, wy), (wx + 8, wy + 12), (90, 200, 245), -1)
    for x in range(0, width, 9):  # rain streaks
        cv2.line(image, (x, (x * 37) % 700), (x - 6, (x * 37) % 700 + 26), (210, 190, 180), 1, cv2.LINE_AA)
    cv2.rectangle(image, (0, 620), (width, height), (40, 26, 24), -1)
    _figure(image, 905, 300, 1.25, (38, 30, 34), (150, 178, 214), hair=(25, 22, 24))
    _write_project(folder, image, {"channel": "Tokyo Chill", "title": "終電を逃した夜、僕は", "subtitle": "One man, one last train",
                                   "episode": "EP.021", "story_type": "MAN STORY", "preferred_typography": "Night Drive"},
                   [{"role": "protagonist", "bbox": [0.6, 0.27, 0.22, 0.73]}], [[0.03, 0.04, 0.28, 0.12]])


def oldpop_couple(folder: Path) -> None:
    height, width = 720, 1280
    t = np.linspace(0, 1, width, dtype=np.float32)[None, :, None]
    image = (np.array([60, 82, 120], np.float32) * (1 - t) + np.array([92, 128, 168], np.float32) * t)
    image = np.broadcast_to(image, (height, width, 3)).astype(np.uint8).copy()
    cv2.rectangle(image, (0, 520), (width, height), (40, 58, 86), -1)
    cv2.rectangle(image, (80, 70), (380, 330), (190, 205, 215), -1)
    cv2.rectangle(image, (92, 82), (368, 318), (150, 120, 96), -1)
    cv2.line(image, (230, 82), (230, 318), (190, 205, 215), 8)
    cv2.circle(image, (1120, 120), 50, (120, 200, 245), -1, cv2.LINE_AA)
    _figure(image, 560, 290, 1.1, (60, 50, 120), (150, 180, 220), hair=(40, 40, 50))
    _figure(image, 790, 310, 1.05, (90, 70, 40), (160, 190, 228), hair=(60, 60, 70))
    _write_project(folder, image, {"channel": "OLD POP LOUNGE", "title": "다시 만난 그 겨울", "subtitle": "A duet from 1982",
                                   "episode": "EP.011", "story_type": "COUPLE", "preferred_typography": "Warm Gold"},
                   [{"role": "protagonist", "bbox": [0.36, 0.28, 0.2, 0.58]},
                    {"role": "counterpart", "bbox": [0.53, 0.31, 0.19, 0.56]}], [[0.05, 0.08, 0.26, 0.38]],
                   {"colors": {"fill": "#FFF4DC", "stroke": "#3A2618", "accent": "#F2C46B"}})


SCENARIOS = (
    ("tokyo_two_person_relationship", lambda folder: shutil.copytree(ROOT / "examples" / "tokyo_chill_project", folder)),
    ("tokyo_one_person_male_story", tokyo_one_person),
    ("oldpop_couple", oldpop_couple),
    ("oldpop_scenery", lambda folder: shutil.copytree(ROOT / "examples" / "old_pop_lounge_project", folder)),
)


def _label(image, text):
    out = image.copy()
    cv2.rectangle(out, (0, 0), (out.shape[1], 26), (20, 20, 24), -1)
    cv2.putText(out, text, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1, cv2.LINE_AA)
    return out


def _legacy(editor, source):
    state = editor.state
    texts = state.texts
    return create_candidate_images(str(source), state.channel, TEMPLATE_MODE, "자동", None, None, texts.get("story", "자동"),
                                   texts.get("episode", ""), texts.get("title", ""), texts.get("subtitle", ""),
                                   state.style, title_size=108)


def _legacy_readability(state, candidate, base, subject_boxes):
    meta = candidate.typography or {}
    bbox = meta.get("title", {}).get("bbox") or meta.get("title_box")
    preset = get_preset(state.style, state.channel)
    analysis = analyze_text_region(base, bbox, subject_boxes)
    size = meta.get("title", {}).get("font_size", 100)
    return readability_report({"fill": preset.fill, "outline_color": preset.outline, "outline_width": preset.outline_width,
                               "font_size": size, "shadow_opacity": 0.7}, analysis)


def measure_latency(app, editor) -> dict:
    """Real Tk events: slider moves on the font-size field and drag motion on the canvas."""
    editor.select_slot("A"); _pump(app)
    title = editor.document.by_role("main_title")
    editor.select_layer(title.id); _pump(app)
    field = editor._fields["font_size"]
    slider = []
    base = title.font_size
    for step in range(16):
        start = time.perf_counter()
        field.var.set(base + (step % 8) * 2 - 6); field._from_scale()
        while editor._render_job is not None:
            app.update()
        slider.append((time.perf_counter() - start) * 1000)
    press_mode, attempts = None, 0
    while press_mode is None and attempts < 4:  # let pending <Configure>/zoom-to-fit settle first
        attempts += 1
        _pump(app, 0.25)
        title = editor.document.by_role("main_title")
        cx, cy = title.center
        sx, sy = _canvas_point(editor, cx, cy)
        editor.canvas.event_generate("<ButtonPress-1>", x=sx, y=sy, time=_stamp()); app.update()
        press_mode = editor._drag["mode"] if editor._drag else None
        if press_mode is None:
            editor.canvas.event_generate("<ButtonRelease-1>", x=sx, y=sy, time=_stamp()); app.update()
    drag = []
    for step in range(1, 21):
        start = time.perf_counter()
        editor.canvas.event_generate("<B1-Motion>", x=sx + step * 6, y=sy - step * 2, state=0x100, time=_stamp())
        app.update()
        while editor._render_job is not None:
            app.update()
        drag.append((time.perf_counter() - start) * 1000)
    editor.canvas.event_generate("<ButtonRelease-1>", x=sx + 120, y=sy - 40, state=0x100, time=_stamp()); _pump(app)
    editor.undo(); _pump(app)
    for _ in range(16):
        editor.undo()
    _pump(app)

    def stats(values):
        ordered = sorted(values)
        return {"samples": len(values), "median_ms": round(ordered[len(ordered) // 2], 1),
                "p90_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))], 1), "max_ms": round(ordered[-1], 1)}
    return {"slider_font_size": stats(slider), "canvas_drag": {**stats(drag), "press_mode": press_mode, "press_attempts": attempts}}


def run() -> dict:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    app = App()
    editor = app.pro_editor
    app.notebook.select(editor)
    app.geometry("1600x1000+10+10")
    _pump(app, 0.3)
    deadline = time.perf_counter() + 60
    while not editor.font_browser.catalog and time.perf_counter() < deadline:
        _pump(app, 0.1)
    names = {family.name for family in editor.font_browser.catalog}
    summary = {}
    try:
        for name, build in SCENARIOS:
            folder = OUT / "projects" / name
            build(folder)
            target = OUT / name
            target.mkdir(parents=True, exist_ok=True)
            editor.open_project_folder(str(folder), synchronous=True)
            editor.zoom_choice.set("Fit"); editor._apply_zoom(); _pump(app, 0.2)
            before_frames = {slot: editor.renderer.render(editor.state.documents[slot], editor.state.images) for slot in "ABC"}
            hangul = any("가" <= char <= "힣" for char in editor.state.texts.get("title", ""))
            choices = ("Malgun Gothic", "Noto Sans KR") if hangul else ("Yu Gothic", "Meiryo", "BIZ UDPGothic")
            family = next((item for item in choices if item in names), "")
            reports = {}
            for slot in "ABC":
                editor.select_slot(slot); _pump(app)
                title = editor.document.by_role("main_title")
                editor.select_layer(title.id)
                if family:
                    editor.apply_font(family)
                reports[slot] = editor.apply_background_fit("fit")
                _pump(app, 0.1)
            editor.select_slot("A"); _pump(app)
            editor.select_layer(editor.document.by_role("main_title").id); editor.update_meter(); _pump(app, 0.2)
            capture_window(app, target / "editor_window.png")
            editor.inspector_tabs.select(editor.font_browser); editor.font_browser.script.set("Korean" if hangul else "Japanese")
            editor.font_browser.refresh(); _pump(app, 1.0)
            capture_window(app, target / "editor_window_font_browser.png")
            editor.inspector_tabs.select(editor.props_scroll); _pump(app)
            latency = measure_latency(app, editor)
            legacy = _legacy(editor, editor.state.source_background)
            legacy_bases = {c.code: c.image for c in create_candidate_images(
                editor.state.source_background, editor.state.channel, TEMPLATE_MODE, render_text=False)}
            rows, slot_results = [], {}
            for slot, candidate in zip("ABC", legacy):
                after = editor.renderer.render(editor.state.documents[slot], editor.state.images)
                write_image(target / f"{slot}_1280x720.png", after)
                write_image(target / f"{slot}_340.png", downscale(after, 340))
                write_image(target / f"{slot}_180.png", downscale(after, 180))
                write_image(target / f"{slot}_before_v051.png", candidate.image)
                document = editor.state.documents[slot]
                title = document.by_role("main_title")
                after_report = readability_report(title.to_dict(), analyze_text_region(
                    editor.renderer.render(document, editor.state.images, skip_ids={title.id}), ink_box(title),
                    document.subject_boxes))
                before_report = _legacy_readability(editor.state, candidate, legacy_bases.get(candidate.code, candidate.image),
                                                    document.subject_boxes)
                slot_results[slot] = {"before_v051": before_report, "after_v06": after_report,
                                      "untouched_default": readability_report(
                                          title.to_dict(), analyze_text_region(before_frames[slot], ink_box(title),
                                                                               document.subject_boxes))["level"]}
                small = downscale(after, 340)
                tiny = downscale(after, 180)
                strip = np.full((360, 340 + 180 + 12, 3), 30, np.uint8)
                strip[0:small.shape[0], 0:340] = small
                strip[0:tiny.shape[0], 352:532] = tiny
                rows.append(np.hstack([_label(cv2.resize(candidate.image, (640, 360), interpolation=cv2.INTER_AREA),
                                              f"{slot} BEFORE v0.5.1 ({before_report['level']})"),
                                       _label(cv2.resize(after, (640, 360), interpolation=cv2.INTER_AREA),
                                              f"{slot} AFTER v0.6 editor ({after_report['level']})"),
                                       _label(strip, "340px / 180px")]))
            write_image(target / "before_after.png", np.vstack(rows))
            summary[name] = {"channel": editor.state.channel, "style": editor.state.style, "font": family or "(auto)",
                             "readability": slot_results, "latency": latency}
            print(name, json.dumps({slot: (r["before_v051"]["level"], r["after_v06"]["level"]) for slot, r in slot_results.items()}),
                  latency)
    finally:
        app.destroy()
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    run()
