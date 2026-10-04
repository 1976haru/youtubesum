"""End-to-end self-tests of the unified app, run inside the real EXE (used for packaged acceptance).

    YouTubeDynamicThumbnailStudio.exe --studio-e2e <youtube_woman|youtube_couple|old_pop|shopify_luma> --out <dir>
    YouTubeDynamicThumbnailStudio.exe --studio-queue-phase <a|b|c> --out <dir>

They press the same buttons/handlers as a user (Home card → 만들기 steps → 생성하기 → 이 후보로 편집 → title edit →
save → export → reopen). The backend is found the normal way (bundled engine / saved setting), never via env vars.
"""
from __future__ import annotations

import json
import time
import traceback
from pathlib import Path

import cv2
import numpy as np

PRODUCT = r"D:\03_image\image_thumbnail_bridge\validation_results\v1_products\bottle.png"
SCENARIOS = {
    "youtube_woman": {"family": "youtube", "kind": "tokyo_chill", "title": "雨の夜、君を思う", "subtitle": "A quiet story in Tokyo"},
    "youtube_couple": {"family": "youtube", "kind": "tokyo_chill", "title": "ふたりの帰り道",
                       "prompt": "a young Japanese man and woman couple sharing an umbrella on a rainy Shibuya street at night"},
    "old_pop": {"family": "youtube", "kind": "old_pop", "title": "첫눈에 다시 만난 날"},
    "shopify_luma": {"family": "shopify", "kind": "shopify_product_lifestyle", "title": "LUMA Serum",
                     "subtitle": "Daily glow in one drop", "cta": "지금 구매", "reference": PRODUCT},
}


def _pump(app, seconds: float = 0.0) -> None:
    end = time.perf_counter() + seconds
    while True:
        app.update()
        if time.perf_counter() >= end:
            break
        time.sleep(0.02)


def run_e2e(app, scenario: str, out: Path, timeout: float = 900) -> dict:
    spec = SCENARIOS[scenario]
    studio, editor = app.studio, app.pro_editor
    results: dict[str, str] = {}
    details: dict[str, object] = {}

    def check(name, ok, info=None):
        results[name] = "PASS" if ok else "FAIL"
        if info is not None:
            details[name] = info

    started = time.perf_counter()
    try:
        _pump(app, 1.0)
        studio.settings["output_dir"] = str(out / "outputs")      # keep test images out of the user's Documents
        from .backend import find_backend
        details["backend"] = dict(zip(("path", "source"), find_backend()))
        check("backend_found_without_env", details["backend"]["source"] in ("bundled", "saved", "covermorph"))
        # Home card → Create
        studio.start_create(spec["family"])
        _pump(app, 0.2)
        check("create_opened_from_home", studio.current == "create" and studio.create.step == 0)
        create = studio.create
        create.choose(spec["kind"])
        _pump(app, 0.2)
        if spec.get("prompt"):
            create.prompt_box.delete("1.0", "end")
            create.prompt_box.insert("1.0", spec["prompt"])
        create.title_var.set(spec.get("title", ""))
        create.subtitle_var.set(spec.get("subtitle", ""))
        create.cta_var.set(spec.get("cta", ""))
        if spec.get("reference"):
            create._add_paths([spec["reference"]])
            check("reference_role_product", create.references and create.references[0]["role"] == "PRODUCT")
            check("product_default_natural", create.product_var.get().startswith("자연광"))
        create.next()                       # → STEP 3
        _pump(app, 0.2)
        create.quality_var.set("일반")
        create.memory_var.set("작업 중 PC 우선")
        create.count_var.set("2")
        create.next()                       # 생성하기 → queue → STEP 4
        job = create.job
        check("job_queued", job is not None and create.step == 3)
        deadline = time.perf_counter() + timeout
        while job.state not in ("done", "failed", "cancelled") and time.perf_counter() < deadline:
            _pump(app, 0.5)
        _pump(app, 1.0)
        details["job"] = {"state": job.state, "seconds": round((job.finished or time.time()) - (job.started or time.time()), 1),
                          "error": job.error, "warnings": (job.result or {}).get("warnings"),
                          "candidates": [{k: c.get(k) for k in ("kind", "engine", "seed", "seconds", "warnings")}
                                         for c in (job.result or {}).get("candidates", [])],
                          "job_dir": (job.result or {}).get("job_dir")}
        check("candidates_generated", job.state == "done" and len(job.result["candidates"]) >= 2)
        if spec["family"] == "shopify":
            kinds = [c.get("kind") for c in job.result["candidates"]]
            check("natural_light_composite_used", all(k == "natural" for k in kinds), kinds)
            check("product_crop_present", all(Path(c["files"].get("product") or "").is_file() for c in job.result["candidates"]))
        else:
            check("previews_340_180", all(Path(c["files"].get("preview_340", "")).is_file() and
                                          Path(c["files"].get("preview_180", "")).is_file() for c in job.result["candidates"]))
        # choose → editor (no manual export/import)
        ok = studio.open_candidate_in_editor(job, 0)
        _pump(app, 1.0)
        check("candidate_opened_in_editor", ok and studio.current == "editor" and bool(editor.state.documents))
        document = editor.document
        expected = tuple(job.payload["canvas"])
        check("editor_canvas_size", (document.canvas_width, document.canvas_height) == expected,
              [document.canvas_width, document.canvas_height])
        roles = sorted({layer.role for layer in document.ordered()})
        details["layers"] = roles
        if spec["family"] == "shopify":
            check("shopify_layers_no_youtube_badges", "main_title" in roles and "cta" in roles and
                  not {"episode_badge", "channel_label", "story_label"} & set(roles), roles)
        else:
            check("youtube_layers", {"main_title", "episode_badge", "channel_label"} <= set(roles), roles)
            report = getattr(studio, "last_collisions", {})
            details["collisions_before_after"] = report
            details["editor_message"] = editor.message.get()
            remaining = sum(after for _before, after in report.values())
            found = sum(before for before, _after in report.values())
            # handled = nothing overlaps after auto-move, or the user is told exactly what is left
            check("face_text_collision_handled", remaining == 0 or "남은 겹침" in editor.message.get(),
                  {"found": found, "remaining": remaining})
        # edit the title like a user
        title = document.by_role("main_title")
        new_title = (spec.get("title") or "제목") + " ✓"
        editor.set_property("text", new_title, title)
        _pump(app, 0.3)
        project = out / f"{scenario}_project" / "thumbnail_project.json"
        project.parent.mkdir(parents=True, exist_ok=True)
        editor._flush_edit()
        saved = {slot: doc.to_dict() for slot, doc in editor.state.documents.items()}
        editor._save_to(project)
        exported = editor.export_all(str(out / f"{scenario}_export"))
        sizes = []
        for path in exported:
            image = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)
            sizes.append(None if image is None else [int(image.shape[1]), int(image.shape[0])])
        check("export_native_size", len(exported) == 3 and all(s == list(expected) for s in sizes),
              {"files": [str(p) for p in exported], "sizes": sizes})
        # reopen from Home ("기존 프로젝트 열기" path)
        editor.open_project_file(str(project))
        _pump(app, 0.5)
        reopened = {slot: doc.to_dict() for slot, doc in editor.state.documents.items()}
        check("project_reopen", reopened == saved and editor.document.by_role("main_title").text == new_title)
    except Exception:
        results["exception"] = "FAIL"
        details["traceback"] = traceback.format_exc()
    details["seconds"] = round(time.perf_counter() - started, 1)
    return {"scenario": scenario, "results": results, "details": details,
            "passed": bool(results) and all(v == "PASS" for v in results.values())}


QUEUE_JOBS = [
    ("youtube", "tokyo_chill", {}),
    ("shopify", "shopify_hero", {"title": "New Season"}),
    ("shopify", "shopify_product_lifestyle", {"reference": PRODUCT}),
    ("youtube", "old_pop", {}),
    ("shopify", "shopify_mobile", {"title": "겨울 컬렉션"}),
]


def queue_phase(app, phase: str, out: Path, timeout: float = 1800) -> dict:
    """a: add 5 mixed jobs, start, 현재 작업 후 일시정지 during job 1, wait, close.
    b: reopen, check states, 재개, close while job 2+ runs.  c: reopen, 재개, run to the end, close."""
    studio = app.studio
    report = {"phase": phase, "start": [j.state for j in studio.queue.jobs], "paused_at_start": studio.queue.paused}
    started = time.perf_counter()
    studio.settings["output_dir"] = str(out / "outputs")
    _pump(app, 1.0)
    if phase == "a":
        for family, kind, extra in QUEUE_JOBS:
            studio.start_create(family)
            create = studio.create
            create.choose(kind)
            _pump(app, 0.1)
            if extra.get("reference"):
                create._add_paths([extra["reference"]])
            create.title_var.set(extra.get("title", ""))
            create._capture_prompt()
            create.quality_var.set("빠른 미리보기")
            create.count_var.set("1")
            create.step = 2
            create.generate(start=False)
        studio.runner.start()
        while studio.runner.current is None and time.perf_counter() - started < 60:
            _pump(app, 0.2)
        studio.runner.pause_after_current()
        while (studio.runner.current is not None) and time.perf_counter() - started < timeout:
            _pump(app, 0.5)
    elif phase == "b":
        studio.runner.start()
        while time.perf_counter() - started < timeout:
            current = studio.runner.current
            done = sum(1 for j in studio.queue.jobs if j.state == "done")
            if current is not None and done >= 2 and current.progress >= 0.1:
                report["closed_during"] = current.id
                break
            _pump(app, 0.5)
    else:
        studio.runner.start()
        while any(j.state in ("pending", "running") for j in studio.queue.jobs) and time.perf_counter() - started < timeout:
            _pump(app, 0.5)
    report["end"] = [j.state for j in studio.queue.jobs]
    report["end_paused"] = studio.queue.paused
    report["seconds"] = round(time.perf_counter() - started, 1)
    return report


def main_e2e(app, argv: list[str]) -> int:
    def arg(flag):
        return argv[argv.index(flag) + 1] if flag in argv and argv.index(flag) + 1 < len(argv) else None
    out = Path(arg("--out") or "studio_selftest")
    out.mkdir(parents=True, exist_ok=True)
    if argv[0] == "--studio-e2e":
        report = run_e2e(app, argv[1], out)
        name = f"e2e_{argv[1]}.json"
        code = 0 if report["passed"] else 1
    else:
        report = queue_phase(app, argv[1], out)
        name = f"queue_phase_{argv[1]}.json"
        code = 0
    (out / name).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    app.on_close_quiet()
    return code
