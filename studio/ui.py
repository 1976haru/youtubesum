"""The single user-facing app shell: 홈 · 만들기 · 편집기 · 대기열 · 기록 · 설정 · 도구.

Normal screens never show model names, bridge/sidecar words or environment variables; those live under
설정 → 고급 설정 and 도구 (legacy conversion tools).
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from PIL import Image, ImageTk

from . import settings as cfg
from .backend import Backend, find_backend
from .jobs import CANCELLED, DONE, FAILED, PENDING, RUNNING, STATE_LABELS, Job, JobQueue, Runner
from .presets import KIND_BY_KEY, KINDS, ROLES

ACCENT = "#2563eb"
MUTED = "#64748b"
QA_KO = [
    ("expected", "얼굴 수가 기대보다 적습니다"),
    ("faces found for a", "추가 인물이 보일 수 있습니다"),
    ("face smaller than", "얼굴이 작습니다"),
    ("face taller than", "얼굴이 커서 글자 공간이 좁습니다"),
    ("main face is soft", "얼굴 디테일이 약할 수 있습니다(얕은 심도)"),
    ("gross exposure", "밝기가 지나치게 어둡거나 밝습니다"),
]


def friendly_warning(text: str) -> str:
    for key, label in QA_KO:
        if text.startswith(key) or key in text:
            return label
    return text


def open_path(path: str | Path) -> None:
    try:
        os.startfile(str(path))  # noqa: S606 - user-requested open
    except OSError:
        pass


def thumb(path: str | Path, box: tuple[int, int]) -> ImageTk.PhotoImage | None:
    try:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        image.thumbnail(box, Image.Resampling.LANCZOS)
        return ImageTk.PhotoImage(image)
    except OSError:
        return None


def setup_styles(root: tk.Misc) -> None:
    style = ttk.Style(root)
    style.configure("Title.TLabel", font=("Malgun Gothic", 20, "bold"))
    style.configure("H2.TLabel", font=("Malgun Gothic", 14, "bold"))
    style.configure("Muted.TLabel", foreground=MUTED, font=("Malgun Gothic", 10))
    style.configure("Card.TButton", font=("Malgun Gothic", 15, "bold"), padding=(24, 26))
    style.configure("Choice.TButton", font=("Malgun Gothic", 12), padding=(14, 12))
    style.configure("Primary.TButton", font=("Malgun Gothic", 12, "bold"), padding=(18, 10))
    style.configure("Nav.TButton", font=("Malgun Gothic", 11), padding=(10, 9), anchor="w")
    style.configure("NavOn.TButton", font=("Malgun Gothic", 11, "bold"), padding=(10, 9), anchor="w")
    style.configure("Step.TLabel", font=("Malgun Gothic", 11), foreground=MUTED, padding=(8, 4))
    style.configure("StepOn.TLabel", font=("Malgun Gothic", 11, "bold"), foreground=ACCENT, padding=(8, 4))
    style.configure("Studio.Treeview", rowheight=28, font=("Malgun Gothic", 10))
    style.configure("Studio.Treeview.Heading", font=("Malgun Gothic", 10, "bold"))


class Studio:
    """Owns settings, backend, queue/runner and the pages. Built inside ``App`` before the legacy tabs."""

    PAGES = (("home", "홈"), ("create", "만들기"), ("editor", "편집기"), ("queue", "대기열"), ("history", "기록"),
             ("settings", "설정"), ("tools", "도구 · 고급 기능"))

    def __init__(self, app: tk.Tk):
        self.app = app
        setup_styles(app)
        self.settings = cfg.load()
        self.backend = Backend()
        self.engine_status: dict[str, Any] = {"connected": self.backend.available, "ready": False,
                                              "message": "확인 중…"}
        self.queue = JobQueue()
        self.runner = Runner(self.queue, self._execute, self._mark_dirty, float(self.settings["recheck_seconds"]))
        self.runner.cancel_current = self.backend.cancel
        self._dirty = True
        self._photos: list[Any] = []
        body = ttk.Frame(app)
        body.pack(fill="both", expand=True)
        self.nav = ttk.Frame(body, padding=(10, 12))
        self.nav.pack(side="left", fill="y")
        ttk.Separator(body, orient="vertical").pack(side="left", fill="y")
        self.content = ttk.Frame(body)
        self.content.pack(side="left", fill="both", expand=True)
        ttk.Label(self.nav, text="Thumbnail\nStudio", style="H2.TLabel").pack(anchor="w", pady=(0, 14))
        self.nav_buttons: dict[str, ttk.Button] = {}
        for key, label in self.PAGES:
            button = ttk.Button(self.nav, text=label, style="Nav.TButton", width=16, command=lambda k=key: self.show(k))
            button.pack(fill="x", pady=2)
            self.nav_buttons[key] = button
        self.engine_label = ttk.Label(self.nav, text="", style="Muted.TLabel", wraplength=170, justify="left")
        self.engine_label.pack(side="bottom", anchor="w", pady=8)
        self.pages: dict[str, ttk.Frame] = {key: ttk.Frame(self.content) for key, _ in self.PAGES}
        self.current = ""
        self._build_home(self.pages["home"])
        self.create = CreatePage(self, self.pages["create"])
        self._build_queue(self.pages["queue"])
        self._build_history(self.pages["history"])
        self.settings_page = SettingsPage(self, self.pages["settings"])
        tools = self.pages["tools"]
        ttk.Label(tools, text="도구 · 고급 기능", style="H2.TLabel").pack(anchor="w", padx=16, pady=(12, 0))
        ttk.Label(tools, text="기존 3후보 변환, Live Composer, Motion Intro 등 고급 사용자를 위한 기능입니다.",
                  style="Muted.TLabel").pack(anchor="w", padx=16, pady=(0, 6))
        self.tools_container = ttk.Frame(tools)
        self.tools_container.pack(fill="both", expand=True)
        self.editor_container = self.pages["editor"]
        app.after(500, self._poll)
        # The status check starts the engine process once; delayed so short-lived windows never trigger it.
        app.after(1500, lambda: threading.Thread(target=self.refresh_engine_status, daemon=True).start())
        note = self.queue.recovered_note
        if note:
            app.after(1200, lambda: messagebox.showwarning("대기열", note))
        if self.settings.get("auto_start") and self.queue.pending() and not self.queue.paused:
            self.runner.start()

    # ------------------------------------------------------------------ navigation
    def show(self, key: str) -> None:
        if key == "editor" and getattr(self.app, "pro_editor", None) is not None:
            self.app.pro_editor.after(50, lambda: self.app.pro_editor._apply_zoom())
        for name, frame in self.pages.items():
            if name == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        for name, button in self.nav_buttons.items():
            button.configure(style="NavOn.TButton" if name == key else "Nav.TButton")
        self.current = key
        if key in ("queue", "history", "home"):
            self._dirty = True

    # ------------------------------------------------------------------ home
    def _build_home(self, page: ttk.Frame) -> None:
        wrap = ttk.Frame(page, padding=(40, 30))
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="무엇을 할까요?", style="Title.TLabel").pack(anchor="w")
        ttk.Label(wrap, text="YouTube 썸네일이나 Shopify 이미지를 만들고, 글자를 편집해 내보낼 수 있습니다.",
                  style="Muted.TLabel").pack(anchor="w", pady=(4, 24))
        grid = ttk.Frame(wrap)
        grid.pack(anchor="w")
        cards = (("YouTube 썸네일 만들기\n장면 설명 → 후보 → 글자 편집", lambda: self.start_create("youtube")),
                 ("Shopify 이미지 만들기\n배너 · 상품 사진 · 프로모션", lambda: self.start_create("shopify")),
                 ("기존 프로젝트 열기\n저장한 썸네일 계속 편집", self.open_existing),
                 ("작업 대기열\n진행 중 · 대기 · 완료", lambda: self.show("queue")),
                 ("설정\nAI 엔진 · 저장 폴더 · 기본값", lambda: self.show("settings")))
        for index, (text, command) in enumerate(cards):
            ttk.Button(grid, text=text, style="Card.TButton", width=26, command=command).grid(
                row=index // 3, column=index % 3, padx=10, pady=10, sticky="nsew")
        self.home_status = ttk.Label(wrap, text="", style="Muted.TLabel", justify="left")
        self.home_status.pack(anchor="w", pady=(24, 0))

    def start_create(self, family: str) -> None:
        self.create.reset(family)
        self.show("create")

    def open_existing(self) -> None:
        editor = getattr(self.app, "pro_editor", None)
        if editor is None:
            return
        path = filedialog.askopenfilename(title="프로젝트 열기", filetypes=[("Thumbnail project", "*.json")],
                                          initialdir=self.settings.get("last_project_dir") or None)
        if not path:
            return
        editor.open_project_file(path)
        self.settings["last_project_dir"] = str(Path(path).parent)
        cfg.save(self.settings)
        self.show("editor")

    # ------------------------------------------------------------------ engine status
    def refresh_engine_status(self) -> None:
        self.backend = Backend()
        self.runner.cancel_current = self.backend.cancel
        status = self.backend.status(self.settings.get("models_dir") or "")
        self.engine_status = status
        self._dirty = True

    def engine_summary(self) -> str:
        status = self.engine_status
        if not status.get("connected"):
            return "AI 엔진: 연결 필요"
        if not status.get("ready"):
            return "AI 엔진: " + (status.get("message") or "모델 폴더 확인 필요")
        gpu = str(status.get("gpu") or "").split(",")[0]
        return f"AI 엔진: 준비됨\nGPU: {gpu}"

    # ------------------------------------------------------------------ queue execution
    def _execute(self, job: Job):
        payload = dict(job.payload)
        payload.update(models_dir=self.settings.get("models_dir") or "", output_root=str(cfg.output_dir(self.settings) / "jobs"),
                       job_id=job.id)

        def progress(event: dict[str, Any]) -> None:
            if "progress" in event:
                job.progress = float(event["progress"])
            if event.get("message"):
                job.message = event["message"]
            elif event.get("steps"):
                job.message = f"{job.message.split(' · ')[0]} · {event['step']}/{event['steps']}"
            self._dirty = True

        work = cfg.data_dir() / "work" / job.id
        return self.backend.run_job(payload, work, progress, timeout=float(self.settings.get("timeout_seconds") or 1200))

    def enqueue(self, payload: dict[str, Any], start: bool = True) -> Job:
        job = self.queue.add(payload)
        if start or self.settings.get("auto_start"):
            self.runner.start()
        self._dirty = True
        return job

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _poll(self) -> None:
        if self._dirty:
            self._dirty = False
            try:
                self._refresh_queue()
                self._refresh_history()
                self.create.refresh_job()
                summary = self.engine_summary()
                self.engine_label.configure(text=summary)
                done = [j for j in self.queue.jobs if j.state == DONE]
                last = max(done, key=lambda j: j.finished or 0) if done else None
                self.home_status.configure(text=summary.replace("\n", " · ") + (
                    f"\n최근 결과: {self._job_title(last)} ({time.strftime('%m-%d %H:%M', time.localtime(last.finished))})"
                    if last else "") + f"\n대기열: {self.runner.status}")
            except tk.TclError:
                return
        self.app.after(500, self._poll)

    # ------------------------------------------------------------------ queue page
    def _build_queue(self, page: ttk.Frame) -> None:
        top = ttk.Frame(page, padding=(16, 12))
        top.pack(fill="x")
        ttk.Label(top, text="작업 대기열", style="H2.TLabel").pack(side="left")
        self.queue_status = ttk.Label(top, text="", style="Muted.TLabel")
        self.queue_status.pack(side="left", padx=16)
        bar = ttk.Frame(page, padding=(16, 0))
        bar.pack(fill="x")
        for text, command in (("시작", self.runner.start), ("현재 작업 후 일시정지", self.runner.pause_after_current),
                              ("재개", self.runner.start), ("선택 취소", self._cancel_selected),
                              ("실패 재시도", self._retry_selected), ("완료 결과 열기", self._open_selected),
                              ("목록에서 지우기", self._remove_selected)):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=3, pady=6)
        columns = ("status", "purpose", "prompt", "quality", "progress", "output", "warning")
        headings = ("상태", "목적", "프롬프트/제목", "품질", "진행률", "출력", "경고")
        widths = (80, 150, 330, 90, 210, 300, 260)
        frame = ttk.Frame(page, padding=(16, 4))
        frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", style="Studio.Treeview", selectmode="extended")
        for column, heading, width in zip(columns, headings, widths):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width, anchor="w", stretch=column in ("prompt", "output"))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self._open_selected())

    @staticmethod
    def _job_title(job: Job | None) -> str:
        if job is None:
            return ""
        payload = job.payload
        return (payload.get("title") or payload.get("prompt") or "")[:60]

    def _purpose_label(self, job: Job) -> str:
        kind = KIND_BY_KEY.get(job.payload.get("studio_kind", ""))
        family = "YouTube" if kind and kind.family == "youtube" else "Shopify"
        return f"{family} · {kind.label}" if kind else job.payload.get("purpose", "")

    def _refresh_queue(self) -> None:
        if not hasattr(self, "tree"):
            return
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for job in self.queue.jobs:
            if job.state == RUNNING:
                progress = f"{int(job.progress * 100)}% {job.message}"
            elif job.state == PENDING and job.waiting_reason:
                progress = "PC 사용 중 — 자원 대기"
            elif job.state == FAILED:
                progress = (job.error or {}).get("message", "실패")[:60]
            else:
                progress = "100%" if job.state == DONE else job.message
            output = (job.result or {}).get("job_dir", "")
            warnings = [friendly_warning(w) for w in (job.result or {}).get("warnings", [])]
            if job.state == FAILED:
                warnings = [(job.error or {}).get("action", "")]
            quality = cfg.label_for(cfg.QUALITY, job.payload.get("quality", "balanced"))
            self.tree.insert("", "end", iid=job.id, values=(STATE_LABELS.get(job.state, job.state), self._purpose_label(job),
                                                            self._job_title(job), quality, progress, output,
                                                            " / ".join(w for w in warnings if w)[:120]))
        for item in selected & set(self.tree.get_children()):
            self.tree.selection_add(item)
        paused = " · 일시정지 상태" if self.queue.paused else ""
        self.queue_status.configure(text=f"{self.runner.status}{paused}")

    def _selected(self) -> list[Job]:
        return [job for job in (self.queue.get(i) for i in self.tree.selection()) if job is not None]

    def _cancel_selected(self) -> None:
        for job in self._selected():
            if job.state == RUNNING:
                self.backend.cancel()
            else:
                self.queue.cancel(job.id)
        self._dirty = True

    def _retry_selected(self) -> None:
        for job in self._selected():
            self.queue.retry(job.id)
        self.runner.start()

    def _remove_selected(self) -> None:
        jobs = [j for j in self._selected() if j.state != RUNNING]
        if jobs and messagebox.askyesno("대기열", f"{len(jobs)}개 항목을 목록에서 지울까요? (만든 이미지는 지우지 않습니다)"):
            self.queue.remove([j.id for j in jobs])
            self._dirty = True

    def _open_selected(self) -> None:
        jobs = self._selected()
        if not jobs:
            return
        job = jobs[0]
        if job.state == DONE:
            self.create.show_results(job)
            self.show("create")
        elif job.state == FAILED:
            error = job.error or {}
            messagebox.showerror(error.get("title") or "작업 실패",
                                 f"{error.get('message', '')}\n\n해결 방법: {error.get('action', '')}")

    # ------------------------------------------------------------------ history page
    def _build_history(self, page: ttk.Frame) -> None:
        ttk.Label(page, text="기록 — 완료된 작업", style="H2.TLabel").pack(anchor="w", padx=16, pady=12)
        frame = ttk.Frame(page, padding=(16, 0))
        frame.pack(fill="both", expand=True)
        self.history = ttk.Treeview(frame, columns=("when", "purpose", "prompt", "count", "folder"), show="headings",
                                    style="Studio.Treeview")
        for column, heading, width in (("when", "완료", 120), ("purpose", "목적", 170), ("prompt", "프롬프트/제목", 380),
                                       ("count", "후보", 60), ("folder", "폴더", 380)):
            self.history.heading(column, text=heading)
            self.history.column(column, width=width, anchor="w", stretch=column in ("prompt", "folder"))
        self.history.pack(fill="both", expand=True)
        row = ttk.Frame(page, padding=16)
        row.pack(fill="x")
        ttk.Button(row, text="후보 보기", command=self._history_open).pack(side="left")
        ttk.Button(row, text="폴더 열기", command=self._history_folder).pack(side="left", padx=6)
        self.history.bind("<Double-1>", lambda _e: self._history_open())

    def _refresh_history(self) -> None:
        if not hasattr(self, "history"):
            return
        self.history.delete(*self.history.get_children())
        for job in sorted((j for j in self.queue.jobs if j.state == DONE), key=lambda j: j.finished or 0, reverse=True):
            self.history.insert("", "end", iid=job.id, values=(
                time.strftime("%m-%d %H:%M", time.localtime(job.finished or 0)), self._purpose_label(job),
                self._job_title(job), len((job.result or {}).get("candidates", [])), (job.result or {}).get("job_dir", "")))

    def _history_open(self) -> None:
        selection = self.history.selection()
        job = self.queue.get(selection[0]) if selection else None
        if job is not None:
            self.create.show_results(job)
            self.show("create")

    def _history_folder(self) -> None:
        selection = self.history.selection()
        job = self.queue.get(selection[0]) if selection else None
        if job is not None and job.result:
            open_path(job.result["job_dir"])

    # ------------------------------------------------------------------ editor hand-off
    def open_candidate_in_editor(self, job: Job, index: int, synchronous: bool = False) -> bool:
        editor = getattr(self.app, "pro_editor", None)
        candidate = job.result["candidates"][index]
        kind = KIND_BY_KEY.get(job.payload.get("studio_kind", ""), KINDS[0])
        folder = Path(job.result["job_dir"]) / f"편집_{index + 1:02d}"
        payload = job.payload
        meta = {"job_id": job.id, "purpose": payload.get("purpose"), "channel": payload.get("channel") or "",
                "title": payload.get("title", ""), "subtitle": payload.get("subtitle", ""),
                "episode": payload.get("episode", ""), "cta": payload.get("cta", ""), "prompt": payload.get("prompt", ""),
                "people": payload.get("people", 0), "seed": candidate.get("seed"), "engine": candidate.get("engine")}
        if not self.backend.make_editor_project(candidate["files"]["full"], folder, meta):
            messagebox.showerror("편집기", "선택한 이미지를 편집기로 보내지 못했습니다. '설정 → AI 엔진'을 확인하세요.")
            return False
        job.chosen = index
        self.queue.save()
        if kind.family == "youtube":
            editor.open_project_folder(str(folder), synchronous=True)
        else:
            from editor.project import generate_shop_project
            from image_bridge import load_image_project
            width, height = payload.get("canvas") or kind.size
            project = load_image_project(folder, canvas_size=(int(width), int(height)))
            state = generate_shop_project(str(folder / "canvas_clean.png"), (int(width), int(height)),
                                          {"title": payload.get("title") or "", "subtitle": payload.get("subtitle") or "",
                                           "cta": payload.get("cta") or ""},
                                          text_region=kind.text_region, cta_region=kind.cta_region,
                                          subject_boxes=list(project.subject_boxes), palette=project.palette,
                                          purpose=payload.get("purpose", ""))
            editor.set_state(state)
            editor.message.set("Shopify 이미지 · 헤드라인/서브헤드/버튼을 편집하세요")
        editor.state.project_path = folder / "thumbnail_project.json"
        self.last_collisions = self._resolve_collisions(editor)
        self.show("editor")
        return True

    @staticmethod
    def _resolve_collisions(editor) -> dict[str, list[int]]:
        """Text/badges that cover a face or the product are moved to the nearest clear spot; the user is told."""
        from editor.project import find_collisions, relayout_to_safe
        report = {}
        for slot, document in editor.state.documents.items():
            before = len(find_collisions(document))
            if before:
                relayout_to_safe(document)
                editor.state.defaults[slot] = document.to_dict()
            report[slot] = [before, len(find_collisions(document))]
        moved = sum(b - a for b, a in report.values())
        left = sum(a for _b, a in report.values())
        if moved or left:
            editor.message.set(f"얼굴·상품과 겹친 글자 {moved}개를 자동으로 옮겼습니다"
                               + (f" · 남은 겹침 {left}건은 직접 옮겨 주세요" if left else ""))
        editor._display()
        return report

    def shutdown(self) -> None:
        self.runner.shutdown()


class CreatePage:
    STEPS = ("1 무엇을 만들까요?", "2 내용 입력", "3 생성 설정", "4 생성 및 선택")

    def __init__(self, studio: Studio, page: ttk.Frame):
        self.studio = studio
        self.page = page
        self.kind = KINDS[0]
        self.references: list[dict[str, Any]] = []
        self.job: Job | None = None
        self.step = 0
        self._photos: list[Any] = []
        header = ttk.Frame(page, padding=(24, 14))
        header.pack(fill="x")
        self.step_labels = []
        for text in self.STEPS:
            label = ttk.Label(header, text=text, style="Step.TLabel")
            label.pack(side="left", padx=(0, 10))
            self.step_labels.append(label)
        self.body = ttk.Frame(page, padding=(28, 6))
        self.body.pack(fill="both", expand=True)
        nav = ttk.Frame(page, padding=(28, 12))
        nav.pack(fill="x", side="bottom")
        self.back_button = ttk.Button(nav, text="← 이전", command=self.back)
        self.back_button.pack(side="left")
        self.next_button = ttk.Button(nav, text="다음 →", style="Primary.TButton", command=self.next)
        self.next_button.pack(side="right")
        s = studio.settings
        self.prompt_text = ""
        self.title_var, self.subtitle_var, self.cta_var = tk.StringVar(), tk.StringVar(), tk.StringVar()
        self.episode_var = tk.StringVar(value="EP.001")
        self.channel_var = tk.StringVar(value="Tokyo Chill")
        self.width_var, self.height_var = tk.StringVar(), tk.StringVar()
        self.quality_var = tk.StringVar(value=cfg.label_for(cfg.QUALITY, s["quality"]))
        self.memory_var = tk.StringVar(value=cfg.label_for(cfg.MEMORY, s["memory"]))
        self.count_var = tk.StringVar(value=str(s.get("candidates", 2)))
        self.product_var = tk.StringVar(value=cfg.label_for(cfg.PRODUCT_MODES, s.get("product_mode", "natural")))
        self.strength_var = tk.StringVar(value=cfg.label_for(cfg.NATURAL_STRENGTH, s.get("natural_strength", "default")))
        self.advanced_product = tk.BooleanVar(value=False)
        self.seed_var = tk.StringVar(value=str(random.randint(1, 999999)))
        self.render()

    # -------------------------------------------------------------- flow
    def reset(self, family: str | None = None) -> None:
        self.family = family or "youtube"
        self.step, self.job, self.references = 0, None, []
        self.prompt_text = ""
        for var in (self.title_var, self.subtitle_var, self.cta_var):
            var.set("")
        self.seed_var.set(str(random.randint(1, 999999)))
        self.render()

    def choose(self, kind_key: str) -> None:
        self.kind = KIND_BY_KEY[kind_key]
        self.prompt_text = self.kind.prompt
        if self.kind.channel:
            self.channel_var.set(self.kind.channel)
        self.width_var.set(str(self.kind.size[0]))
        self.height_var.set(str(self.kind.size[1]))
        self.step = 1
        self.render()

    def next(self) -> None:
        if self.step == 1:
            self._capture_prompt()
            if not self.prompt_text.strip() and not self.references:
                messagebox.showwarning("내용 입력", "장면 설명을 입력하거나 레퍼런스를 추가하세요.")
                return
        if self.step == 2:
            self.generate()
            return
        if self.step == 3:
            self.reset(self.kind.family)
            return
        self.step = min(3, self.step + 1)
        self.render()

    def back(self) -> None:
        if self.step == 1:
            self._capture_prompt()
        self.step = max(0, self.step - 1)
        self.render()

    def _capture_prompt(self) -> None:
        if hasattr(self, "prompt_box"):
            try:
                self.prompt_text = self.prompt_box.get("1.0", "end").strip()
            except tk.TclError:
                pass

    # -------------------------------------------------------------- rendering
    def render(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        for index, label in enumerate(self.step_labels):
            label.configure(style="StepOn.TLabel" if index == self.step else "Step.TLabel")
        self.back_button.configure(state="normal" if 0 < self.step < 3 else "disabled")
        self.next_button.configure(text={0: "다음 →", 1: "다음 →", 2: "생성하기", 3: "새로 만들기"}[self.step],
                                   state="disabled" if self.step == 0 else "normal")
        [self._step_kind, self._step_content, self._step_settings, self._step_results][self.step]()

    def _step_kind(self) -> None:
        ttk.Label(self.body, text="무엇을 만들까요?", style="Title.TLabel").pack(anchor="w", pady=(0, 14))
        for family, title in (("youtube", "YouTube 썸네일"), ("shopify", "Shopify 이미지")):
            box = ttk.LabelFrame(self.body, text=title, padding=12)
            box.pack(fill="x", pady=8)
            for index, kind in enumerate(k for k in KINDS if k.family == family):
                size = f"{kind.size[0]}×{kind.size[1]}"
                ttk.Button(box, text=f"{kind.label}\n{size}", style="Choice.TButton", width=20,
                           command=lambda k=kind.key: self.choose(k)).grid(row=0, column=index, padx=6, pady=4)
            if getattr(self, "family", "youtube") == family:
                box.configure(text=f"{title}  ◀")

    def _step_content(self) -> None:
        kind = self.kind
        ttk.Label(self.body, text=f"{'YouTube' if kind.family == 'youtube' else 'Shopify'} · {kind.label}",
                  style="Title.TLabel").pack(anchor="w")
        ttk.Label(self.body, text="장면을 자유롭게 설명하세요 (한국어·일본어 가능). 글자는 이미지에 그리지 않고 편집기에서 얹습니다.",
                  style="Muted.TLabel").pack(anchor="w", pady=(2, 8))
        self.prompt_box = tk.Text(self.body, height=4, wrap="word", font=("Malgun Gothic", 11))
        self.prompt_box.pack(fill="x")
        self.prompt_box.insert("1.0", self.prompt_text)
        form = ttk.Frame(self.body)
        form.pack(fill="x", pady=10)
        fields = [("제목", self.title_var, 40), ("부제", self.subtitle_var, 40)]
        if kind.family == "youtube":
            fields.append(("에피소드", self.episode_var, 12))
        else:
            fields.append(("버튼(CTA)", self.cta_var, 16))
        for column, (label, var, width) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=0, column=column * 2, sticky="w", padx=(0 if column == 0 else 14, 4))
            ttk.Entry(form, textvariable=var, width=width).grid(row=0, column=column * 2 + 1, sticky="w")
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=(0, 8))
        if kind.family == "youtube":
            ttk.Label(row, text="채널").pack(side="left")
            ttk.Combobox(row, textvariable=self.channel_var, values=["Tokyo Chill", "OLD POP LOUNGE"], width=18,
                         state="readonly").pack(side="left", padx=6)
        else:
            ttk.Label(row, text="크기").pack(side="left")
            ttk.Entry(row, textvariable=self.width_var, width=6).pack(side="left", padx=(6, 2))
            ttk.Label(row, text="×").pack(side="left")
            ttk.Entry(row, textvariable=self.height_var, width=6).pack(side="left", padx=2)
            for name, (w, h) in kind.alternates.items():
                ttk.Button(row, text=name, command=lambda w=w, h=h: (self.width_var.set(str(w)), self.height_var.set(str(h)))).pack(side="left", padx=6)
        refs = ttk.LabelFrame(self.body, text="레퍼런스 이미지 (선택 · 여기로 끌어다 놓기)", padding=10)
        refs.pack(fill="x", pady=6)
        top = ttk.Frame(refs)
        top.pack(fill="x")
        ttk.Button(top, text="레퍼런스 추가", command=self.add_references).pack(side="left")
        ttk.Label(top, text="역할: 인물=얼굴·머리·옷 유지 · 상품=모양·색·로고 유지 · 스타일=빛·색감만 · 구도=배치만 · 배경=장소 분위기만",
                  style="Muted.TLabel").pack(side="left", padx=10)
        self.ref_list = ttk.Frame(refs)
        self.ref_list.pack(fill="x", pady=6)
        self._enable_drop(refs)
        self._render_refs()

    def _enable_drop(self, widget) -> None:
        try:
            from tkinterdnd2 import DND_FILES
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", lambda event: self._dropped(widget.tk.splitlist(event.data)))
        except Exception:
            pass   # drag-and-drop unavailable: the button still works

    def _dropped(self, paths) -> None:
        self._add_paths([p for p in paths if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp")])

    def add_references(self) -> None:
        self._add_paths(filedialog.askopenfilenames(title="레퍼런스 이미지",
                                                    filetypes=[("이미지", "*.png *.jpg *.jpeg *.webp *.bmp")]))

    def _add_paths(self, paths) -> None:
        for path in paths:
            if len(self.references) >= 4:
                messagebox.showinfo("레퍼런스", "레퍼런스는 최대 4장입니다.")
                break
            role = "PRODUCT" if self.kind.family == "shopify" else "PERSON"
            self.references.append({"path": str(path), "role": role})
        self._render_refs()

    def _render_refs(self) -> None:
        if not hasattr(self, "ref_list"):
            return
        for child in self.ref_list.winfo_children():
            child.destroy()
        names = {v: k for k, v in ROLES.items()}
        for index, ref in enumerate(self.references):
            row = ttk.Frame(self.ref_list)
            row.pack(fill="x", pady=2)
            photo = thumb(ref["path"], (56, 56))
            if photo:
                self._photos.append(photo)
                ttk.Label(row, image=photo).pack(side="left")
            ttk.Label(row, text=Path(ref["path"]).name, width=36).pack(side="left", padx=6)
            var = tk.StringVar(value=names.get(ref["role"], "인물"))
            box = ttk.Combobox(row, textvariable=var, values=list(ROLES), width=8, state="readonly")
            box.pack(side="left")
            box.bind("<<ComboboxSelected>>", lambda _e, ref=ref, var=var: (ref.update(role=ROLES[var.get()]), self._render_refs()))
            ttk.Button(row, text="삭제", command=lambda i=index: (self.references.pop(i), self._render_refs())).pack(side="left", padx=6)
        if any(ref["role"] == "PRODUCT" for ref in self.references):
            box = ttk.LabelFrame(self.ref_list, text="상품 처리", padding=8)
            box.pack(fill="x", pady=6)
            modes = ["자연광 보정 합성 (추천)", "원본 그대로 합성"] + (["AI 재구성 · 변형 가능"] if self.advanced_product.get() else [])
            if self.product_var.get() not in modes:
                self.product_var.set(modes[0])
            for label in modes:
                ttk.Radiobutton(box, text=label, value=label, variable=self.product_var).pack(side="left", padx=6)
            ttk.Label(box, text="자연광 강도").pack(side="left", padx=(16, 4))
            ttk.Combobox(box, textvariable=self.strength_var, values=list(cfg.NATURAL_STRENGTH), width=7,
                         state="readonly").pack(side="left")
            ttk.Checkbutton(box, text="고급", variable=self.advanced_product, command=self._render_refs).pack(side="left", padx=12)
            ttk.Label(self.ref_list, text="자연광 보정 합성: 상품 사진의 픽셀은 그대로, 배경·그림자만 맞춥니다. "
                                          "AI 재구성은 라벨·로고·모양이 바뀔 수 있습니다.", style="Muted.TLabel").pack(anchor="w")

    def _step_settings(self) -> None:
        ttk.Label(self.body, text="생성 설정", style="Title.TLabel").pack(anchor="w", pady=(0, 12))
        for title, var, options, note in (
                ("품질", self.quality_var, list(cfg.QUALITY), "빠른 미리보기 ≈20초 · 일반 ≈35초/장 · 최고 품질은 여러 방식을 비교(느림)"),
                ("PC 사용", self.memory_var, list(cfg.MEMORY), "작업 중 PC 우선: 한 장씩 만들고 바로 메모리를 돌려줍니다"),
                ("후보 수", self.count_var, ["1", "2", "4"], "")):
            box = ttk.LabelFrame(self.body, text=title, padding=10)
            box.pack(fill="x", pady=6)
            for option in options:
                ttk.Radiobutton(box, text=option, value=option, variable=var).pack(side="left", padx=10)
            if note:
                ttk.Label(box, text=note, style="Muted.TLabel").pack(side="left", padx=16)
        row = ttk.Frame(self.body)
        row.pack(fill="x", pady=8)
        ttk.Label(row, text="seed (같은 값이면 같은 결과)", style="Muted.TLabel").pack(side="left")
        ttk.Entry(row, textvariable=self.seed_var, width=10).pack(side="left", padx=6)
        ttk.Button(row, text="무작위", command=lambda: self.seed_var.set(str(random.randint(1, 999999)))).pack(side="left")

    # -------------------------------------------------------------- generate / results
    def payload(self) -> dict[str, Any]:
        kind = self.kind
        try:
            width, height = int(self.width_var.get() or kind.size[0]), int(self.height_var.get() or kind.size[1])
            seed = int(self.seed_var.get())
        except ValueError:
            width, height, seed = kind.size[0], kind.size[1], random.randint(1, 999999)
        channel = self.channel_var.get() if kind.family == "youtube" else ""
        payload = {"kind": "generate", "studio_kind": kind.key, "purpose": kind.purpose,
                   "canvas": [width, height] if kind.family == "shopify" else [1280, 720],
                   "prompt": self.prompt_text, "prompt_preset": kind.prompt_preset if self.prompt_text == kind.prompt else "",
                   "channel": channel, "people": kind.people if self.prompt_text == kind.prompt else _people(self.prompt_text),
                   "composition": kind.composition if self.prompt_text == kind.prompt else "",
                   "title": self.title_var.get(), "subtitle": self.subtitle_var.get(), "episode": self.episode_var.get(),
                   "cta": self.cta_var.get(), "references": [dict(r) for r in self.references],
                   "quality": cfg.QUALITY[self.quality_var.get()], "memory": cfg.MEMORY[self.memory_var.get()],
                   "candidates": int(self.count_var.get()), "seed": seed}
        if any(r["role"] == "PRODUCT" for r in self.references):
            payload["product_mode"] = cfg.PRODUCT_MODES.get(self.product_var.get(), "natural")
            payload["natural_strength"] = cfg.NATURAL_STRENGTH.get(self.strength_var.get(), "default")
        else:
            payload["product_mode"] = "none"
        return payload

    def generate(self, start: bool = True) -> Job:
        payload = self.payload()
        s = self.studio.settings
        s.update(quality=payload["quality"], memory=payload["memory"], candidates=payload["candidates"])
        if payload.get("product_mode") not in (None, "none"):
            s["product_mode"], s["natural_strength"] = payload["product_mode"], payload.get("natural_strength", "default")
        cfg.save(s)
        self.job = self.studio.enqueue(payload, start)
        self.step = 3
        self.render()
        return self.job

    def show_results(self, job: Job) -> None:
        self.job = job
        self.kind = KIND_BY_KEY.get(job.payload.get("studio_kind", ""), KINDS[0])
        self.step = 3
        self.render()

    def refresh_job(self) -> None:
        if self.step != 3 or self.job is None or not hasattr(self, "progress_label"):
            return
        job = self.job
        try:
            if job.state in (PENDING, RUNNING):
                text = ("대기 중 — " + ("PC 사용 중 — 자원 대기" if job.waiting_reason else "앞 작업이 끝나면 시작합니다")
                        if job.state == PENDING else f"생성 중 {int(job.progress * 100)}% · {job.message}")
                self.progress_label.configure(text=text)
                self.progress_bar["value"] = job.progress * 100
            elif not getattr(self, "_shown_result", None) == (job.id, job.state):
                self.render()
        except tk.TclError:
            pass

    def _step_results(self) -> None:
        job = self.job
        if job is None:
            return
        self._shown_result = (job.id, job.state)
        title = f"{self.studio._purpose_label(job)} — {self.studio._job_title(job) or '이미지'}"
        ttk.Label(self.body, text=title, style="H2.TLabel").pack(anchor="w")
        actions = ttk.Frame(self.body)
        actions.pack(fill="x", pady=6)
        ttk.Button(actions, text="다시 생성", command=lambda: self._requeue(new_seed=True)).pack(side="left")
        ttk.Button(actions, text="seed만 변경", command=self._change_seed).pack(side="left", padx=6)
        ttk.Button(actions, text="프롬프트 수정", command=self._edit_prompt).pack(side="left")
        if job.state in (PENDING, RUNNING):
            self.progress_label = ttk.Label(self.body, text="", style="Muted.TLabel")
            self.progress_label.pack(anchor="w", pady=(12, 4))
            self.progress_bar = ttk.Progressbar(self.body, length=520, maximum=100)
            self.progress_bar.pack(anchor="w")
            ttk.Label(self.body, text="생성은 대기열에서 진행됩니다. 다른 화면으로 이동해도 계속됩니다.",
                      style="Muted.TLabel").pack(anchor="w", pady=6)
            self.refresh_job()
            return
        if job.state == FAILED:
            error = job.error or {}
            ttk.Label(self.body, text=f"{error.get('title') or '생성 실패'}: {error.get('message', '')}", foreground="#b91c1c").pack(anchor="w", pady=8)
            ttk.Label(self.body, text=f"해결 방법: {error.get('action', '')}", style="Muted.TLabel").pack(anchor="w")
            ttk.Button(self.body, text="실패 재시도", command=lambda: (self.studio.queue.retry(job.id), self.studio.runner.start())).pack(anchor="w", pady=8)
            return
        if job.state == CANCELLED:
            ttk.Label(self.body, text="취소된 작업입니다.").pack(anchor="w", pady=8)
            return
        grid = ttk.Frame(self.body)
        grid.pack(fill="both", expand=True, pady=6)
        candidates = (job.result or {}).get("candidates", [])
        youtube = self.kind.family == "youtube"
        columns = 2 if len(candidates) > 1 else 1
        for index, cand in enumerate(candidates):
            card = ttk.Frame(grid, padding=8, relief="solid", borderwidth=1)
            card.grid(row=index // columns, column=index % columns, padx=8, pady=8, sticky="nsew")
            photo = thumb(cand["files"]["full"], (560, 330))
            if photo:
                self._photos.append(photo)
                ttk.Label(card, image=photo).pack()
            row = ttk.Frame(card)
            row.pack(fill="x", pady=4)
            keys = ("preview_340", "preview_180") if youtube else ("product", "face")
            for key in keys:
                path = cand["files"].get(key)
                if path and Path(path).exists():
                    small = thumb(path, (170 if key != "preview_180" else 90, 110))
                    if small:
                        self._photos.append(small)
                        ttk.Label(row, image=small).pack(side="left", padx=3)
            kind_label = {"composite": "원본 그대로 합성", "natural": "자연광 보정 합성", "harmonized": "AI 조명 보정 · 변형 가능",
                          "regenerated": "AI 재구성 · 변형 가능", "generated": "", "edit": "편집"}.get(cand.get("kind"), "")
            info = f"{index + 1}번 후보" + (f" · {kind_label}" if kind_label else "") + f" · seed {cand.get('seed')} · {cand.get('seconds')}초"
            ttk.Label(card, text=info).pack(anchor="w")
            warnings = [friendly_warning(w) for w in cand.get("warnings") or []]
            if warnings:
                ttk.Label(card, text="⚠ " + " / ".join(dict.fromkeys(warnings)), foreground="#b45309", wraplength=540,
                          justify="left").pack(anchor="w")
            ttk.Button(card, text="이 후보로 편집", style="Primary.TButton",
                       command=lambda i=index: self.studio.open_candidate_in_editor(job, i)).pack(anchor="e", pady=4)

    def _requeue(self, new_seed: bool) -> None:
        if self.job is None:
            return
        payload = dict(self.job.payload)
        if new_seed:
            payload["seed"] = random.randint(1, 999999)
        self.job = self.studio.enqueue(payload)
        self.render()

    def _change_seed(self) -> None:
        if self.job is None:
            return
        from tkinter import simpledialog
        value = simpledialog.askinteger("seed만 변경", "새 seed", initialvalue=int(self.job.payload.get("seed", 1)) + 1, minvalue=0)
        if value is not None:
            payload = dict(self.job.payload, seed=value)
            self.job = self.studio.enqueue(payload)
            self.render()

    def _edit_prompt(self) -> None:
        if self.job is None:
            return
        payload = self.job.payload
        self.kind = KIND_BY_KEY.get(payload.get("studio_kind", ""), KINDS[0])
        self.family = self.kind.family
        self.prompt_text = payload.get("prompt", "")
        for var, key in ((self.title_var, "title"), (self.subtitle_var, "subtitle"), (self.cta_var, "cta"),
                         (self.episode_var, "episode")):
            var.set(payload.get(key, ""))
        self.references = [dict(r) for r in payload.get("references") or []]
        canvas = payload.get("canvas") or self.kind.size
        self.width_var.set(str(canvas[0]))
        self.height_var.set(str(canvas[1]))
        self.step = 1
        self.render()


def _people(prompt: str) -> int:
    text = f" {prompt} ".casefold()
    if any(w in text for w in ("couple", "two people", "커플", "부부", "두 사람", "カップル", "夫婦", "二人")):
        return 2
    if any(w in text for w in ("woman", "man ", "girl", "boy", "person", "여성", "남성", "여자", "남자", "女性", "男性")):
        return 1
    return 0


class SettingsPage:
    def __init__(self, studio: Studio, page: ttk.Frame):
        self.studio = studio
        s = studio.settings
        canvas = tk.Canvas(page, highlightthickness=0)
        scroll = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(28, 16))
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        ttk.Label(inner, text="설정", style="Title.TLabel").pack(anchor="w", pady=(0, 10))
        self.vars: dict[str, tk.Variable] = {}

        engine = ttk.LabelFrame(inner, text="AI 엔진", padding=10)
        engine.pack(fill="x", pady=6)
        self.engine_text = ttk.Label(engine, text="", justify="left")
        self.engine_text.pack(anchor="w")
        row = ttk.Frame(engine)
        row.pack(fill="x", pady=6)
        ttk.Button(row, text="다시 확인", command=self.recheck).pack(side="left")
        ttk.Button(row, text="연결 설정…", command=self.connect).pack(side="left", padx=6)

        def folder_row(title: str, key: str, hint: str) -> None:
            box = ttk.LabelFrame(inner, text=title, padding=10)
            box.pack(fill="x", pady=6)
            var = tk.StringVar(value=s.get(key) or "")
            self.vars[key] = var
            ttk.Entry(box, textvariable=var, width=80).pack(side="left")
            ttk.Button(box, text="찾아보기", command=lambda: var.set(filedialog.askdirectory() or var.get())).pack(side="left", padx=6)
            ttk.Label(inner, text=hint, style="Muted.TLabel").pack(anchor="w")

        folder_row("모델 폴더", "models_dir", "AI 엔진의 모델 파일 폴더 (quality_v2 폴더가 들어 있는 곳). 비우면 엔진에 저장된 값을 씁니다.")
        folder_row("저장 폴더", "output_dir", f"비우면 {cfg.output_dir({**s, 'output_dir': ''})}")
        for title, key, mapping in (("기본 품질", "quality", cfg.QUALITY), ("PC 사용 모드", "memory", cfg.MEMORY)):
            box = ttk.LabelFrame(inner, text=title, padding=10)
            box.pack(fill="x", pady=6)
            var = tk.StringVar(value=cfg.label_for(mapping, s[key]))
            self.vars[key] = var
            for label in mapping:
                ttk.Radiobutton(box, text=label, value=label, variable=var).pack(side="left", padx=8)
        presets = ttk.LabelFrame(inner, text="기본 프리셋", padding=10)
        presets.pack(fill="x", pady=6)
        ttk.Label(presets, text="YouTube").pack(side="left")
        self.vars["youtube_preset"] = tk.StringVar(value=KIND_BY_KEY.get(s.get("youtube_kind", "tokyo_chill"), KINDS[0]).label)
        ttk.Combobox(presets, textvariable=self.vars["youtube_preset"], state="readonly", width=16,
                     values=[k.label for k in KINDS if k.family == "youtube"]).pack(side="left", padx=6)
        ttk.Label(presets, text="Shopify").pack(side="left", padx=(16, 0))
        self.vars["shopify_preset"] = tk.StringVar(value=KIND_BY_KEY.get(s.get("shopify_preset", "shopify_hero"), KINDS[3]).label)
        ttk.Combobox(presets, textvariable=self.vars["shopify_preset"], state="readonly", width=18,
                     values=[k.label for k in KINDS if k.family == "shopify"]).pack(side="left", padx=6)
        queue_box = ttk.LabelFrame(inner, text="대기열", padding=10)
        queue_box.pack(fill="x", pady=6)
        self.vars["auto_start"] = tk.BooleanVar(value=bool(s.get("auto_start")))
        ttk.Checkbutton(queue_box, text="작업을 추가하거나 앱을 열면 자동으로 시작", variable=self.vars["auto_start"]).pack(anchor="w")
        ttk.Button(inner, text="저장", style="Primary.TButton", command=self.save).pack(anchor="w", pady=12)
        self.advanced_open = tk.BooleanVar(value=False)
        ttk.Checkbutton(inner, text="고급 설정 보기", variable=self.advanced_open, command=self._toggle_advanced).pack(anchor="w")
        self.advanced = ttk.LabelFrame(inner, text="고급 설정", padding=10)
        self.advanced_text = tk.Text(self.advanced, height=12, width=110, font=("Consolas", 9))
        self.advanced_text.pack(fill="x")
        arow = ttk.Frame(self.advanced)
        arow.pack(fill="x", pady=6)
        ttk.Label(arow, text="작업 제한 시간(초)").pack(side="left")
        self.vars["timeout_seconds"] = tk.StringVar(value=str(s.get("timeout_seconds", 1200)))
        ttk.Entry(arow, textvariable=self.vars["timeout_seconds"], width=8).pack(side="left", padx=6)
        ttk.Button(arow, text="오픈소스 라이선스", command=getattr(studio.app, "show_licenses", lambda: None)).pack(side="left", padx=16)
        self.refresh()

    def _toggle_advanced(self) -> None:
        if self.advanced_open.get():
            self.advanced.pack(fill="x", pady=6)
            self.refresh()
        else:
            self.advanced.pack_forget()

    def refresh(self) -> None:
        status = self.studio.engine_status
        lines = [self.studio.engine_summary().replace("\n", " · ")]
        if status.get("connected") and status.get("models_dir"):
            lines.append(f"모델 폴더: {status.get('models_dir')}")
        if status.get("connected") and not status.get("ready"):
            lines.append("모델 폴더를 확인하거나 '연결 설정…'으로 AI 엔진을 지정하세요.")
        self.engine_text.configure(text="\n".join(lines))
        path, source = find_backend()
        detail = {"path": path, "source": source, **{k: v for k, v in status.items() if k not in ("message",)}}
        try:
            self.advanced_text.delete("1.0", "end")
            self.advanced_text.insert("1.0", json.dumps(detail, ensure_ascii=False, indent=2))
        except tk.TclError:
            pass

    def recheck(self) -> None:
        self.engine_text.configure(text="확인 중…")

        def work():
            self.studio.refresh_engine_status()
            self.studio.app.after(0, self.refresh)
        threading.Thread(target=work, daemon=True).start()

    def connect(self) -> None:
        from image_program import save_program
        path = filedialog.askopenfilename(title="AI 엔진 (CoverMorphStudio.exe) 선택", filetypes=[("Program", "*.exe")])
        if path:
            save_program(path)
            self.recheck()

    def save(self) -> None:
        s = self.studio.settings
        for key in ("models_dir", "output_dir"):
            s[key] = self.vars[key].get().strip()
        s["quality"] = cfg.QUALITY[self.vars["quality"].get()]
        s["memory"] = cfg.MEMORY[self.vars["memory"].get()]
        s["auto_start"] = bool(self.vars["auto_start"].get())
        s["shopify_preset"] = next((k.key for k in KINDS if k.label == self.vars["shopify_preset"].get()), "shopify_hero")
        s["youtube_preset"] = next((k.prompt_preset for k in KINDS if k.label == self.vars["youtube_preset"].get()), "tc_solo_woman")
        try:
            s["timeout_seconds"] = max(120, int(self.vars["timeout_seconds"].get()))
        except ValueError:
            pass
        s["setup_done"] = True
        cfg.save(s)
        self.recheck()
        messagebox.showinfo("설정", "저장했습니다. 프로그램을 다시 설치·업데이트해도 유지됩니다.")
