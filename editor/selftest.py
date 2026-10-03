"""End-to-end GUI self-test for the Pro Editor (used by tests and the packaged EXE smoke test).

Drives the real Tk canvas with synthesized mouse events, so selection, drag, resize,
rotate, undo/redo, live typography, font browser, background fit, A/B/C switching,
save/reopen, export and the bridge background swap are all exercised end to end.
"""
from __future__ import annotations

import json
import tempfile
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

from . import geometry as geo
from .document import TextLayer


def _pump(app, seconds: float = 0.0) -> None:
    end = time.perf_counter() + seconds
    while True:
        app.update()
        if time.perf_counter() >= end:
            break
        time.sleep(0.01)


_CLOCK = [int(time.monotonic() * 1000)]


def _stamp() -> int:
    """Increasing event timestamps; without them Tk sees repeated synthetic presses as double-clicks."""
    _CLOCK[0] += 1000
    return _CLOCK[0]


def _canvas_point(editor, x: float, y: float) -> tuple[int, int]:
    vx, vy = editor.view.to_view(x, y)
    return round(vx - editor.canvas.canvasx(0)), round(vy - editor.canvas.canvasy(0))


def _drag(app, editor, start_doc, end_doc, steps: int = 6, state: int = 0) -> None:
    canvas = editor.canvas
    sx, sy = _canvas_point(editor, *start_doc)
    ex, ey = _canvas_point(editor, *end_doc)
    canvas.event_generate("<ButtonPress-1>", x=sx, y=sy, state=state, time=_stamp())
    _pump(app)
    for step in range(1, steps + 1):
        canvas.event_generate("<B1-Motion>", x=round(sx + (ex - sx) * step / steps),
                              y=round(sy + (ey - sy) * step / steps), state=state | 0x100, time=_stamp())
        _pump(app)
    canvas.event_generate("<ButtonRelease-1>", x=ex, y=ey, state=state | 0x100, time=_stamp())
    _pump(app)


def run_editor_self_test(app, project_folder: str | Path, *, capture: str | Path | None = None,
                         workdir: str | Path | None = None, fonts_timeout: float = 45.0,
                         bridge_generate: bool = False) -> dict:
    editor = app.pro_editor
    app.notebook.select(editor)
    app.deiconify()
    app.geometry("1600x1000+20+20")
    _pump(app, 0.3)
    results: dict[str, str] = {}
    details: dict[str, object] = {}

    def check(name: str, condition: bool, info=None) -> None:
        results[name] = "PASS" if condition else "FAIL"
        if info is not None:
            details[name] = info

    temp = tempfile.TemporaryDirectory() if workdir is None else None
    root = Path(workdir or temp.name) / "저장 테스트 東京 space"
    root.mkdir(parents=True, exist_ok=True)
    try:
        editor.open_project_folder(str(project_folder), synchronous=True)
        _pump(app, 0.2)
        editor.zoom_choice.set("Fit"); editor._apply_zoom(); _pump(app, 0.1)
        state = editor.state
        check("project_load_abc", set(state.documents) == {"A", "B", "C"} and editor.frame_bgr is not None,
              {"channel": state.channel, "style": state.style})
        # Destructive manipulation checks run on candidate C; A is kept for a realistic capture.
        editor.select_slot("C"); _pump(app)
        document = editor.document
        title = document.by_role("main_title")
        editor.select_layer(None); _pump(app)

        # Direct selection + drag through real canvas events.
        cx, cy = title.center
        before = (title.x, title.y)
        _drag(app, editor, (cx, cy), (cx + 60, cy - 40))
        title = editor.document.by_role("main_title")
        selected = editor.selected_layer()
        moved = (round(title.x - before[0]), round(title.y - before[1]))
        check("canvas_select", selected is not None and selected.id == title.id)
        check("canvas_drag", abs(moved[0] - 60) <= 8 and abs(moved[1] + 40) <= 8, {"moved": moved})
        editor.undo(); _pump(app)
        title = editor.document.by_role("main_title")
        undone = (round(title.x), round(title.y)) == (round(before[0]), round(before[1]))
        editor.redo(); _pump(app)
        title = editor.document.by_role("main_title")
        check("undo_redo", undone and abs(title.x - before[0] - moved[0]) < 1)

        # Corner resize scales the type proportionally.
        editor.select_layer(title.id); _pump(app)
        font_before = title.font_size
        se = geo.corners(title)[2]
        _drag(app, editor, se, (se[0] + 80, se[1] + 30))
        title = editor.document.by_role("main_title")
        check("canvas_resize", title.font_size > font_before * 1.04, {"font_size": [font_before, title.font_size]})

        # Rotation handle.
        handles = geo.handle_points(title, editor.view)
        rot_doc = editor.view.to_doc(*handles["rot"])
        _drag(app, editor, rot_doc, (rot_doc[0] + 90, rot_doc[1] + 10))
        title = editor.document.by_role("main_title")
        check("canvas_rotate", abs(title.rotation) > 5, {"rotation": round(title.rotation, 1)})

        # Keyboard nudges.
        editor.canvas.focus_force(); _pump(app)
        x0 = title.x
        editor.canvas.event_generate("<KeyPress>", keysym="Right"); _pump(app)
        editor.canvas.event_generate("<KeyPress>", keysym="Right", state=0x0001); _pump(app)
        title = editor.document.by_role("main_title")
        check("keyboard_nudge", round(title.x - x0) == 11, {"dx": round(title.x - x0, 1)})

        # Live typography edits through the inspector fields.
        frame = editor.frame_bgr.copy()
        timings = []
        for attr, value in (("font_size", title.font_size + 6), ("outline_width", 14.0), ("shadow_opacity", 0.9),
                            ("glow_opacity", 0.7), ("glow_blur", 18.0), ("letter_spacing", 3.0),
                            ("secondary_outline_width", 5.0), ("fill", "#FFE9F5"), ("line_spacing", 1.25)):
            field = editor._fields.get(attr)
            start = time.perf_counter()
            if field is not None and hasattr(field, "scale"):
                field.var.set(value); field._from_scale()
            elif field is not None and hasattr(field, "swatch"):
                field.var.set(value)
            else:
                editor.set_property(attr, value)
            while editor._render_job is not None:  # until the coalesced frame is on screen
                app.update()
            timings.append((time.perf_counter() - start) * 1000)
            _pump(app)
        title = editor.document.by_role("main_title")
        changed = float(cv2.absdiff(frame, editor.frame_bgr).mean())
        check("live_typography", changed > 0.3 and title.outline_width == 14.0 and title.glow_opacity == 0.7,
              {"mean_pixel_change": round(changed, 2)})
        ordered = sorted(timings)
        details["live_property_ms"] = {"median": round(ordered[len(ordered) // 2], 1), "max": round(ordered[-1], 1)}

        # Font browser (async scan) with live preview of the actual title.
        deadline = time.perf_counter() + fonts_timeout
        while not editor.font_browser.catalog and time.perf_counter() < deadline:
            _pump(app, 0.1)
        browser = editor.font_browser
        browser.script.set("Japanese"); browser.refresh(); _pump(app, 0.3)
        picked = browser.families[0].name if browser.families else ""
        if picked:
            browser.pick_index(0); _pump(app, 0.2)
        title = editor.document.by_role("main_title")
        check("font_browser", bool(picked) and title.font_family == picked and len(browser._photos) > 0,
              {"families": len(browser.families), "picked": picked})

        # Background fit + readability meter.
        report = editor.apply_background_fit("fit"); _pump(app)
        check("background_fit", report is not None and report["level"] in ("GOOD", "WARNING", "POOR"),
              report and {k: report[k] for k in ("level", "contrast", "px340", "px180")})
        check("preview_340_180", bool(editor.preview_340.cget("image")) and bool(editor.preview_180.cget("image")))

        # Realistic workflow on candidate A: pick a proper display font, then 배경에 맞춤.
        editor.select_slot("A"); _pump(app)
        a_layer = editor.document.by_role("main_title")
        editor.select_layer(a_layer.id); _pump(app)
        names = {family.name for family in browser.catalog}
        hangul = any("가" <= char <= "힣" for char in a_layer.text)
        choices = ("Malgun Gothic", "Noto Sans KR") if hangul else ("Yu Gothic", "Meiryo", "BIZ UDPGothic")
        family = next((name for name in choices if name in names), "")
        if family:
            editor.apply_font(family); _pump(app)
        editor.apply_background_fit("fit"); _pump(app, 0.3)
        editor.update_meter(); _pump(app)
        details["capture_state"] = {"font": family, "report": getattr(editor, "last_report", None)}
        if capture:
            capture_window(app, capture)
            details["capture"] = str(capture)

        # Candidate independence.
        a_title = editor.document.by_role("main_title").to_dict()
        editor.select_slot("B"); _pump(app)
        b_title = editor.document.by_role("main_title")
        editor.set_property("font_size", b_title.font_size - 10, b_title); _pump(app)
        editor.select_slot("A"); _pump(app)
        check("abc_independent", editor.document.by_role("main_title").to_dict() == a_title)

        # Save / reopen on a Korean/Japanese/space path.
        editor._flush_edit()
        project_path = root / "thumbnail_project.json"
        saved_docs = {slot: doc.to_dict() for slot, doc in editor.state.documents.items()}
        editor._save_to(project_path)
        editor.open_project_file(str(project_path)); _pump(app)
        reopened = {slot: doc.to_dict() for slot, doc in editor.state.documents.items()}
        check("project_save_reopen", reopened == saved_docs, {"path": str(project_path)})
        exported = editor.export_all(str(root / "내보내기"))
        decoded = cv2.imdecode(np.fromfile(str(exported[0]), np.uint8), cv2.IMREAD_COLOR) if exported else None
        same = decoded is not None and np.array_equal(
            decoded, editor.renderer.render(editor.state.documents["A"], editor.state.images))
        check("export_same_renderer", len(exported) == 3 and same)

        # Bridge refresh (no external program) swaps backgrounds only.
        texts_before = {slot: [layer.to_dict() for layer in doc.ordered() if layer.type != "background"]
                        for slot, doc in editor.state.documents.items()}
        editor.bridge_refresh(choice="keep"); _pump(app)
        texts_after = {slot: [layer.to_dict() for layer in doc.ordered() if layer.type != "background"]
                       for slot, doc in editor.state.documents.items()}
        check("bridge_refresh_preserves_layers", texts_before == texts_after)
        if bridge_generate:
            # Real subprocess through the Image Bridge launcher (IMAGE_PROGRAM_EXE must be configured).
            editor._ask_relayout = lambda _collisions: "keep"
            before_bg = editor.state.background_image("A").copy()
            layers_before = {slot: [layer.to_dict() for layer in doc.ordered() if layer.type != "background"]
                             for slot, doc in editor.state.documents.items()}
            editor.image_prompt.set("rainy Tokyo station at night, 東京")
            editor.bridge_generate()
            deadline = time.perf_counter() + 180
            while (editor._bridge_running or not editor._bridge_queue.empty()) and time.perf_counter() < deadline:
                _pump(app, 0.1)
            _pump(app, 0.3)
            layers_after = {slot: [layer.to_dict() for layer in doc.ordered() if layer.type != "background"]
                            for slot, doc in editor.state.documents.items()}
            changed_bg = not np.array_equal(before_bg, editor.state.background_image("A"))
            check("bridge_generate_subprocess", changed_bg and layers_before == layers_after,
                  {"status": editor.bridge_status.get()[:160], "message": editor.message.get()[:160]})
        details["timings"] = editor.timing_summary()
    except Exception:
        results["exception"] = "FAIL"
        details["traceback"] = traceback.format_exc()
    finally:
        if temp is not None:
            temp.cleanup()
    return {"results": results, "details": details, "passed": all(v == "PASS" for v in results.values())}


def capture_window(app, path: str | Path) -> Path:
    """Screenshot the real application window (actual pixels on screen)."""
    from PIL import ImageGrab
    app.lift(); app.attributes("-topmost", True); _pump(app, 0.4)
    x, y = app.winfo_rootx(), app.winfo_rooty()
    w, h = app.winfo_width(), app.winfo_height()
    image = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    app.attributes("-topmost", False)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def main_self_test(app, folder: str, capture: str | None, report: str | None, bridge_generate: bool = False) -> int:
    if bridge_generate:
        # The bridge writes into the project folder; work on a copy so the source stays untouched.
        import shutil
        scratch = Path(tempfile.mkdtemp(prefix="ydts_bridge_"))
        copy = scratch / "브리지 프로젝트 東京"
        shutil.copytree(folder, copy)
        folder = str(copy)
    outcome = run_editor_self_test(app, folder, capture=capture, bridge_generate=bridge_generate)
    text = json.dumps(outcome, ensure_ascii=False, indent=2)
    if report:
        Path(report).write_text(text, encoding="utf-8")
    return 0 if outcome["passed"] else 1


__all__ = ["run_editor_self_test", "capture_window", "main_self_test", "TextLayer"]
