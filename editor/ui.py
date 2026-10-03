"""v0.6 Pro Editor: three-pane, layer-based, WYSIWYG thumbnail editor (Tk)."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import cv2
import numpy as np
from PIL import Image, ImageTk

from image_bridge import LaunchResult, launch_edit, launch_generate, load_image_project
from thumbnail_engine import APP_VERSION, TEMPLATE_MODE, create_candidate_images
from typography.background_fit import analyze_text_region, readability_report, suggest_text_style
from typography.font_registry import get_font_registry
from typography.layer_renderer import LayerRenderer, downscale, layout_text
from typography.text_style import PRESETS_BY_CHANNEL, get_preset, preset_names

from . import geometry as geo
from .document import (BADGE_SHAPES, OVERLAY_KINDS, SHAPE_KINDS, BadgeLayer, ImageLayer, Layer, OverlayLayer,
                       ShapeLayer, TextLayer, ThumbnailDocument)
from .fonts import EditorSettings, build_catalog, family_faces, missing_glyphs, nearest_weight
from .io_utils import read_image
from .project import (CHANNEL_PALETTES, PROJECT_FILENAME, SLOT_LABELS, SLOTS, TEXT_EFFECTS, ProjectState,
                      copy_layer_to, copy_typography_layout, default_document, export_candidate, generate_project,
                      load_project, preset_text_props, propagate_shared, relayout_to_safe, replace_backgrounds,
                      reset_candidate, save_project, sync_text_height)
from .widgets import ColorField, FontBrowser, NumberField, ScrollableFrame

ZOOM_CHOICES = ("25%", "50%", "75%", "100%", "Fit")
LEVEL_COLORS = {"GOOD": "#1f9d55", "WARNING": "#d98b00", "POOR": "#d0312d"}
OVERLAY_LABELS = {"gradient_black": "소프트 블랙 그라디언트", "gradient_white": "소프트 화이트 그라디언트",
                  "plate": "반투명 라운드 플레이트", "label_strip": "컬러 라벨 스트립", "vignette": "제목 뒤 비네트",
                  "blur_plate": "로컬 블러 플레이트"}
TYPE_LABELS = {"background": "배경", "image": "이미지", "text": "텍스트", "badge": "배지", "shape": "도형",
               "overlay": "오버레이"}
TEXTUAL_FOCUS = ("Entry", "TEntry", "Text", "TSpinbox", "Spinbox", "TCombobox")


class ProEditor(ttk.Frame):
    """Left: templates/styles/assets · Centre: WYSIWYG canvas · Right: layers + inspector."""

    def __init__(self, parent, *, settings_path: Path | None = None, status: tk.StringVar | None = None):
        super().__init__(parent)
        self.state = ProjectState()
        self.renderer = LayerRenderer()
        self.settings = EditorSettings(settings_path)
        self.status = status or tk.StringVar()
        self.message = tk.StringVar(value="프로젝트 폴더나 이미지를 열면 A/B/C 편집 문서가 만들어집니다.")
        self.zoom_choice = tk.StringVar(value="Fit")
        self.show_safe = tk.BooleanVar(value=True)
        self.show_thirds = tk.BooleanVar(value=False)
        self.show_center = tk.BooleanVar(value=False)
        self.show_subjects = tk.BooleanVar(value=True)
        self.show_reference = tk.BooleanVar(value=False)
        self.reference_opacity = tk.DoubleVar(value=0.35)
        self.snap_enabled = tk.BooleanVar(value=True)
        self.shared_lock = tk.BooleanVar(value=True)
        self.autosave = tk.BooleanVar(value=self.settings.autosave)
        self.add_plate_on_fit = tk.BooleanVar(value=True)
        self.slot_var = tk.StringVar(value="A")
        self.image_prompt = tk.StringVar()
        self.image_edit_instruction = tk.StringVar()
        self.bridge_status = tk.StringVar(value="Image Bridge: 프로젝트 폴더를 열면 활성화됩니다.")
        self.timing = tk.StringVar(value="")
        self.meter_text = tk.StringVar(value="가독성: —")
        self.fallback_text = tk.StringVar(value="")
        self.view = geo.ViewTransform(0.6, 24, 24)
        self.frame_bgr: np.ndarray | None = None
        self.reference_bgr: np.ndarray | None = None
        self.reference_palette: tuple[str, str, str] | None = None
        self._photo = None
        self._mini_photos = []
        self._render_job = None
        self._edit_started: float | None = None
        self._meter_job = None
        self._cards_job = None
        self._commit_job = None
        self._autosave_job = None
        self._baseline: dict | None = None
        self._pending_edit = False
        self._drag = None
        self._pan_active = False
        self._loading = False
        self._dirty = False
        self._fields: dict[str, object] = {}
        self._text_widget: tk.Text | None = None
        self._style_photos = []
        self._bridge_queue: queue.Queue = queue.Queue()
        self._bridge_running = False
        self._bridge_buttons: list[ttk.Button] = []
        self.timings = {"render": [], "property": [], "drag": [], "display": []}
        self._build()
        self.after(50, self._warm_fonts)

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        self._build_toolbar()
        self._build_candidate_bar()
        panes = ttk.PanedWindow(self, orient="horizontal")
        panes.pack(fill="both", expand=True, padx=4, pady=(2, 4))
        self.left = ScrollableFrame(panes, width=292)
        self.center = ttk.Frame(panes)
        self.right = ttk.Frame(panes, width=390)
        panes.add(self.left, weight=0)
        panes.add(self.center, weight=1)
        panes.add(self.right, weight=0)
        self._build_left(self.left.inner)
        self._build_center(self.center)
        self._build_right(self.right)
        top = self.winfo_toplevel()
        top.bind("<KeyPress>", self._on_key, add="+")

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self); bar.pack(fill="x", padx=4, pady=(4, 1))
        for text, command in (("프로젝트 폴더 열기", self.open_project_folder), ("이미지 열기", self.open_image),
                              ("프로젝트 열기", self.open_project_file), ("저장 (Ctrl+S)", self.save),
                              ("다른 이름으로", self.save_as), ("PNG 내보내기", self.export_current),
                              ("A/B/C 내보내기", self.export_all)):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=1)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=4)
        ttk.Button(bar, text="↶ Undo", width=7, command=self.undo).pack(side="left")
        ttk.Button(bar, text="↷ Redo", width=7, command=self.redo).pack(side="left")
        ttk.Label(bar, text=" 줌").pack(side="left")
        zoom = ttk.Combobox(bar, textvariable=self.zoom_choice, values=ZOOM_CHOICES, width=5, state="readonly")
        zoom.pack(side="left"); zoom.bind("<<ComboboxSelected>>", lambda _e: self._apply_zoom())
        for text, variable in (("안전영역", self.show_safe), ("3분할", self.show_thirds), ("중앙선", self.show_center),
                               ("피사체", self.show_subjects), ("스냅", self.snap_enabled)):
            ttk.Checkbutton(bar, text=text, variable=variable, command=self._redraw_overlay).pack(side="left", padx=1)
        ttk.Checkbutton(bar, text="자동저장", variable=self.autosave, command=self._autosave_toggled).pack(side="right")
        bridge = ttk.Frame(self); bridge.pack(fill="x", padx=4, pady=1)
        for text, command in (("배경 생성", self.bridge_generate), ("배경 편집", self.bridge_edit),
                              ("image에서 새로고침", self.bridge_refresh)):
            button = ttk.Button(bridge, text=text, command=command); button.pack(side="left", padx=1)
            self._bridge_buttons.append(button)
        ttk.Label(bridge, text=" 프롬프트").pack(side="left")
        ttk.Entry(bridge, textvariable=self.image_prompt, width=28).pack(side="left", padx=2)
        ttk.Label(bridge, text="편집 지시").pack(side="left")
        ttk.Entry(bridge, textvariable=self.image_edit_instruction, width=28).pack(side="left", padx=2)
        ttk.Label(bridge, textvariable=self.bridge_status, foreground="#3e5c77").pack(side="left", padx=6)

    def _build_candidate_bar(self) -> None:
        bar = ttk.Frame(self); bar.pack(fill="x", padx=4, pady=(1, 2))
        self.slot_buttons = {}
        for slot in SLOTS:
            button = ttk.Radiobutton(bar, text=SLOT_LABELS[slot], value=slot, variable=self.slot_var,
                                     command=lambda: self.select_slot(self.slot_var.get()), style="Toolbutton")
            button.pack(side="left", padx=1, ipadx=8)
            self.slot_buttons[slot] = button
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=6)
        ttk.Button(bar, text="선택 레이어 → 다른 후보", command=self.copy_layer_to_others).pack(side="left", padx=1)
        ttk.Button(bar, text="타이포 레이아웃 → 다른 후보", command=self.copy_layout_to_others).pack(side="left", padx=1)
        ttk.Button(bar, text="후보 초기화", command=self.reset_slot).pack(side="left", padx=1)
        ttk.Checkbutton(bar, text="EP/채널 공유 잠금", variable=self.shared_lock,
                        command=lambda: setattr(self.state, "shared_lock", self.shared_lock.get())).pack(side="left", padx=6)
        ttk.Label(bar, textvariable=self.message, foreground="#2b4d6e").pack(side="left", padx=6)

    def _section(self, parent, title: str) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text=title)
        frame.pack(fill="x", padx=4, pady=3)
        return frame

    def _build_left(self, parent) -> None:
        channel = self._section(parent, "채널 프리셋")
        for name, note in (("Tokyo Chill", "시네마틱 · 도시 · 젊은 감성"), ("OLD POP LOUNGE", "차분함 · 큰 글씨 · 높은 가독성")):
            ttk.Button(channel, text=f"{name}\n{note}", command=lambda n=name: self.apply_channel_preset(n)).pack(
                fill="x", padx=3, pady=2)
        self.recent_styles_frame = self._section(parent, "최근 · 즐겨찾기 스타일")
        self.style_frames = {}
        for channel_name in ("Tokyo Chill", "OLD POP LOUNGE"):
            frame = self._section(parent, f"타이포 프리셋 · {channel_name}")
            self.style_frames[channel_name] = frame
        effects = self._section(parent, "텍스트 스타일 카드")
        for index, name in enumerate(TEXT_EFFECTS):
            ttk.Button(effects, text=name, command=lambda n=name: self.apply_effect(n)).grid(
                row=index // 2, column=index % 2, sticky="ew", padx=2, pady=1)
        effects.columnconfigure(0, weight=1); effects.columnconfigure(1, weight=1)
        self.palette_frame = self._section(parent, "색상 팔레트 (채우기 · 외곽선 · 강조)")
        tools = self._section(parent, "배경 도구 · 레이어 추가")
        for index, kind in enumerate(OVERLAY_KINDS):
            ttk.Button(tools, text=OVERLAY_LABELS[kind], command=lambda k=kind: self.add_overlay(k)).grid(
                row=index // 2, column=index % 2, sticky="ew", padx=2, pady=1)
        for index, (text, command) in enumerate((("텍스트 추가", self.add_text), ("배지 추가", self.add_badge),
                                                  ("도형 추가", self.add_shape), ("이미지 추가", self.add_image))):
            ttk.Button(tools, text=text, command=command).grid(row=3 + index // 2, column=index % 2, sticky="ew",
                                                                 padx=2, pady=1)
        tools.columnconfigure(0, weight=1); tools.columnconfigure(1, weight=1)
        bridge = self._section(parent, "Image Bridge")
        ttk.Label(bridge, text="배경만 교체하고 텍스트·배지 레이어는 유지합니다.", wraplength=250).pack(anchor="w", padx=3)
        for text, command in (("배경 생성", self.bridge_generate), ("배경 편집", self.bridge_edit),
                              ("image에서 새로고침", self.bridge_refresh)):
            button = ttk.Button(bridge, text=text, command=command); button.pack(fill="x", padx=3, pady=1)
            self._bridge_buttons.append(button)
        reference = self._section(parent, "참고 썸네일 (비교 전용)")
        ttk.Button(reference, text="참고 이미지 열기", command=self.open_reference).pack(fill="x", padx=3, pady=1)
        self.reference_label = ttk.Label(reference, text="자동 복제하지 않고 비교만 합니다.", anchor="center")
        self.reference_label.pack(fill="x", padx=3, pady=2)
        ttk.Button(reference, text="참고 이미지에서 색상만 추출", command=self.extract_reference_palette).pack(fill="x", padx=3, pady=1)
        ttk.Button(reference, text="참고 이미지에서 레이아웃 가이드 만들기", command=self.make_reference_guide).pack(fill="x", padx=3, pady=1)
        row = ttk.Frame(reference); row.pack(fill="x", padx=3)
        ttk.Checkbutton(row, text="가이드 표시", variable=self.show_reference, command=self._display).pack(side="left")
        ttk.Scale(row, from_=0.1, to=0.8, variable=self.reference_opacity, command=lambda _v: self._display()).pack(
            side="left", fill="x", expand=True)
        self._build_palettes()

    def _build_center(self, parent) -> None:
        holder = ttk.Frame(parent); holder.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(holder, background="#1e1f24", highlightthickness=0, cursor="arrow")
        xscroll = ttk.Scrollbar(holder, orient="horizontal", command=self.canvas.xview)
        yscroll = ttk.Scrollbar(holder, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew"); yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        holder.rowconfigure(0, weight=1); holder.columnconfigure(0, weight=1)
        self.canvas_image = self.canvas.create_image(0, 0, anchor="nw")
        self.canvas.create_text(20, 20, anchor="nw", fill="#9aa0ad", font=("Segoe UI", 13), tags=("placeholder",),
                                text="프로젝트 폴더 열기 / 이미지 열기 / 프로젝트 열기로 시작하세요")
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", self._double_click)
        self.canvas.bind("<Motion>", self._hover)
        self.canvas.bind("<ButtonPress-2>", lambda e: (self.canvas.scan_mark(e.x, e.y), setattr(self, "_pan_active", True)))
        self.canvas.bind("<B2-Motion>", lambda e: (self.canvas.scan_dragto(e.x, e.y, gain=1), self._redraw_overlay()))
        self.canvas.bind("<ButtonRelease-2>", lambda _e: setattr(self, "_pan_active", False))
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.canvas.bind("<Configure>", lambda _e: self._apply_zoom() if self.zoom_choice.get() == "Fit" else None)
        bottom = ttk.Frame(parent); bottom.pack(fill="x", pady=(3, 0))
        previews = ttk.LabelFrame(bottom, text="실제 크기 미리보기 (같은 렌더러)")
        previews.pack(side="left", padx=2)
        self.preview_340 = ttk.Label(previews, text="340px", anchor="center"); self.preview_340.pack(side="left", padx=4, pady=3)
        self.preview_180 = ttk.Label(previews, text="180px", anchor="center"); self.preview_180.pack(side="left", padx=4, pady=3)
        meter = ttk.LabelFrame(bottom, text="가독성 미터")
        meter.pack(side="left", fill="both", expand=True, padx=2)
        self.meter_badge = tk.Label(meter, text="—", width=9, foreground="white", background="#666",
                                    font=("Segoe UI", 11, "bold"))
        self.meter_badge.pack(anchor="w", padx=4, pady=(4, 2))
        ttk.Label(meter, textvariable=self.meter_text, wraplength=270, justify="left").pack(anchor="w", padx=4)
        ttk.Label(meter, textvariable=self.timing, foreground="#5a6a7a").pack(anchor="w", padx=4, pady=(2, 0))

    def _build_right(self, parent) -> None:
        layers = ttk.LabelFrame(parent, text="레이어")
        layers.pack(fill="both", padx=2, pady=(0, 3))
        self.tree = ttk.Treeview(layers, columns=("vis", "lock", "name", "type"), show="headings", height=9,
                                 selectmode="browse")
        for column, text, width in (("vis", "👁", 30), ("lock", "🔒", 30), ("name", "이름", 190), ("type", "유형", 70)):
            self.tree.heading(column, text=text)
            self.tree.column(column, width=width, stretch=column == "name", anchor="center" if column != "name" else "w")
        self.tree.pack(fill="both", expand=True, padx=2, pady=2)
        self.tree.bind("<<TreeviewSelect>>", self._tree_selected)
        self.tree.bind("<Button-1>", self._tree_click, add="+")
        self.tree.bind("<Double-Button-1>", lambda _e: self.rename_layer())
        buttons = ttk.Frame(layers); buttons.pack(fill="x", padx=2, pady=(0, 2))
        for text, command in (("▲", lambda: self.move_layer(1)), ("▼", lambda: self.move_layer(-1)),
                              ("복제", self.duplicate_layer), ("삭제", self.delete_layer), ("이름", self.rename_layer)):
            ttk.Button(buttons, text=text, width=5, command=command).pack(side="left", padx=1)
        self.inspector_tabs = ttk.Notebook(parent)
        self.inspector_tabs.pack(fill="both", expand=True, padx=2)
        self.props_scroll = ScrollableFrame(self.inspector_tabs, width=360)
        self.inspector_tabs.add(self.props_scroll, text="속성")
        self.font_browser = FontBrowser(self.inspector_tabs, self.settings, self._sample_text, self.apply_font,
                                        lambda: self.state.channel)
        self.inspector_tabs.add(self.font_browser, text="폰트")
        fit = ttk.Frame(self.inspector_tabs)
        self.inspector_tabs.add(fit, text="배경 맞춤")
        self._build_fit_tab(fit)

    def _build_fit_tab(self, parent) -> None:
        ttk.Label(parent, text="선택한 텍스트 아래 배경을 분석해 채널 감성을 유지하며 색·외곽선·그림자·글로우를 맞춥니다.",
                  wraplength=340).pack(anchor="w", padx=4, pady=4)
        grid = ttk.Frame(parent); grid.pack(fill="x", padx=4)
        for index, (text, mode) in enumerate((("배경에 맞춤", "fit"), ("더 강하게", "stronger"),
                                              ("더 부드럽게", "softer"), ("대비만 보정", "contrast"))):
            ttk.Button(grid, text=text, command=lambda m=mode: self.apply_background_fit(m)).grid(
                row=index // 2, column=index % 2, sticky="ew", padx=2, pady=2)
        grid.columnconfigure(0, weight=1); grid.columnconfigure(1, weight=1)
        ttk.Checkbutton(parent, text="필요하면 플레이트/그라디언트 레이어 추가", variable=self.add_plate_on_fit).pack(anchor="w", padx=4)
        self.fit_report = tk.StringVar(value="텍스트 레이어를 선택하세요.")
        ttk.Label(parent, textvariable=self.fit_report, wraplength=340, justify="left").pack(anchor="w", padx=4, pady=6)
        self.fit_palette = tk.Canvas(parent, height=26, highlightthickness=0)
        self.fit_palette.pack(fill="x", padx=4)

    # ------------------------------------------------------------------ helpers
    @property
    def document(self) -> ThumbnailDocument | None:
        return self.state.documents.get(self.state.selected_slot)

    def selected_layer(self) -> Layer | None:
        document = self.document
        return document.get(self.state.selected_layers.get(self.state.selected_slot)) if document else None

    def _sample_text(self) -> str:
        layer = self.selected_layer()
        if isinstance(layer, (TextLayer, BadgeLayer)) and layer.text.strip():
            return layer.text
        title = self.document.by_role("main_title") if self.document else None
        return title.text if title else "思い出の夜 첫눈 Night"

    def _warm_fonts(self) -> None:
        """Scan installed fonts once, off the GUI thread; the browser fills in when ready."""
        def work():
            try:
                registry = get_font_registry()
                catalog = build_catalog(registry)
                self._bridge_queue.put(("fonts", catalog))
            except Exception as exc:  # pragma: no cover - logged only
                logging.exception("font scan failed: %s", exc)
        threading.Thread(target=work, name="font-scan", daemon=True).start()
        self.after(100, self._poll_queue)

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._bridge_queue.get_nowait()
                if kind == "fonts":
                    self.font_browser.load_catalog(payload)
                elif kind == "bridge":
                    self._bridge_finished(*payload)
                elif kind == "project":
                    self._project_ready(*payload)
                elif kind == "error":
                    self._bridge_running = False
                    self._set_bridge_buttons(True)
                    self.message.set(payload)
                    messagebox.showerror("Pro Editor", payload)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------ project lifecycle
    def open_image(self, path: str | None = None) -> None:
        path = path or filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")])
        if not path:
            return
        texts = dict(self.state.texts) if self.state.documents else {"title": "思い出の夜", "subtitle": "",
                                                                    "episode": "EP.001", "story": ""}
        self._start_project(path, self.state.channel, self.state.style or preset_names(self.state.channel)[0],
                            texts, {}, {}, {})

    def open_project_folder(self, folder: str | None = None, synchronous: bool = False) -> None:
        folder = folder or filedialog.askdirectory(title="이미지 프로젝트 폴더 선택")
        if not folder:
            return
        project = load_image_project(folder)
        if project.source_image is None:
            messagebox.showwarning("Pro Editor", "폴더에서 캔버스나 이미지 파일을 찾지 못했습니다.")
            return
        manifest = project.manifest
        channel = _channel_name(manifest.get("channel"), self.state.channel)
        style = str(manifest.get("preferred_typography") or "")
        if style not in preset_names(channel):
            style = preset_names(channel)[0]
        episode = str(manifest.get("episode") or "EP.001")
        texts = {"title": str(manifest.get("title") or "思い出の夜"), "subtitle": str(manifest.get("subtitle") or ""),
                 "episode": episode if episode.upper().startswith("EP") else f"EP.{episode.zfill(3)}",
                 "story": str(manifest.get("story_type") or "")}
        bridge = {"folder": str(project.folder), "status": dict(project.status), "warnings": list(project.warnings),
                  "reference": str(project.reference_image or "")}
        self._start_project(str(project.source_image), channel, style, texts, project.palette, bridge,
                            dict(project.subject_points), synchronous=synchronous)
        if project.reference_image:
            self.load_reference(str(project.reference_image))

    def _start_project(self, source, channel, style, texts, palette, bridge, points, synchronous=False) -> None:
        self.message.set("A/B/C 배경을 구성하는 중…")
        args = (source, channel, style, texts)
        kwargs = {"palette": palette, "bridge": bridge, "protagonist": points.get("protagonist"),
                  "counterpart": points.get("counterpart")}
        if synchronous:
            self._project_ready(generate_project(*args, **kwargs), None)
            return

        def work():
            try:
                self._bridge_queue.put(("project", (generate_project(*args, **kwargs), None)))
            except Exception as exc:
                logging.exception("project generation failed")
                self._bridge_queue.put(("error", f"프로젝트를 만들지 못했습니다: {exc}"))
        threading.Thread(target=work, name="project-generate", daemon=True).start()

    def _project_ready(self, state: ProjectState, _unused) -> None:
        self.set_state(state)
        self.message.set(f"{state.channel} · {state.style} · A/B/C 편집 문서 준비 완료")

    def set_state(self, state: ProjectState) -> None:
        self.state = state
        self.shared_lock.set(state.shared_lock)
        self.slot_var.set(state.selected_slot)
        self.zoom_choice.set(state.zoom if state.zoom in ZOOM_CHOICES else "Fit")
        self._baseline = self.document.to_dict() if self.document else None
        self._dirty = False
        self.canvas.delete("placeholder")
        self.bridge_status.set(self._bridge_summary())
        if state.reference_image and Path(state.reference_image).is_file():
            self.load_reference(state.reference_image)
        self._build_palettes()
        self._refresh_all()
        self._apply_zoom()

    def _bridge_summary(self) -> str:
        bridge = self.state.bridge or {}
        if not bridge.get("folder"):
            return "Image Bridge: 로컬 이미지 모드"
        status = bridge.get("status", {})
        flags = " · ".join(f"{name} {'✓' if status.get(key) else '–'}" for key, name in (
            ("clean_canvas", "canvas"), ("subjects", "subjects"), ("safe_zones", "safe"), ("palette", "palette"),
            ("manifest", "manifest")))
        program = os.environ.get("IMAGE_PROGRAM_EXE", "")
        ready = "연결됨" if program and Path(program).is_file() else "IMAGE_PROGRAM_EXE 미설정"
        return f"{Path(bridge['folder']).name}: {flags} · {ready}"

    def open_project_file(self, path: str | None = None) -> None:
        path = path or filedialog.askopenfilename(filetypes=[("Thumbnail project", "*.json")])
        if not path:
            return
        try:
            state = load_project(path)
        except Exception as exc:
            messagebox.showerror("프로젝트 열기", str(exc))
            return
        self.set_state(state)
        self.message.set(f"프로젝트 열기 완료: {Path(path).name}")

    def save(self) -> Path | None:
        if not self.state.documents:
            return None
        self._flush_edit()
        if self.state.project_path is None:
            return self.save_as()
        return self._save_to(self.state.project_path)

    def save_as(self) -> Path | None:
        if not self.state.documents:
            return None
        folder = self.state.bridge.get("folder") or (Path(self.state.source_background).parent
                                                      if self.state.source_background else Path.cwd())
        path = filedialog.asksaveasfilename(initialdir=str(folder), initialfile=PROJECT_FILENAME,
                                            defaultextension=".json", filetypes=[("Thumbnail project", "*.json")])
        return self._save_to(Path(path)) if path else None

    def _save_to(self, path: Path) -> Path:
        self.state.zoom = self.zoom_choice.get()
        self.state.shared_lock = self.shared_lock.get()
        saved = save_project(self.state, path, app_version=APP_VERSION)
        self._dirty = False
        self.message.set(f"저장 완료: {saved}")
        self.status.set(f"프로젝트 저장: {saved}")
        return saved

    def _autosave_toggled(self) -> None:
        self.settings.autosave = self.autosave.get(); self.settings.save()
        self._schedule_autosave()

    def _schedule_autosave(self) -> None:
        if self._autosave_job:
            self.after_cancel(self._autosave_job); self._autosave_job = None
        if self.autosave.get():
            self._autosave_job = self.after(60_000, self._autosave_tick)

    def _autosave_tick(self) -> None:
        self._autosave_job = None
        if self._dirty and self.state.project_path:
            try:
                self._save_to(self.state.project_path)
                self.message.set("자동 저장 완료 (원자적 쓰기)")
            except OSError as exc:
                self.message.set(f"자동 저장 실패: {exc}")
        self._schedule_autosave()

    def export_current(self, path: str | None = None) -> Path | None:
        if not self.document:
            return None
        slot = self.state.selected_slot
        path = path or filedialog.asksaveasfilename(defaultextension=".png", initialfile=f"thumbnail_{slot}.png",
                                                    filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg")])
        if not path:
            return None
        saved = export_candidate(self.state, slot, path, self.renderer)
        self.message.set(f"내보내기 완료: {saved}")
        return saved

    def export_all(self, folder: str | None = None) -> list[Path]:
        if not self.state.documents:
            return []
        folder = folder or filedialog.askdirectory(title="A/B/C 내보내기 폴더")
        if not folder:
            return []
        stem = Path(self.state.source_background).stem or "thumbnail"
        saved = [export_candidate(self.state, slot, Path(folder) / f"{stem}_{self.state.documents[slot].candidate_type}.png",
                                  self.renderer) for slot in SLOTS if slot in self.state.documents]
        self.message.set(f"A/B/C {len(saved)}장 내보내기 완료: {folder}")
        return saved

    # ------------------------------------------------------------------ history
    def _mark_changed(self, *, coalesce: bool = True) -> None:
        """Record an edit; slider/text bursts collapse into one undo step after 400 ms idle."""
        self._dirty = True
        if not coalesce:
            self._commit_now()
            return
        self._pending_edit = True
        if self._commit_job:
            self.after_cancel(self._commit_job)
        self._commit_job = self.after(400, self._commit_now)

    def _commit_now(self) -> None:
        if self._commit_job:
            self.after_cancel(self._commit_job); self._commit_job = None
        document = self.document
        if document is None:
            return
        current = document.to_dict()
        if self._baseline is not None and self._baseline != current:
            self.state.histories[self.state.selected_slot].push(self._baseline)
        self._baseline = current
        self._pending_edit = False

    def _flush_edit(self) -> None:
        if self._pending_edit:
            self._commit_now()

    def undo(self) -> None:
        self._restore(self.state.histories[self.state.selected_slot].undo)

    def redo(self) -> None:
        self._restore(self.state.histories[self.state.selected_slot].redo)

    def _restore(self, step) -> None:
        if not self.document:
            return
        self._flush_edit()
        snapshot = step(self.document.to_dict())
        if snapshot is None:
            return
        self.state.documents[self.state.selected_slot] = ThumbnailDocument.from_dict(snapshot)
        self._baseline = snapshot
        self._dirty = True
        if self.selected_layer() is None:
            self.state.selected_layers[self.state.selected_slot] = None
        self._refresh_all()

    # ------------------------------------------------------------------ rendering
    def _refresh_all(self) -> None:
        self._rebuild_tree()
        self._build_inspector()
        self.render_now()
        self._schedule_cards()

    def schedule_render(self, kind: str = "property", delay: int = 8) -> None:
        """Coalesce bursts of slider/text events into one render (perceived latency is measured
        from the first queued edit to the finished on-screen frame)."""
        if self._edit_started is None:
            self._edit_started = time.perf_counter()
        if self._render_job is None:
            self._render_job = self.after(delay, lambda: self.render_now(kind))

    def render_now(self, kind: str = "render") -> float:
        if self._render_job:
            self.after_cancel(self._render_job); self._render_job = None
        document = self.document
        if document is None:
            return 0.0
        start = time.perf_counter()
        queued, self._edit_started = self._edit_started, None
        self.frame_bgr = self.renderer.render(document, self.state.images,
                                              split_at=self.state.selected_layers.get(self.state.selected_slot))
        rendered = time.perf_counter()
        self._display()
        self._update_minis()
        finished = time.perf_counter()
        elapsed = (finished - (queued or start)) * 1000
        self.timings[kind].append(elapsed)
        self.timings["display"].append((finished - rendered) * 1000)
        for values in self.timings.values():
            del values[:-60]
        self.timing.set(f"렌더 {(rendered - start) * 1000:.0f} ms · 표시 {(finished - rendered) * 1000:.0f} ms · "
                        f"총 {elapsed:.0f} ms (목표 ≤120 ms)")
        self._schedule_meter()
        return elapsed

    def _display(self) -> None:
        if self.frame_bgr is None:
            return
        frame = self.frame_bgr
        if self.show_reference.get() and self.reference_bgr is not None:
            ghost = cv2.resize(self.reference_bgr, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_AREA)
            frame = cv2.addWeighted(frame, 1 - self.reference_opacity.get(), ghost, self.reference_opacity.get(), 0)
        zoom = self.view.zoom
        size = (max(1, round(frame.shape[1] * zoom)), max(1, round(frame.shape[0] * zoom)))
        shown = frame if size == (frame.shape[1], frame.shape[0]) else cv2.resize(
            frame, size, interpolation=cv2.INTER_AREA if zoom < 1 else cv2.INTER_LINEAR)
        self._photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(shown, cv2.COLOR_BGR2RGB)))
        self.canvas.itemconfigure(self.canvas_image, image=self._photo)
        self.canvas.coords(self.canvas_image, self.view.origin_x, self.view.origin_y)
        self._redraw_overlay()

    def _update_minis(self) -> None:
        if self.frame_bgr is None:
            return
        photos = []
        for label, width in ((self.preview_340, 340), (self.preview_180, 180)):
            photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(downscale(self.frame_bgr, width), cv2.COLOR_BGR2RGB)))
            label.configure(image=photo, text="")
            photos.append(photo)
        self._mini_photos = photos

    def _apply_zoom(self) -> None:
        width, height = max(200, self.canvas.winfo_width()), max(150, self.canvas.winfo_height())
        choice = self.zoom_choice.get()
        zoom = geo.fit_zoom(width, height) if choice == "Fit" else float(choice.rstrip("%")) / 100
        self.view = geo.centered_view(zoom, width, height)
        total_w = max(width, 1280 * zoom + 2 * self.view.origin_x)
        total_h = max(height, 720 * zoom + 2 * self.view.origin_y)
        self.canvas.configure(scrollregion=(0, 0, total_w, total_h))
        self.state.zoom = choice
        self._display()

    def _redraw_overlay(self) -> None:
        canvas = self.canvas
        canvas.delete("overlay")
        document = self.document
        if document is None:
            return
        view = self.view

        def rect(box, **options):
            x, y, w, h = box
            x0, y0 = view.to_view(x, y); x1, y1 = view.to_view(x + w, y + h)
            canvas.create_rectangle(x0, y0, x1, y1, tags=("overlay",), **options)

        if self.show_safe.get():
            rect((geo.SAFE_MARGIN_X, geo.SAFE_MARGIN_Y, 1280 - 2 * geo.SAFE_MARGIN_X, 720 - 2 * geo.SAFE_MARGIN_Y),
                 outline="#5fd3ff", dash=(4, 4))
            rect(geo.TIMESTAMP_BOX, outline="#ff6b6b", dash=(2, 3))
            x, y = view.to_view(geo.TIMESTAMP_BOX[0] + 4, geo.TIMESTAMP_BOX[1] + 4)
            canvas.create_text(x, y, anchor="nw", text="재생시간", fill="#ff6b6b", font=("Segoe UI", 8), tags=("overlay",))
            for zone in document.safe_zones:
                rect(zone, outline="#ff3d6e", dash=(6, 3), width=2)
        if self.show_subjects.get():
            for box in document.subject_boxes:
                rect(box, outline="#ffa94d", dash=(3, 3), width=2)
                x, y = view.to_view(box[0] + 4, box[1] + 4)
                canvas.create_text(x, y, anchor="nw", text="얼굴/피사체 회피", fill="#ffa94d", font=("Segoe UI", 8),
                                   tags=("overlay",))
        if self.show_thirds.get():
            for fraction in (1 / 3, 2 / 3):
                canvas.create_line(*view.to_view(1280 * fraction, 0), *view.to_view(1280 * fraction, 720),
                                   fill="#8f96a3", dash=(2, 4), tags=("overlay",))
                canvas.create_line(*view.to_view(0, 720 * fraction), *view.to_view(1280, 720 * fraction),
                                   fill="#8f96a3", dash=(2, 4), tags=("overlay",))
        if self.show_center.get():
            canvas.create_line(*view.to_view(640, 0), *view.to_view(640, 720), fill="#c084fc", dash=(5, 3), tags=("overlay",))
            canvas.create_line(*view.to_view(0, 360), *view.to_view(1280, 360), fill="#c084fc", dash=(5, 3), tags=("overlay",))
        if self._drag and self._drag.get("guides"):
            for axis, value in self._drag["guides"]:
                if axis == "x":
                    canvas.create_line(*view.to_view(value, 0), *view.to_view(value, 720), fill="#ff4fd8", tags=("overlay",))
                else:
                    canvas.create_line(*view.to_view(0, value), *view.to_view(1280, value), fill="#ff4fd8", tags=("overlay",))
        layer = self.selected_layer()
        if layer is not None and layer.visible:
            points = [view.to_view(*point) for point in geo.corners(layer)]
            flat = [coord for point in points for coord in point]
            canvas.create_polygon(*flat, outline="#45e6ff" if not layer.locked else "#888", fill="", width=2,
                                  tags=("overlay",))
            if not layer.locked:
                handles = geo.handle_points(layer, view)
                top_mid = handles["n"]
                canvas.create_line(*top_mid, *handles["rot"], fill="#45e6ff", tags=("overlay",))
                for name, (hx, hy) in handles.items():
                    if name in self._allowed_handles(layer) or name == "rot":
                        radius = 6 if name == "rot" else 5
                        shape = canvas.create_oval if name == "rot" else canvas.create_rectangle
                        shape(hx - radius, hy - radius, hx + radius, hy + radius, fill="white", outline="#1a8fb0",
                              width=2, tags=("overlay",))

    @staticmethod
    def _allowed_handles(layer: Layer) -> tuple[str, ...]:
        if isinstance(layer, TextLayer) and layer.auto_height:
            return ("nw", "ne", "se", "sw", "e", "w")
        return tuple(geo.HANDLE_SIGNS)

    # ------------------------------------------------------------------ canvas interaction
    def _doc_point(self, event) -> tuple[float, float, float, float]:
        vx, vy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        x, y = self.view.to_doc(vx, vy)
        return x, y, vx, vy

    def _press(self, event) -> None:
        document = self.document
        if document is None:
            return
        self.canvas.focus_set()
        self._flush_edit()
        x, y, vx, vy = self._doc_point(event)
        layer = self.selected_layer()
        if layer is not None and not layer.locked and layer.visible:
            handle = geo.handle_at(layer, self.view, vx, vy, allowed=self._allowed_handles(layer) + ("rot",))
            if handle:
                self._begin_drag("rotate" if handle == "rot" else "resize", layer, x, y, handle)
                return
        hit = geo.hit_test(document, x, y, tolerance=3 / self.view.zoom)
        if hit is None:
            self.select_layer(None)
            return
        if hit.id != (layer.id if layer else None):
            self.select_layer(hit.id)
        self._begin_drag("move", hit, x, y)

    def _begin_drag(self, mode: str, layer: Layer, x: float, y: float, handle: str | None = None) -> None:
        self._drag = {"mode": mode, "layer": layer.id, "start": (x, y), "geometry": geo.Geometry.of(layer),
                      "handle": handle, "font": getattr(layer, "font_size", None),
                      "props": {key: getattr(layer, key) for key in ("outline_width", "secondary_outline_width",
                                                                      "shadow_x", "shadow_y", "shadow_blur", "glow_blur",
                                                                      "letter_spacing", "border_width", "padding",
                                                                      "radius") if hasattr(layer, key)},
                      "targets": geo.snap_targets(self.document, {layer.id}), "guides": [], "moved": False}

    def _motion(self, event) -> None:
        drag = self._drag
        document = self.document
        if not drag or document is None:
            return
        layer = document.get(drag["layer"])
        if layer is None:
            return
        x, y, _vx, _vy = self._doc_point(event)
        sx, sy = drag["start"]
        start: geo.Geometry = drag["geometry"]
        shift = bool(event.state & 0x0001)
        alt = bool(event.state & 0x20000)
        if drag["mode"] == "move":
            layer.x, layer.y = start.x + (x - sx), start.y + (y - sy)
            drag["guides"] = []
            if self.snap_enabled.get() and not alt:
                dx, dy, guides = geo.snap_move(geo.aabb(layer), drag["targets"], 6 / self.view.zoom)
                layer.x += dx; layer.y += dy
                drag["guides"] = guides
        elif drag["mode"] == "resize":
            resized, factor = geo.resize(start, drag["handle"], x - sx, y - sy,
                                         proportional=None if not shift else drag["handle"] not in geo.CORNER_HANDLES)
            layer.x, layer.y, layer.width, layer.height = resized.x, resized.y, resized.width, resized.height
            if drag["font"] is not None and drag["handle"] in geo.CORNER_HANDLES and factor != 1.0:
                layer.font_size = max(6.0, round(drag["font"] * factor, 1))
                for key, value in drag["props"].items():
                    setattr(layer, key, round(value * factor, 2))
            if isinstance(layer, TextLayer):
                before_h = layer.height
                sync_text_height(layer, keep_center=False)
                if drag["handle"] in ("nw", "ne", "n"):
                    layer.y += before_h - layer.height
        else:
            layer.rotation = geo.rotation_from_pointer(start, (sx, sy), (x, y), snap=shift)
        drag["moved"] = True
        self._drag_render()

    def _drag_render(self) -> None:
        if self._edit_started is None:
            self._edit_started = time.perf_counter()
        if self._render_job is None:
            self._render_job = self.after(1, lambda: (self.render_now("drag"), self._refresh_inspector_values()))

    def _release(self, _event) -> None:
        drag, self._drag = self._drag, None
        if drag and drag["moved"]:
            self._mark_changed(coalesce=False)
            self.render_now("drag")
            self._refresh_inspector_values()
        else:
            self._redraw_overlay()

    def _hover(self, event) -> None:
        layer = self.selected_layer()
        if layer is None or self._drag:
            return
        vx, vy = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        handle = geo.handle_at(layer, self.view, vx, vy, allowed=self._allowed_handles(layer) + ("rot",))
        cursor = {"rot": "exchange", "n": "sb_v_double_arrow", "s": "sb_v_double_arrow", "e": "sb_h_double_arrow",
                  "w": "sb_h_double_arrow", "nw": "size_nw_se", "se": "size_nw_se", "ne": "size_ne_sw",
                  "sw": "size_ne_sw"}.get(handle or "", "fleur" if geo.contains(layer, *self.view.to_doc(vx, vy)) else "arrow")
        self.canvas.configure(cursor=cursor)

    def _double_click(self, _event) -> None:
        if isinstance(self.selected_layer(), (TextLayer, BadgeLayer)) and self._text_widget is not None:
            self.inspector_tabs.select(self.props_scroll)
            self._text_widget.focus_set()

    def _wheel(self, event) -> None:
        if event.state & 0x0004:
            index = ZOOM_CHOICES.index(self.zoom_choice.get()) if self.zoom_choice.get() in ZOOM_CHOICES else 4
            index = max(0, min(3, (index if index < 4 else 2) + (1 if event.delta > 0 else -1)))
            self.zoom_choice.set(ZOOM_CHOICES[index]); self._apply_zoom()
        else:
            self.canvas.yview_scroll(int(-event.delta / 120), "units"); self._redraw_overlay()

    def _on_key(self, event) -> str | None:
        if not self.winfo_ismapped() or self.document is None:
            return None
        focus = self.focus_get()
        typing = focus is not None and focus.winfo_class() in TEXTUAL_FOCUS
        ctrl = bool(event.state & 0x0004)
        key = event.keysym.lower()
        if ctrl and key == "s":
            self.save(); return "break"
        if typing:
            return None
        if ctrl and key == "z":
            self.redo() if event.state & 0x0001 else self.undo(); return "break"
        if ctrl and key == "y":
            self.redo(); return "break"
        if ctrl and key == "d":
            self.duplicate_layer(); return "break"
        if key == "delete":
            self.delete_layer(); return "break"
        if key in ("left", "right", "up", "down"):
            self.nudge(key, 10 if event.state & 0x0001 else 1); return "break"
        return None

    def nudge(self, direction: str, step: float) -> None:
        layer = self.selected_layer()
        if layer is None or layer.locked:
            return
        dx, dy = {"left": (-step, 0), "right": (step, 0), "up": (0, -step), "down": (0, step)}[direction]
        layer.x += dx; layer.y += dy
        self._mark_changed()
        self.render_now("drag")
        self._refresh_inspector_values()

    # ------------------------------------------------------------------ selection / layer list
    def select_slot(self, slot: str) -> None:
        if slot not in self.state.documents:
            return
        self._flush_edit()
        self.state.selected_slot = slot
        self.slot_var.set(slot)
        self._baseline = self.document.to_dict()
        self._refresh_all()

    def select_layer(self, layer_id: str | None) -> None:
        self.state.selected_layers[self.state.selected_slot] = layer_id
        if layer_id and self.tree.exists(layer_id):
            if self.tree.selection() != (layer_id,):
                self.tree.selection_set(layer_id)
        elif self.tree.selection():
            self.tree.selection_remove(*self.tree.selection())
        self._build_inspector()
        self._redraw_overlay()
        self._schedule_meter()

    def _rebuild_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        document = self.document
        if document is None:
            return
        for layer in reversed(document.ordered()):
            self.tree.insert("", "end", iid=layer.id, values=self._tree_values(layer))
        selected = self.state.selected_layers.get(self.state.selected_slot)
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)

    @staticmethod
    def _tree_values(layer: Layer):
        return ("●" if layer.visible else "○", "🔒" if layer.locked else "", layer.name or layer.type,
                TYPE_LABELS.get(layer.type, layer.type))

    def _tree_selected(self, _event) -> None:
        selection = self.tree.selection()
        layer_id = selection[0] if selection else None
        if layer_id != self.state.selected_layers.get(self.state.selected_slot):
            self.select_layer(layer_id)

    def _tree_click(self, event) -> str | None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return None
        column = self.tree.identify_column(event.x)
        layer_id = self.tree.identify_row(event.y)
        layer = self.document.get(layer_id) if self.document else None
        if layer is None or column not in ("#1", "#2"):
            return None
        if column == "#1":
            layer.visible = not layer.visible
        else:
            layer.locked = not layer.locked
        self.tree.item(layer.id, values=self._tree_values(layer))
        self._mark_changed(coalesce=False)
        self.render_now()
        return "break"

    def toggle_visibility(self, layer_id: str) -> None:
        layer = self.document.get(layer_id)
        layer.visible = not layer.visible
        self._mark_changed(coalesce=False); self._rebuild_tree(); self.render_now()

    def toggle_lock(self, layer_id: str) -> None:
        layer = self.document.get(layer_id)
        layer.locked = not layer.locked
        self._mark_changed(coalesce=False); self._rebuild_tree(); self._redraw_overlay()

    def move_layer(self, steps: int) -> None:
        layer = self.selected_layer()
        if layer is not None and self.document.move(layer.id, steps):
            self._mark_changed(coalesce=False); self._rebuild_tree(); self.render_now()

    def duplicate_layer(self) -> None:
        layer = self.selected_layer()
        if layer is None or layer.type == "background":
            return
        clone = self.document.duplicate(layer.id)
        self._mark_changed(coalesce=False)
        self.state.selected_layers[self.state.selected_slot] = clone.id
        self._refresh_all()

    def delete_layer(self) -> None:
        layer = self.selected_layer()
        if layer is None or layer.type == "background":
            return
        self.document.remove(layer.id)
        self.state.selected_layers[self.state.selected_slot] = None
        self._mark_changed(coalesce=False)
        self._refresh_all()

    def rename_layer(self, name: str | None = None) -> None:
        layer = self.selected_layer()
        if layer is None:
            return
        name = name if name is not None else simpledialog.askstring("레이어 이름", "새 이름", initialvalue=layer.name,
                                                                      parent=self)
        if name:
            layer.name = name
            self._mark_changed(coalesce=False)
            self.tree.item(layer.id, values=self._tree_values(layer))

    def _add_layer(self, layer: Layer, below: str | None = None) -> Layer:
        document = self.document
        if document is None:
            return layer
        document.add(layer, below=below)
        self.state.selected_layers[self.state.selected_slot] = layer.id
        self._mark_changed(coalesce=False)
        self._refresh_all()
        return layer

    def add_text(self) -> Layer | None:
        if not self.document:
            return None
        layer = TextLayer(name="텍스트", text="새 텍스트", x=420, y=300, width=440, height=80, font_size=64,
                          **{k: v for k, v in preset_text_props(self.state.style, self.state.channel).items()})
        sync_text_height(layer)
        return self._add_layer(layer)

    def add_badge(self) -> Layer | None:
        if not self.document:
            return None
        preset = get_preset(self.state.style, self.state.channel)
        return self._add_layer(BadgeLayer(name="배지", text="NEW", channel=self.state.channel, x=560, y=120, width=200,
                                          height=56, fill=preset.outline, border_color=preset.accent))

    def add_shape(self) -> Layer | None:
        if not self.document:
            return None
        return self._add_layer(ShapeLayer(name="도형", x=540, y=260, width=200, height=200, fill="#FFFFFF80"))

    def add_image(self, path: str | None = None) -> Layer | None:
        if not self.document:
            return None
        path = path or filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")])
        if not path:
            return None
        image = read_image(path, cv2.IMREAD_UNCHANGED)
        if image is None:
            messagebox.showerror("이미지 추가", "이미지를 읽을 수 없습니다.")
            return None
        h, w = image.shape[:2]
        scale = min(400 / w, 400 / h, 1.0)
        return self._add_layer(ImageLayer(name=Path(path).name, source=str(path), x=440, y=160, width=w * scale,
                                          height=h * scale, fit="contain"))

    def add_overlay(self, kind: str) -> Layer | None:
        document = self.document
        if document is None:
            return None
        anchor = self.selected_layer()
        if anchor is None or anchor.type not in ("text", "badge"):
            anchor = document.by_role("main_title")
        if kind == "vignette":
            box = (0.0, 0.0, 1280.0, 720.0)
        elif anchor is not None:
            x, y, w, h = geo.aabb(anchor)
            pad = 28.0 if kind in ("plate", "blur_plate", "label_strip") else 120.0
            box = (x - pad, y - pad * 0.6, w + 2 * pad, h + 1.2 * pad)
            if kind in ("gradient_black", "gradient_white"):
                box = (0.0, max(0.0, y - 120), 1280.0, 720.0 - max(0.0, y - 120)) if y > 300 else \
                      (0.0, 0.0, 1280.0, min(720.0, y + h + 120))
        else:
            box = (340.0, 220.0, 600.0, 280.0)
        defaults = {"gradient_black": dict(color="#000000", strength=0.65, blur=60, radius=0,
                                           direction="bottom" if box[1] > 0 else "top"),
                    "gradient_white": dict(color="#FFFFFF", strength=0.55, blur=60, radius=0,
                                           direction="bottom" if box[1] > 0 else "top"),
                    "plate": dict(color="#000000", strength=0.45, blur=18, radius=26),
                    "label_strip": dict(color=get_preset(self.state.style, self.state.channel).accent, strength=0.92,
                                        blur=0, radius=6),
                    "vignette": dict(color="#000000", strength=0.6, blur=0, radius=0),
                    "blur_plate": dict(color="#000000", strength=0.5, blur=14, radius=24)}[kind]
        layer = OverlayLayer(name=OVERLAY_LABELS[kind], kind=kind, x=box[0], y=box[1], width=box[2], height=box[3],
                             **defaults)
        return self._add_layer(layer, below=anchor.id if anchor is not None and kind != "vignette" else None)

    # ------------------------------------------------------------------ inspector
    def _build_inspector(self) -> None:
        parent = self.props_scroll.inner
        for child in parent.winfo_children():
            child.destroy()
        self._fields = {}
        self._text_widget = None
        layer = self.selected_layer()
        if layer is None:
            ttk.Label(parent, text="캔버스나 레이어 목록에서 레이어를 선택하세요.\n방향키 1px · Shift+방향키 10px · "
                                   "Delete 삭제 · Ctrl+D 복제 · Ctrl+Z/Y · Ctrl+S", justify="left").pack(anchor="w", padx=6, pady=8)
            self.fallback_text.set("")
            return
        self._loading = True
        try:
            transform = ttk.LabelFrame(parent, text=f"{TYPE_LABELS.get(layer.type, layer.type)} · 변형")
            transform.pack(fill="x", padx=3, pady=2)
            transform.columnconfigure(1, weight=1)
            row = 0
            for attr, label, low, high in (("x", "X", -400, 1680), ("y", "Y", -300, 1020), ("width", "너비", 8, 1600),
                                           ("height", "높이", 8, 1000), ("rotation", "회전", -180, 180),
                                           ("opacity", "불투명도", 0, 1)):
                if attr == "height" and isinstance(layer, TextLayer) and layer.auto_height:
                    continue
                self._number(transform, row, label, attr, low, high, integer=attr in ("x", "y", "width", "height"))
                row += 1
            if isinstance(layer, TextLayer):
                self._text_inspector(parent, layer)
            elif isinstance(layer, BadgeLayer):
                self._badge_inspector(parent, layer)
            elif isinstance(layer, ShapeLayer):
                frame = self._group(parent, "도형")
                self._choice(frame, 0, "모양", "shape", SHAPE_KINDS)
                self._color(frame, 1, "채우기", "fill")
                self._color(frame, 2, "테두리", "border_color")
                self._number(frame, 3, "테두리 두께", "border_width", 0, 30)
                self._number(frame, 4, "모서리", "radius", 0, 200)
            elif isinstance(layer, OverlayLayer):
                frame = self._group(parent, "오버레이 / 플레이트")
                self._choice(frame, 0, "종류", "kind", OVERLAY_KINDS)
                self._color(frame, 1, "색상", "color")
                self._choice(frame, 2, "그라디언트 방향", "direction", ("bottom", "top", "left", "right", "center"))
                self._number(frame, 3, "강도", "strength", 0, 1)
                self._number(frame, 4, "블러/페더", "blur", 0, 120)
                self._number(frame, 5, "모서리", "radius", 0, 200)
            elif layer.type in ("image", "background"):
                frame = self._group(parent, "이미지")
                ttk.Label(frame, text=Path(layer.source).name if not layer.source.startswith("asset://")
                          else "생성된 A/B/C 배경 (Image Bridge로 교체)", wraplength=300).grid(row=0, column=0, columnspan=3,
                                                                                         sticky="w", padx=4)
                self._choice(frame, 1, "맞춤", "fit", ("cover", "contain", "stretch"))
        finally:
            self._loading = False
        self._update_fallback_warning()

    def _group(self, parent, title: str) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text=title)
        frame.pack(fill="x", padx=3, pady=2)
        frame.columnconfigure(1, weight=1)
        return frame

    def _text_inspector(self, parent, layer: TextLayer) -> None:
        content = self._group(parent, "텍스트 (줄바꿈 = 수동 줄나눔)")
        self._text_widget = tk.Text(content, height=3, width=34, wrap="word", font=("Segoe UI", 10))
        self._text_widget.insert("1.0", layer.text)
        self._text_widget.grid(row=0, column=0, columnspan=3, sticky="ew", padx=4, pady=2)
        self._text_widget.bind("<KeyRelease>", lambda _e: self._text_changed())
        self._entry(content, 1, "강조 단어", "highlight_word")
        self._check(content, 2, "수동 줄바꿈 사용", "manual_line_breaks")
        self._number(content, 3, "최대 줄 수", "max_lines", 1, 5, integer=True)
        ttk.Label(content, textvariable=self.fallback_text, foreground="#b45309", wraplength=320).grid(
            row=4, column=0, columnspan=3, sticky="w", padx=4)
        font = self._group(parent, "글꼴")
        ttk.Label(font, text="글꼴").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Label(font, text=layer.font_family or "(자동 · 채널 기본)", foreground="#1d4ed8").grid(row=0, column=1, sticky="w")
        ttk.Button(font, text="폰트 브라우저", command=lambda: self.inspector_tabs.select(self.font_browser)).grid(
            row=0, column=2, padx=2)
        weights = sorted({face.weight for face in family_faces(layer.font_family)}) if layer.font_family else []
        self._choice(font, 1, "굵기", "font_weight", tuple(str(w) for w in (weights or (400, 700, 900))), cast=int)
        self._number(font, 2, "크기", "font_size", 10, 260)
        self._number(font, 3, "자간", "letter_spacing", -10, 30)
        self._number(font, 4, "행간", "line_spacing", 0.7, 1.8)
        self._choice(font, 5, "정렬", "alignment", ("left", "center", "right"))
        fill = self._group(parent, "채우기 · 강조")
        self._color(fill, 0, "채우기", "fill")
        self._check(fill, 1, "세로 그라디언트", "gradient")
        self._color(fill, 2, "그라디언트 끝", "gradient_end")
        self._color(fill, 3, "강조 색", "highlight_color")
        self._number(fill, 4, "강조 크기", "highlight_scale", 0.8, 1.5)
        outline = self._group(parent, "외곽선")
        self._color(outline, 0, "외곽선", "outline_color")
        self._number(outline, 1, "두께", "outline_width", 0, 40)
        self._color(outline, 2, "2차 외곽선", "secondary_outline_color")
        self._number(outline, 3, "2차 두께", "secondary_outline_width", 0, 20)
        shadow = self._group(parent, "그림자")
        self._color(shadow, 0, "색", "shadow_color")
        self._number(shadow, 1, "X", "shadow_x", -40, 40)
        self._number(shadow, 2, "Y", "shadow_y", -40, 40)
        self._number(shadow, 3, "블러", "shadow_blur", 0, 60)
        self._number(shadow, 4, "불투명도", "shadow_opacity", 0, 1)
        glow = self._group(parent, "Glow")
        self._color(glow, 0, "색", "glow_color")
        self._number(glow, 1, "블러", "glow_blur", 0, 80)
        self._number(glow, 2, "불투명도", "glow_opacity", 0, 1)

    def _badge_inspector(self, parent, layer: BadgeLayer) -> None:
        frame = self._group(parent, "배지 / 라벨")
        self._entry(frame, 0, "텍스트", "text")
        self._choice(frame, 1, "모양", "shape", BADGE_SHAPES)
        self._color(frame, 2, "채우기", "fill")
        self._color(frame, 3, "글자색", "text_color")
        self._color(frame, 4, "테두리", "border_color")
        self._number(frame, 5, "테두리 두께", "border_width", 0, 12)
        self._number(frame, 6, "모서리", "radius", 0, 60)
        self._number(frame, 7, "여백", "padding", 0, 60)
        self._number(frame, 8, "글자 크기", "font_size", 8, 80)
        ttk.Button(frame, text="폰트 브라우저", command=lambda: self.inspector_tabs.select(self.font_browser)).grid(
            row=9, column=1, sticky="w", pady=2)

    def _number(self, parent, row, label, attr, low, high, integer=False):
        layer = self.selected_layer()
        field = NumberField(parent, row, label, low, high, getattr(layer, attr),
                            lambda value, a=attr: self.set_property(a, value), integer=integer)
        self._fields[attr] = field
        return field

    def _color(self, parent, row, label, attr):
        layer = self.selected_layer()
        field = ColorField(parent, row, label, getattr(layer, attr), lambda value, a=attr: self.set_property(a, value))
        self._fields[attr] = field
        return field

    def _choice(self, parent, row, label, attr, values, cast=str):
        layer = self.selected_layer()
        variable = tk.StringVar(value=str(getattr(layer, attr)))
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(4, 2), pady=1)
        box = ttk.Combobox(parent, textvariable=variable, values=list(values), state="readonly", width=14)
        box.grid(row=row, column=1, columnspan=2, sticky="w", padx=2, pady=1)
        box.bind("<<ComboboxSelected>>", lambda _e: self.set_property(attr, cast(variable.get())))
        self._fields[attr] = variable

    def _check(self, parent, row, label, attr):
        layer = self.selected_layer()
        variable = tk.BooleanVar(value=bool(getattr(layer, attr)))
        ttk.Checkbutton(parent, text=label, variable=variable,
                        command=lambda: self.set_property(attr, bool(variable.get()))).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=4)
        self._fields[attr] = variable

    def _entry(self, parent, row, label, attr):
        layer = self.selected_layer()
        variable = tk.StringVar(value=str(getattr(layer, attr)))
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(4, 2), pady=1)
        ttk.Entry(parent, textvariable=variable, width=22).grid(row=row, column=1, columnspan=2, sticky="ew", padx=2)
        variable.trace_add("write", lambda *_: None if self._loading else self.set_property(attr, variable.get()))
        self._fields[attr] = variable

    def _text_changed(self) -> None:
        if self._text_widget is None:
            return
        value = self._text_widget.get("1.0", "end-1c")
        layer = self.selected_layer()
        if isinstance(layer, TextLayer) and value != layer.text:
            self.set_property("text", value)

    def _refresh_inspector_values(self) -> None:
        layer = self.selected_layer()
        if layer is None:
            return
        self._loading = True
        try:
            for attr, field in self._fields.items():
                value = getattr(layer, attr, None)
                if isinstance(field, (NumberField, ColorField)):
                    field.set(value)
                elif isinstance(field, (tk.StringVar, tk.BooleanVar)) and str(field.get()) != str(value):
                    field.set(value)
        finally:
            self._loading = False

    def set_property(self, attr: str, value, layer: Layer | None = None) -> None:
        """Live property edit: no Generate step, no AI call, same Skia/HarfBuzz renderer as export."""
        if self._loading:
            return
        layer = layer or self.selected_layer()
        if layer is None or getattr(layer, attr, object()) == value:
            return
        start = time.perf_counter()
        setattr(layer, attr, value)
        if isinstance(layer, TextLayer) and attr in ("text", "font_family", "font_weight", "font_size",
                                                     "letter_spacing", "line_spacing", "width", "max_lines",
                                                     "manual_line_breaks", "highlight_word", "highlight_scale",
                                                     "auto_height"):
            sync_text_height(layer)
        if attr == "text":
            changed = propagate_shared(self.state, self.state.selected_slot, layer)
            if changed:
                self.message.set(f"공유 잠금: {', '.join(changed)} 후보의 {layer.name}도 변경")
            if layer.role == "main_title":
                self._schedule_cards()
                self.font_browser.invalidate_samples()
        if attr == "name":
            self.tree.item(layer.id, values=self._tree_values(layer))
        if attr in ("text", "font_family"):
            self._update_fallback_warning()
        self._mark_changed()
        self._edit_started = self._edit_started or start
        self.schedule_render("property")
        if attr in ("font_size", "width", "text") and isinstance(layer, TextLayer):
            self._refresh_inspector_values()

    def set_properties(self, values: dict, layer: Layer | None = None) -> None:
        layer = layer or self.selected_layer()
        if layer is None:
            return
        for attr, value in values.items():
            if hasattr(layer, attr):
                setattr(layer, attr, value)
        sync_text_height(layer)
        self._mark_changed(coalesce=False)
        self._build_inspector()
        self.render_now("property")

    def _update_fallback_warning(self) -> None:
        layer = self.selected_layer()
        if not isinstance(layer, (TextLayer, BadgeLayer)) or not layer.font_family:
            self.fallback_text.set("")
            return
        missing = missing_glyphs(layer.font_family, layer.text)
        self.fallback_text.set(f"⚠ '{layer.font_family}'에 없는 글자 {''.join(missing[:12])} → 대체 글꼴로 표시"
                               if missing else "")

    def apply_font(self, family: str) -> None:
        layer = self.selected_layer()
        if not isinstance(layer, (TextLayer, BadgeLayer)):
            title = self.document.by_role("main_title") if self.document else None
            if title is None:
                return
            self.select_layer(title.id)
            layer = title
        weight = nearest_weight(family, layer.font_weight) if family else layer.font_weight
        layer.font_family = family
        layer.font_weight = weight
        sync_text_height(layer)
        self._mark_changed()
        self._build_inspector()
        self.render_now("property")
        self.message.set(f"글꼴 적용: {family or '자동'} {weight}")

    # ------------------------------------------------------------------ styles / palettes / channel
    def _target_text(self) -> TextLayer | None:
        layer = self.selected_layer()
        if isinstance(layer, TextLayer):
            return layer
        return self.document.by_role("main_title") if self.document else None

    def apply_style(self, style_name: str, channel: str) -> None:
        layer = self._target_text()
        if layer is None:
            return
        self.state.style = style_name
        props = preset_text_props(style_name, channel)
        if self.document and self.document.metadata is not None:
            self.document.metadata["style"] = style_name
        self.settings.use_style(f"{channel}|{style_name}")
        self.set_properties(props, layer)
        self._build_recent_styles()

    def apply_effect(self, name: str) -> None:
        layer = self._target_text()
        if layer is not None:
            self.set_properties(dict(TEXT_EFFECTS[name]), layer)

    def apply_palette(self, fill: str, outline: str, highlight: str) -> None:
        layer = self._target_text()
        if layer is not None:
            self.set_properties({"fill": fill, "outline_color": outline, "highlight_color": highlight,
                                 "gradient_end": fill}, layer)

    def apply_channel_preset(self, channel: str) -> None:
        """Re-flow the current candidate with the channel's identity; text and background are kept."""
        document = self.document
        if document is None:
            return
        self._flush_edit()
        slot = self.state.selected_slot
        style = preset_names(channel)[0]
        title = document.by_role("main_title")
        texts = dict(self.state.texts)
        if title is not None:
            texts["title"] = title.text
        background = document.background()
        rebuilt = default_document(slot, channel, style, texts, background.source if background else "",
                                   document.subject_boxes, document.safe_zones, None)
        self.state.histories[slot].push(document.to_dict())
        self.state.documents[slot] = rebuilt
        self.state.channel, self.state.style = channel, style
        self._baseline = rebuilt.to_dict()
        new_title = rebuilt.by_role("main_title")
        self.state.selected_layers[slot] = new_title.id if new_title else None
        self._dirty = True
        self._build_palettes()
        self._refresh_all()
        self.message.set(f"{slot} 후보에 {channel} 채널 프리셋 적용")

    def _build_palettes(self) -> None:
        frame = self.palette_frame
        for child in frame.winfo_children():
            child.destroy()
        rows = [(f"{channel[:10]} · {name}", fill, outline, highlight)
                for channel in (self.state.channel, *(c for c in CHANNEL_PALETTES if c != self.state.channel))
                for name, fill, outline, highlight in CHANNEL_PALETTES[channel]]
        palette = self.state.palette or {}
        if palette.get("fill_color") or palette.get("stroke_color"):
            rows.insert(0, ("프로젝트 palette.json", palette.get("fill_color", "#FFFFFF"),
                            palette.get("stroke_color", "#111111"), palette.get("highlight_color", "#FFE23A")))
        if self.reference_palette:
            rows.insert(0, ("참고 이미지 추출", *self.reference_palette))
        for index, (name, fill, outline, highlight) in enumerate(rows):
            row = ttk.Frame(frame); row.pack(fill="x", padx=2, pady=1)
            for color in (fill, outline, highlight):
                swatch = tk.Label(row, width=2, background=color[:7], relief="solid", borderwidth=1, cursor="hand2")
                swatch.pack(side="left", padx=1)
                swatch.bind("<Button-1>", lambda _e, c=(fill, outline, highlight): self.apply_palette(*c))
            label = ttk.Label(row, text=name, cursor="hand2")
            label.pack(side="left", padx=4)
            label.bind("<Button-1>", lambda _e, c=(fill, outline, highlight): self.apply_palette(*c))

    def _schedule_cards(self) -> None:
        if self._cards_job:
            self.after_cancel(self._cards_job)
        self._cards_job = self.after(350, self._build_style_cards)

    def _style_card_image(self, style, text: str) -> ImageTk.PhotoImage:
        card = ThumbnailDocument(canvas_width=132, canvas_height=58)
        card.add(OverlayLayer(kind="gradient_black", color="#3a3f55", x=0, y=0, width=132, height=58,
                              direction="top", strength=1.0, blur=0))
        layer = TextLayer(text=text, x=4, y=4, width=124, height=50, font_size=24, max_lines=1, alignment="center",
                          **preset_text_props(style.name, style.channel))
        widest = max(layout_text(layer).line_widths or (1.0,))
        if widest > 118:  # preview the real title, shrunk to the card instead of clipped
            layer.font_size = max(9.0, round(24 * 118 / widest, 1))
        scale = layer.font_size / 96
        layer.outline_width = max(1.5, layer.outline_width * scale * 1.2); layer.glow_blur *= scale
        layer.shadow_blur *= scale; layer.shadow_x, layer.shadow_y = 1.0, 1.5
        sync_text_height(layer)
        layer.y = (58 - layer.height) / 2
        card.add(layer)
        frame = self.renderer.render(card, {}, background_color="#2a2d38")
        return ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)))

    def _build_style_cards(self) -> None:
        self._cards_job = None
        title = self.document.by_role("main_title") if self.document else None
        text = (title.text if title else "思い出の夜").replace("\n", " ").strip()[:14] or "Aa"
        self._style_photos = []
        for channel, frame in self.style_frames.items():
            for child in frame.winfo_children():
                child.destroy()
            for index, style in enumerate(PRESETS_BY_CHANNEL[channel]):
                photo = self._style_card_image(style, text)
                self._style_photos.append(photo)
                favorite = f"{channel}|{style.name}" in self.settings.favorite_styles
                button = ttk.Button(frame, image=photo, text=("★ " if favorite else "") + style.name, compound="top",
                                    command=lambda s=style: self.apply_style(s.name, s.channel))
                button.grid(row=index // 2, column=index % 2, padx=1, pady=1, sticky="ew")
                button.bind("<Button-3>", lambda _e, s=style: (self.settings.toggle_favorite_style(f"{s.channel}|{s.name}"),
                                                               self._schedule_cards()))
            frame.columnconfigure(0, weight=1); frame.columnconfigure(1, weight=1)
        self._build_recent_styles()

    def _build_recent_styles(self) -> None:
        frame = self.recent_styles_frame
        for child in frame.winfo_children():
            child.destroy()
        entries = list(dict.fromkeys(self.settings.favorite_styles + self.settings.recent_styles))[:6]
        if not entries:
            ttk.Label(frame, text="스타일 카드를 쓰면 여기에 표시됩니다 (우클릭 = ★)").pack(anchor="w", padx=3)
        for entry in entries:
            channel, _, name = entry.partition("|")
            star = "★ " if entry in self.settings.favorite_styles else ""
            ttk.Button(frame, text=f"{star}{name} · {channel}", command=lambda c=channel, n=name: self.apply_style(n, c)).pack(
                fill="x", padx=3, pady=1)

    # ------------------------------------------------------------------ background fit / readability
    def _schedule_meter(self) -> None:
        if self._meter_job:
            self.after_cancel(self._meter_job)
        self._meter_job = self.after(220, self.update_meter)

    def _analysis_for(self, layer: Layer):
        document = self.document
        backdrop = self.renderer.render(document, self.state.images, skip_ids={layer.id})
        return analyze_text_region(backdrop, geo.aabb(layer), document.subject_boxes)

    def update_meter(self) -> dict | None:
        self._meter_job = None
        layer = self._target_text()
        if layer is None:
            return None
        analysis = self._analysis_for(layer)
        report = readability_report(layer.to_dict(), analysis, role="title" if layer.role == "main_title" else "label")
        color = LEVEL_COLORS[report["level"]]
        self.meter_badge.configure(text=report["level"], background=color)
        lines = [f"{layer.name}: 대비 {report['contrast']}:1 ({report['contrast_level']}) · "
                 f"340px {report['px340']}px {report['level340']} · 180px {report['px180']}px {report['level180']}"]
        lines += report["messages"]
        self.meter_text.set("\n".join(lines))
        self.fit_report.set(f"평균 밝기 {analysis.mean_luminance:.2f} · 국부 대비 {analysis.local_contrast:.2f} · "
                            f"복잡도 {analysis.edge_density:.2f} · 피사체 겹침 {analysis.subject_overlap:.0%}\n" + "\n".join(lines))
        self.fit_palette.delete("all")
        for index, swatch in enumerate(analysis.palette):
            self.fit_palette.create_rectangle(index * 30, 2, index * 30 + 26, 24, fill=swatch, outline="#555")
        self.last_report = report
        return report

    def apply_background_fit(self, mode: str) -> dict | None:
        layer = self._target_text()
        document = self.document
        if layer is None or document is None:
            return None
        analysis = self._analysis_for(layer)
        suggestion = suggest_text_style(analysis, document.channel, mode, layer.to_dict(), self.state.palette)
        plate = suggestion.pop("plate", None)
        for attr, value in suggestion.items():
            setattr(layer, attr, value)
        if plate and self.add_plate_on_fit.get():
            backdrop = document.by_role(f"plate:{layer.id}") or (
                document.by_role("title_backdrop") if layer.role == "main_title" else None)
            if backdrop is None:
                x, y, w, h = geo.aabb(layer)
                pad = 30.0
                backdrop = OverlayLayer(name="배경 맞춤 플레이트", role=f"plate:{layer.id}", x=x - pad, y=y - pad * 0.6,
                                        width=w + 2 * pad, height=h + 1.2 * pad, radius=26, blur=24)
                document.add(backdrop, below=layer.id)
            backdrop.visible = True
            backdrop.kind = plate["kind"] if backdrop.role.startswith("plate:") or plate["kind"] != "plate" else backdrop.kind
            backdrop.strength = max(backdrop.strength, plate["strength"]) if mode != "softer" else plate["strength"]
            backdrop.color = plate.get("color", backdrop.color)
        self._mark_changed(coalesce=False)
        self._refresh_all()
        report = self.update_meter()
        self.message.set(f"배경 맞춤 ({mode}) 적용 · 가독성 {report['level'] if report else '—'}")
        return report

    # ------------------------------------------------------------------ A/B/C
    def copy_layer_to_others(self) -> None:
        layer = self.selected_layer()
        if layer is None:
            return
        changed = copy_layer_to(self.state, self.state.selected_slot, layer.id)
        self._dirty = True
        self.message.set(f"'{layer.name}' → {', '.join(changed)} 후보에 복사")

    def copy_layout_to_others(self) -> None:
        if not self.document:
            return
        changed = copy_typography_layout(self.state, self.state.selected_slot)
        self._dirty = True
        self.message.set(f"{self.state.selected_slot} 타이포 레이아웃 → {', '.join(changed)} 후보에 복사")

    def reset_slot(self) -> None:
        if not self.document:
            return
        self._flush_edit()
        reset_candidate(self.state, self.state.selected_slot)
        self._baseline = self.document.to_dict()
        title = self.document.by_role("main_title")
        self.state.selected_layers[self.state.selected_slot] = title.id if title else None
        self._dirty = True
        self._refresh_all()
        self.message.set(f"{self.state.selected_slot} 후보를 생성 기본값으로 초기화")

    # ------------------------------------------------------------------ reference thumbnail (P8)
    def open_reference(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.webp")], title="참고 썸네일")
        if path:
            self.load_reference(path)

    def load_reference(self, path: str) -> None:
        image = read_image(path)
        if image is None:
            return
        self.reference_bgr = image
        self.state.reference_image = str(path)
        thumb = cv2.resize(image, (256, max(1, round(image.shape[0] * 256 / image.shape[1]))), interpolation=cv2.INTER_AREA)
        self._reference_photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(thumb, cv2.COLOR_BGR2RGB)))
        self.reference_label.configure(image=self._reference_photo, text="")

    def extract_reference_palette(self) -> tuple[str, str, str] | None:
        if self.reference_bgr is None:
            messagebox.showinfo("참고 썸네일", "먼저 참고 이미지를 여세요.")
            return None
        analysis = analyze_text_region(self.reference_bgr, (0, 0, self.reference_bgr.shape[1], self.reference_bgr.shape[0]))
        from typography.background_fit import relative_luminance
        import colorsys
        colors = list(analysis.palette)
        light = max(colors, key=relative_luminance)
        dark = min(colors, key=relative_luminance)
        def saturation(value):
            r, g, b = (int(value[i:i + 2], 16) / 255 for i in (1, 3, 5))
            return colorsys.rgb_to_hls(r, g, b)[2]
        accent = max(colors, key=saturation)
        self.reference_palette = (light, dark, accent)
        self._build_palettes()
        self.message.set("참고 이미지 색상만 추출 → 팔레트에 추가 (디자인은 복제하지 않음)")
        return self.reference_palette

    def make_reference_guide(self) -> None:
        if self.reference_bgr is None:
            messagebox.showinfo("참고 썸네일", "먼저 참고 이미지를 여세요.")
            return
        self.show_reference.set(True)
        self._display()
        self.message.set("참고 이미지를 반투명 가이드로 표시합니다 (편집 화면 전용 · 내보내기에는 포함되지 않음)")

    # ------------------------------------------------------------------ Image Bridge (P9)
    def _set_bridge_buttons(self, enabled: bool) -> None:
        for button in self._bridge_buttons:
            button.configure(state="normal" if enabled else "disabled")

    def bridge_generate(self) -> None:
        self._bridge_launch("generate")

    def bridge_edit(self) -> None:
        self._bridge_launch("edit")

    def _bridge_launch(self, action: str) -> None:
        folder = self.state.bridge.get("folder")
        if not folder:
            messagebox.showinfo("Image Bridge", "먼저 이미지 프로젝트 폴더를 여세요.")
            return
        if self._bridge_running:
            return
        title = self.document.by_role("main_title") if self.document else None
        options = {"channel": self.state.channel, "story_type": self.state.texts.get("story", ""),
                   "title": title.text if title else self.state.texts.get("title", ""),
                   "subtitle": self.state.texts.get("subtitle", ""), "episode": self.state.texts.get("episode", ""),
                   "preferred_typography": self.state.style}
        prompt, instruction = self.image_prompt.get().strip(), self.image_edit_instruction.get().strip()
        self._bridge_running = True
        self._set_bridge_buttons(False)
        self.bridge_status.set(f"이미지 프로그램 {action} 실행 중… (GUI는 계속 사용 가능)")

        def work():
            try:
                result = launch_generate(folder, prompt, options) if action == "generate" else \
                    launch_edit(folder, instruction, options)
            except Exception as exc:
                result = LaunchResult(False, f"Image Bridge failed safely: {exc}", action=action, project_dir=Path(folder))
            self._bridge_queue.put(("bridge", (action, result)))
        threading.Thread(target=work, name=f"pro-bridge-{action}", daemon=True).start()

    def _bridge_finished(self, action: str, result: LaunchResult) -> None:
        self._bridge_running = False
        self._set_bridge_buttons(True)
        if not result.launched:
            self.bridge_status.set(f"{action} 실패 · 기존 배경/레이어 유지: {result.message[:120]}")
            messagebox.showerror("Image Bridge", result.message)
            return
        self.bridge_refresh(after_action=action)

    def bridge_refresh(self, after_action: str | None = None, choice: str | None = None) -> dict | None:
        """Re-read canvas + sidecars and replace only the background layers."""
        folder = self.state.bridge.get("folder")
        if not folder or not self.state.documents:
            messagebox.showinfo("Image Bridge", "먼저 이미지 프로젝트 폴더를 여세요.")
            return None
        self._flush_edit()
        project = load_image_project(folder)
        if project.source_image is None:
            messagebox.showwarning("Image Bridge", "새 캔버스를 찾지 못했습니다. 기존 배경을 유지합니다.")
            return None
        points = project.subject_points or {}
        generated = create_candidate_images(str(project.source_image), self.state.channel, TEMPLATE_MODE, "자동",
                                            points.get("protagonist"), points.get("counterpart"),
                                            self.state.texts.get("story", "자동"), self.state.texts.get("episode", ""),
                                            "", "", self.state.style, render_text=False)
        backgrounds, subjects, zones = {}, {}, {}
        for slot, candidate in zip(SLOTS, generated):
            backgrounds[slot] = candidate.image
            subjects[slot] = (candidate.typography or {}).get("subject_boxes", ())
            zones[slot] = (candidate.typography or {}).get("safe_zones", ())
        collisions = replace_backgrounds(self.state, backgrounds, subjects, zones)
        self.state.source_background = str(project.source_image)
        if project.palette:
            self.state.palette = dict(project.palette)
        self.state.bridge.update({"status": dict(project.status), "warnings": list(project.warnings),
                                  "last_action": after_action or "refresh", "composition": project.composition})
        self._baseline = self.document.to_dict()
        self._dirty = True
        total = sum(len(items) for items in collisions.values())
        if total:
            choice = choice or self._ask_relayout(collisions)
            if choice == "relayout":
                for slot, document in self.state.documents.items():
                    if collisions.get(slot):
                        self.state.histories[slot].push(document.to_dict())
                        relayout_to_safe(document)
                self._baseline = self.document.to_dict()
        self.bridge_status.set(self._bridge_summary() + (f" · 충돌 {total}건" if total else " · 충돌 없음"))
        self._build_palettes()
        self._refresh_all()
        self.message.set("새 배경 적용 · 텍스트/배지 레이어 유지" + (" · 새 안전영역에 맞춰 재배치" if choice == "relayout" else ""))
        return collisions

    def _ask_relayout(self, collisions) -> str:
        dialog = tk.Toplevel(self)
        dialog.title("새 배경과 텍스트 충돌")
        dialog.transient(self.winfo_toplevel()); dialog.grab_set()
        lines = [f"{slot}: {item['name']} ↔ {'얼굴/피사체' if item['kind'] == 'subject' else '안전영역'} {item['ratio']:.0%}"
                 for slot, items in collisions.items() for item in items]
        ttk.Label(dialog, text="새 배경에서 제목/라벨이 얼굴이나 안전영역과 겹칩니다.\n" + "\n".join(lines[:8]),
                  justify="left").pack(padx=14, pady=10)
        choice = {"value": "keep"}
        buttons = ttk.Frame(dialog); buttons.pack(pady=8)
        ttk.Button(buttons, text="현재 배치 유지", command=lambda: (choice.update(value="keep"), dialog.destroy())).pack(side="left", padx=4)
        ttk.Button(buttons, text="새 안전영역에 맞춰 재배치",
                   command=lambda: (choice.update(value="relayout"), dialog.destroy())).pack(side="left", padx=4)
        self.wait_window(dialog)
        return choice["value"]

    # ------------------------------------------------------------------ diagnostics
    def timing_summary(self) -> dict:
        def stats(values):
            if not values:
                return {"count": 0}
            ordered = sorted(values)
            return {"count": len(values), "median_ms": round(ordered[len(ordered) // 2], 1),
                    "p90_ms": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.9))], 1),
                    "max_ms": round(ordered[-1], 1)}
        return {key: stats(values) for key, values in self.timings.items()}


def _channel_name(value, fallback: str) -> str:
    value = str(value or "").strip().casefold().replace("_", " ").replace("-", " ")
    if value in ("old pop lounge", "oldpoplounge", "old pop"):
        return "OLD POP LOUNGE"
    if value in ("tokyo chill", "tokyo"):
        return "Tokyo Chill"
    return fallback
