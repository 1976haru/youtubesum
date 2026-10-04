from __future__ import annotations

import logging
import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk
import cv2
import numpy as np
from editor.ui import ProEditor
from motion_engine import PRESETS, render
from typography_engine import TYPOGRAPHY_PRESETS, preset_names
from typography.linebreak_engine import choose_line_break
from typography.storage_assets import load_image_storage_assets
from image_bridge import ImageProject, LaunchResult, launch_edit, launch_generate, load_image_project
from typography.text_style import get_preset, PRESETS_BY_CHANNEL
from typography.text_renderer_skia import render_title
from typography.thumbnail_layouts import choose_layout
from layout_engine import render_candidate_text
from thumbnail_engine import (APP_VERSION, COMPLETED_MODE, RAW_MODE, TEMPLATE_MODE,
                              candidate_similarities, candidates_too_similar,
                              create_candidate_images, generate_candidates, record_test,
                              save_candidates, summarize)


def app_home():
    preferred = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    try:
        (preferred / "logs").mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        fallback = Path.home() / "YouTubeDynamicThumbnailStudio"
        (fallback / "logs").mkdir(parents=True, exist_ok=True)
        return fallback


APP_HOME = app_home()
logging.basicConfig(filename=APP_HOME / "logs" / "error.log", level=logging.ERROR, encoding="utf-8", format="%(asctime)s %(levelname)s\n%(message)s")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"YouTube Dynamic Thumbnail Studio v{APP_VERSION}")
        self.geometry("1600x1000"); self.minsize(1320, 860)
        self.src = tk.StringVar(); self.channel = tk.StringVar(value="Tokyo Chill")
        self.source_mode = tk.StringVar(value=TEMPLATE_MODE)
        self.focus_mode = tk.StringVar(value="자동")
        self.story_type = tk.StringVar(value="자동")
        self.template_episode = tk.StringVar(value="EP.001")
        self.template_title = tk.StringVar(value="思い出の夜")
        self.template_subtitle = tk.StringVar(value="A quiet story in the city")
        self.typography_style = tk.StringVar(value="Japanese Impact")
        self.auto_two_line = tk.BooleanVar(value=True)
        self.emphasize_keyword = tk.BooleanVar(value=True)
        self.keyword = tk.StringVar()
        self.title_size = tk.IntVar(value=108)
        self.outline_thickness = tk.DoubleVar(value=10.0)
        self.glow_intensity = tk.DoubleVar(value=1.0)
        self.shadow_intensity = tk.DoubleVar(value=0.9)
        self.manual_breaks = tk.StringVar()
        self.line_break_preview = tk.StringVar(value="줄바꿈 미리보기: 제목을 입력하세요")
        self.safe_zone_overlay = tk.BooleanVar(value=False)
        self.selected_preview_var = tk.StringVar(value="A")
        self.reference_src = tk.StringVar()
        self.preset = tk.StringVar(value="Tokyo Chill - Rain"); self.duration = tk.IntVar(value=8)
        self.intensity = tk.DoubleVar(value=1.0); self.status = tk.StringVar(value="이미지를 선택하세요.")
        self.episode = tk.StringVar(value="EP001"); self.a = tk.StringVar(); self.b = tk.StringVar(); self.c = tk.StringVar()
        self.winner = tk.StringVar(value="B"); self.db = APP_HOME / "youtube_test_history.csv"
        self.candidates = []; self.preview_refs = []; self.last_output_dir = None
        self.protagonist = None; self.counterpart = None; self.focus_source = None
        self.composer_code = tk.StringVar(value="A_PERSON")
        self.composer_role = tk.StringVar(value="main_title")
        self.composer_title_size = tk.IntVar(value=108)
        self.composer_outline = tk.DoubleVar(value=10.0)
        self.composer_shadow = tk.DoubleVar(value=0.9)
        self.composer_glow = tk.DoubleVar(value=1.0)
        self.composer_line_spacing = tk.DoubleVar(value=1.17)
        self.composer_letter_spacing = tk.DoubleVar(value=0.0)
        self.composer_alignment = tk.StringVar(value="left")
        self.composer_anchor = tk.StringVar(value="lower-left")
        self.composer_fill = tk.StringVar(value="#FFFFFF")
        self.composer_stroke = tk.StringVar(value="#17090C")
        self.composer_highlight = tk.StringVar(value="#FFE23A")
        self.composer_soft_plate = tk.BooleanVar(value=True)
        self.composer_gradient = tk.BooleanVar(value=True)
        self.composer_safe_overlay = tk.BooleanVar(value=False)
        self.composer_style = tk.StringVar(value="Japanese Impact")
        self.composer_channel = tk.StringVar(value="Tokyo Chill")
        self.composer_title = tk.StringVar(value=self.template_title.get())
        self.composer_subtitle = tk.StringVar(value=self.template_subtitle.get())
        self.composer_episode = tk.StringVar(value=self.template_episode.get())
        self.composer_story = tk.StringVar(value=self.story_type.get())
        self.composer_positions = {code: {} for code in ("A_PERSON", "B_EMOTION", "C_STORY")}
        self.composer_states = {}
        self.composer_bases = {}
        self.composer_subjects = {}
        self.composer_safe_zones = {}
        self.composer_result = None
        self.composer_metadata = {}
        self.composer_image_refs = []
        self.composer_style_refs = []
        self.composer_history = {code: [] for code in ("A_PERSON", "B_EMOTION", "C_STORY")}
        self.composer_redo = {code: [] for code in ("A_PERSON", "B_EMOTION", "C_STORY")}
        self._composer_render_job = None
        self._composer_history_job = None
        self._composer_pending_before = None
        self._composer_loading_state = False
        self._composer_drag = None
        self._composer_cards_loaded = False
        self.image_project: ImageProject | None = None
        self.image_project_path = tk.StringVar(value="No image project open")
        self.image_bridge_status = tk.StringVar(value="clean canvas — · safe zones — · subject boxes — · palette — · manifest —")
        from image_program import resolve_mode, resolve_program
        configured_image_exe = resolve_program()[0]
        bridge_mode = resolve_mode()
        project_root = os.environ.get("IMAGE_PROJECT_ROOT", "(current directory)")
        executable_ready = bool(configured_image_exe and Path(configured_image_exe).is_file())
        connection = f"Image program {'ready' if executable_ready else 'not configured'}: {configured_image_exe or '이미지 프로그램 설정… 에서 선택'}"
        self.image_run_summary = tk.StringVar(value=f"{connection} · bridge mode: {bridge_mode} · project root: {project_root}")
        self.image_prompt = tk.StringVar()
        self.image_edit_instruction = tk.StringVar()
        self.image_bridge_queue = queue.Queue()
        self._image_action_running = False
        self._image_action_buttons = []
        self._image_bridge_palette = {}
        self._image_bridge_position_baselines = {}
        header = ttk.Frame(self); header.pack(fill="x", padx=14, pady=(6, 0))
        ttk.Label(header, text="YOUTUBE DYNAMIC THUMBNAIL STUDIO", font=("Segoe UI", 15, "bold")).pack(side="left")
        ttk.Label(header, text=f"  v{APP_VERSION} · Pro Editor · 3후보 + Motion Intro · "
                  "Motion uses FFmpeg · LGPLv3 · ydts_ffmpeg 교체 가능", foreground="#555").pack(side="left")
        ttk.Button(header, text="오픈소스 라이선스", command=self.show_licenses).pack(side="right")
        notebook = ttk.Notebook(self); notebook.pack(fill="both", expand=True, padx=8, pady=6)
        self.notebook = notebook
        self._tab_pro_editor(notebook)
        self._tab_candidates(notebook); self._tab_live_composer(notebook); self._tab_motion(notebook); self._tab_history(notebook)
        notebook.select(self.pro_editor)
        ttk.Label(self, textvariable=self.status, wraplength=1100).pack(pady=(0, 8))
        self.src.trace_add("write", self._source_changed)
        self.source_mode.trace_add("write", lambda *_: self._update_mode_guard())
        self.channel.trace_add("write", lambda *_: self._update_typography_styles())
        self.focus_mode.trace_add("write", lambda *_: self._update_focus_state())
        for variable in (self.src, self.source_mode, self.focus_mode, self.channel, self.story_type, self.template_episode,
                         self.template_title, self.template_subtitle, self.typography_style, self.auto_two_line,
                         self.emphasize_keyword, self.keyword, self.title_size, self.outline_thickness,
                         self.glow_intensity, self.shadow_intensity, self.manual_breaks, self.safe_zone_overlay):
            variable.trace_add("write", self._invalidate_candidates)
        self.template_title.trace_add("write", lambda *_: self._update_line_break_preview())
        self.manual_breaks.trace_add("write", lambda *_: self._update_line_break_preview())
        self.title_size.trace_add("write", lambda *_: self._update_line_break_preview())
        self.auto_two_line.trace_add("write", lambda *_: self._update_line_break_preview())
        self._update_mode_guard()

    def report_callback_exception(self, exc, value, tb):
        logging.error("".join(traceback.format_exception(exc, value, tb)))
        messagebox.showerror("오류", f"작업 중 오류가 발생했습니다.\n\n{value}\n\n로그: {APP_HOME / 'logs' / 'error.log'}")

    def show_licenses(self):
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        folder = base / "third_party"
        text = []
        for name in ("THIRD_PARTY_NOTICES.txt", "LICENSE.txt", "COPYING.GPLv3"):
            path = folder / name
            if path.is_file():
                text.append(f"===== {name} =====\n{path.read_text(encoding='utf-8', errors='replace')}")
        window = tk.Toplevel(self); window.title("오픈소스 라이선스")
        box = tk.Text(window, wrap="word", width=100, height=32)
        scroll = ttk.Scrollbar(window, orient="vertical", command=box.yview); box.configure(yscrollcommand=scroll.set)
        box.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        box.insert("1.0", "\n\n".join(text) if text else "라이선스 고지 파일을 찾지 못했습니다.")
        box.configure(state="disabled")

    def _handle(self, action):
        try: return action()
        except Exception:
            detail = traceback.format_exc(); logging.error(detail)
            messagebox.showerror("오류", f"작업을 완료하지 못했습니다.\n\n{detail.splitlines()[-1]}\n\n로그: {APP_HOME / 'logs' / 'error.log'}")
            self.status.set("실패했습니다. error.log를 확인하세요.")

    def source_row(self, parent):
        frame = ttk.Frame(parent); frame.pack(fill="x", padx=16, pady=8)
        ttk.Entry(frame, textvariable=self.src).pack(side="left", fill="x", expand=True)
        ttk.Button(frame, text="이미지 선택", command=self.pick).pack(side="left", padx=8)

    def pick(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.jpeg *.png *.webp")])
        if path:
            self.src.set(path); self.status.set("준비 완료: " + Path(path).name)

    def _source_changed(self, *_):
        if self.focus_source and self.src.get() != self.focus_source:
            self.protagonist = self.counterpart = self.focus_source = None
            self._update_focus_state()
        if self.src.get():
            try:
                assets = load_image_storage_assets(self.src.get())
                if assets.reference_thumbnail:
                    self.reference_src.set(str(assets.reference_thumbnail))
            except Exception:
                pass

    def _update_line_break_preview(self):
        text = " ".join(self.template_title.get().split())
        if not text:
            self.line_break_preview.set("줄바꿈 미리보기: 제목을 입력하세요")
            return
        size = max(64, int(self.title_size.get()))
        width_limit = 780 / max(1, size)
        def width(line):
            return sum(1.0 if ord(char) > 0x2E7F else 0.56 for char in line)
        manual = self.manual_breaks.get().replace("|", "\n")
        choice = choose_line_break(text, width, width_limit, 3 if self.auto_two_line.get() else 1, manual)
        self.line_break_preview.set("줄바꿈 미리보기: " + " / ".join(choice.lines))

    def show_selected_preview(self, index: int):
        if not hasattr(self, "large_preview_label") or not self.candidates or index >= len(self.candidates):
            return
        image = Image.fromarray(self.candidates[index].image[:, :, ::-1]).resize(
            (340, 191), Image.Resampling.LANCZOS)
        self._large_preview_ref = ImageTk.PhotoImage(image)
        self.large_preview_label.configure(image=self._large_preview_ref, text="")

    def _invalidate_candidates(self, *_):
        self.candidates = []
        if hasattr(self, "large_preview_label"):
            self._large_preview_ref = None
            self.large_preview_label.configure(image="", text="A/B/C 카드 이미지를 클릭하면 표시됩니다")
        if hasattr(self, "preview_labels"):
            self.preview_refs.clear()
            for image_label, note_label in zip(self.preview_labels, self.note_labels):
                image_label.configure(image="", text="미리보기 대기")
                note_label.configure(text="")
        if hasattr(self, "save_all_button"):
            self.save_all_button.state(["disabled"])
        if hasattr(self, "diversity_state"):
            self.diversity_state.set("입력 변경됨 · 새 A/B/C 미리보기를 생성하세요")

    def _update_mode_guard(self):
        if not hasattr(self, "mode_guard"):
            return
        mode = self.source_mode.get()
        if mode == COMPLETED_MODE:
            self.mode_guard.set("완성 썸네일 보호 · 크롭 금지 · 강한 A/B/C 차이는 제한됩니다")
        elif mode == TEMPLATE_MODE:
            self.mode_guard.set("권장 모드 · 텍스트 없는 원본을 재구도하고 입력한 글자를 새 레이어로 렌더링합니다")
        else:
            self.mode_guard.set("원본 이미지 모드 · 기본 구도 변경")
        self._update_typography_controls()

    def _update_typography_styles(self):
        names = preset_names(self.channel.get())
        if hasattr(self, "typography_combo"):
            self.typography_combo.configure(values=names)
        if self.typography_style.get() not in names and names:
            self.typography_style.set(names[0])
        self._invalidate_candidates()

    def _update_typography_controls(self):
        if not hasattr(self, "typography_controls"):
            return
        state = "normal" if self.source_mode.get() == TEMPLATE_MODE else "disabled"
        for control in self.typography_controls:
            control.configure(state=state)

    def _update_focus_state(self):
        main = "수동 지정" if self.protagonist is not None else self.focus_mode.get()
        other = "수동 지정" if self.counterpart is not None else "미지정"
        if hasattr(self, "focus_state"):
            self.focus_state.set(f"주인공: {main} · 상대: {other}")

    def clear_points(self):
        self.protagonist = self.counterpart = self.focus_source = None
        self._update_focus_state()
        self.status.set("인물 지정을 해제했습니다.")

    def select_point(self, role):
        source = self.src.get()
        if not source:
            return messagebox.showwarning("확인", "먼저 이미지를 선택하세요.")
        try:
            raw = Image.open(source).convert("RGB")
        except Exception as exc:
            logging.exception("수동 인물 선택용 이미지 읽기 실패")
            return messagebox.showerror("오류", f"이미지를 열 수 없습니다.\n{exc}")
        dialog = tk.Toplevel(self)
        dialog.title("주인공 직접 지정" if role == "protagonist" else "상대 인물 지정")
        dialog.transient(self); dialog.grab_set()
        ttk.Label(dialog, text="원본 전체에서 얼굴 또는 몸의 중심을 클릭하세요. 이미 지정한 점은 표시됩니다.").pack(padx=12, pady=8)
        scale = min(1000 / raw.width, 620 / raw.height)
        view_w, view_h = max(1, round(raw.width * scale)), max(1, round(raw.height * scale))
        photo = ImageTk.PhotoImage(raw.resize((view_w, view_h), Image.Resampling.LANCZOS))
        canvas = tk.Canvas(dialog, width=view_w, height=view_h, highlightthickness=0)
        canvas.pack(padx=10, pady=4); canvas.create_image(0, 0, anchor="nw", image=photo); canvas.image = photo
        self.selection_dialog = dialog
        self.selection_canvas = canvas
        marks = {}
        for key, point, color, label in (("protagonist", self.protagonist, "#ff3030", "주인공"), ("counterpart", self.counterpart, "#20a0ff", "상대")):
            if point is not None:
                x, y = point[0] * view_w, point[1] * view_h
                oval = canvas.create_oval(x-10,y-10,x+10,y+10,outline=color,width=3)
                text = canvas.create_text(x+14,y-12,text=label,anchor="w",fill=color,font=("Segoe UI",10,"bold"))
                marks[key] = (oval, text)
        selection = {"point": None}
        color = "#ff3030" if role == "protagonist" else "#20a0ff"
        def click(event):
            x = max(0, min(view_w-1, event.x)); y = max(0, min(view_h-1, event.y))
            selection["point"] = (x / view_w, y / view_h)
            if role in marks:
                canvas.delete(*marks[role])
            oval = canvas.create_oval(x-10,y-10,x+10,y+10,outline=color,width=3)
            text = canvas.create_text(x+14,y-12,text="주인공" if role == "protagonist" else "상대",anchor="w",fill=color,font=("Segoe UI",10,"bold"))
            marks[role] = (oval, text)
        canvas.bind("<Button-1>", click)
        buttons = ttk.Frame(dialog); buttons.pack(pady=8)
        self.selection_apply_button = ttk.Button(buttons, text="선택 적용", command=lambda: apply())
        self.selection_apply_button.pack(side="left", padx=5)
        ttk.Button(buttons, text="취소", command=dialog.destroy).pack(side="left", padx=5)
        def apply():
            if selection["point"] is None:
                messagebox.showwarning("확인", "원본 이미지에서 위치를 클릭하세요.", parent=dialog)
                return
            if role == "protagonist": self.protagonist = selection["point"]
            else: self.counterpart = selection["point"]
            self.focus_source = source; self._update_focus_state(); self._invalidate_candidates(); dialog.destroy()

    def _tab_pro_editor(self, notebook):
        self.pro_editor = ProEditor(notebook, settings_path=APP_HOME / "editor_settings.json", status=self.status)
        notebook.add(self.pro_editor, text="★ Pro Editor")

    def _tab_candidates(self, notebook):
        tab = ttk.Frame(notebook); notebook.add(tab, text="① 3후보 미리보기"); self.source_row(tab)
        row = ttk.Frame(tab); row.pack(fill="x", padx=16, pady=(4, 2))
        ttk.Label(row, text="채널", width=8).pack(side="left")
        ttk.Combobox(row, textvariable=self.channel, values=["Tokyo Chill", "OLD POP LOUNGE"], state="readonly", width=18).pack(side="left")
        ttk.Label(row, text="입력 유형", width=9).pack(side="left", padx=(12, 0))
        ttk.Combobox(row, textvariable=self.source_mode, values=[COMPLETED_MODE, TEMPLATE_MODE, RAW_MODE], state="readonly", width=34).pack(side="left")
        ttk.Label(row, text="주인공", width=7).pack(side="left", padx=(12, 0))
        ttk.Combobox(row, textvariable=self.focus_mode, values=["자동", "왼쪽 인물", "오른쪽 인물", "두 사람"], state="readonly", width=12).pack(side="left")
        ttk.Label(row, text="이야기", width=7).pack(side="left", padx=(8, 0))
        ttk.Combobox(row, textvariable=self.story_type, values=["자동", "남자 이야기", "여자 이야기", "두 사람 이야기"], state="readonly", width=13).pack(side="left")
        type_row = ttk.Frame(tab); type_row.pack(fill="x", padx=16, pady=(2, 2))
        ttk.Label(type_row, text="타이포그래피", width=12).pack(side="left")
        self.typography_combo = ttk.Combobox(type_row, textvariable=self.typography_style,
            values=preset_names(self.channel.get()), state="readonly", width=24)
        self.typography_combo.pack(side="left", padx=(0, 10))
        ttk.Label(type_row, text="제목 크기").pack(side="left")
        self.title_size_combo = ttk.Combobox(type_row, values=["슬라이더 조정"], state="disabled", width=12)
        self.title_size_combo.pack_forget()
        self.two_line_check = ttk.Checkbutton(type_row, text="자동 2줄 분할", variable=self.auto_two_line)
        self.two_line_check.pack(side="left", padx=4)
        self.keyword_check = ttk.Checkbutton(type_row, text="핵심어 강조", variable=self.emphasize_keyword)
        self.keyword_check.pack(side="left", padx=4)
        ttk.Label(type_row, text="핵심어").pack(side="left", padx=(6, 2))
        self.keyword_entry = ttk.Entry(type_row, textvariable=self.keyword, width=18)
        self.keyword_entry.pack(side="left")
        self.typography_controls = [self.typography_combo, self.two_line_check, self.keyword_check, self.keyword_entry]
        control_row = ttk.Frame(tab); control_row.pack(fill="x", padx=16, pady=(0, 2))
        ttk.Label(control_row, text="Title size").pack(side="left")
        self.title_size_scale = ttk.Scale(control_row, from_=64, to=150, variable=self.title_size,
            orient="horizontal", length=150); self.title_size_scale.pack(side="left", padx=5)
        ttk.Label(control_row, textvariable=self.title_size).pack(side="left", padx=(0, 12))
        ttk.Label(control_row, text="Outline").pack(side="left")
        self.outline_scale = ttk.Scale(control_row, from_=0, to=22, variable=self.outline_thickness,
            orient="horizontal", length=135); self.outline_scale.pack(side="left", padx=5)
        ttk.Label(control_row, text="Glow").pack(side="left")
        self.glow_scale = ttk.Scale(control_row, from_=0, to=1.5, variable=self.glow_intensity,
            orient="horizontal", length=110); self.glow_scale.pack(side="left", padx=5)
        ttk.Label(control_row, text="Shadow").pack(side="left")
        self.shadow_scale = ttk.Scale(control_row, from_=0, to=1.5, variable=self.shadow_intensity,
            orient="horizontal", length=110); self.shadow_scale.pack(side="left", padx=5)
        ttk.Label(control_row, text="줄바꿈 수동 수정(|)").pack(side="left", padx=(10, 2))
        self.manual_breaks_entry = ttk.Entry(control_row, textvariable=self.manual_breaks, width=27)
        self.manual_breaks_entry.pack(side="left")
        self.safe_zone_toggle = ttk.Checkbutton(control_row, text="안전영역 표시", variable=self.safe_zone_overlay)
        self.safe_zone_toggle.pack(side="left", padx=8)
        self.typography_controls += [self.title_size_scale, self.outline_scale, self.glow_scale,
            self.shadow_scale, self.manual_breaks_entry, self.safe_zone_toggle]
        ttk.Label(tab, textvariable=self.line_break_preview, foreground="#335577").pack(anchor="w", padx=22)
        text_row = ttk.Frame(tab); text_row.pack(fill="x", padx=16, pady=(2, 4))
        for label, variable, width in (("EP", self.template_episode, 10), ("메인 제목", self.template_title, 32), ("영문/부제", self.template_subtitle, 34)):
            ttk.Label(text_row, text=label).pack(side="left", padx=(0, 4))
            ttk.Entry(text_row, textvariable=variable, width=width).pack(side="left", padx=(0, 10))
        ttk.Button(text_row, text="참고 완성 썸네일", command=self.pick_reference).pack(side="left")
        actions = ttk.Frame(tab); actions.pack(fill="x", padx=16, pady=(2, 4))
        ttk.Button(actions, text="주인공 직접 지정", command=lambda: self.select_point("protagonist")).pack(side="left", padx=(0, 4))
        ttk.Button(actions, text="상대 인물 지정", command=lambda: self.select_point("counterpart")).pack(side="left", padx=4)
        ttk.Button(actions, text="지정 해제", command=self.clear_points).pack(side="left", padx=4)
        ttk.Button(actions, text="A/B/C 미리보기 생성", command=self.make_previews).pack(side="left", padx=8)
        ttk.Button(actions, text="결과 폴더 열기", command=self.open_output_folder).pack(side="right")
        self.mode_guard = tk.StringVar()
        self.focus_state = tk.StringVar(value="주인공: 자동 감지 · 상대: 미지정")
        self.guard_label = ttk.Label(tab, textvariable=self.mode_guard, foreground="#a03020", font=("Segoe UI", 10, "bold"))
        self.guard_label.pack(anchor="w", padx=18, pady=(0, 2))
        ttk.Label(tab, textvariable=self.focus_state, foreground="#333").pack(anchor="w", padx=18, pady=(0, 2))
        self.diversity_state = tk.StringVar(value="A/B/C 차이 점수: 미리보기 후 표시")
        ttk.Label(tab, textvariable=self.diversity_state, foreground="#174c8c", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=18, pady=(0, 2))
        ttk.Label(tab, text="완성 썸네일은 한 장으로 합쳐진 이미지라 글자/로고를 보존하면 구도 차이가 제한됩니다. 강한 후보 비교에는 ‘원본 이미지 + 템플릿’을 권장합니다.", wraplength=1160, foreground="#704020").pack(anchor="w", padx=18, pady=(0, 3))
        cards = ttk.Frame(tab); cards.pack(fill="both", expand=True, padx=10, pady=6)
        self.preview_labels, self.note_labels = [], []
        for index, title in enumerate(("A · PERSON", "B · EMOTION / MEMORY", "C · STORY / SCENERY")):
            card = ttk.LabelFrame(cards, text=title); card.grid(row=0, column=index, sticky="nsew", padx=5)
            image_label = ttk.Label(card, text="미리보기 대기", anchor="center"); image_label.pack(fill="both", expand=True, padx=5, pady=5)
            note = ttk.Label(card, text="", wraplength=330, justify="center"); note.pack(padx=5, pady=3)
            ttk.Button(card, text="이 후보만 저장", command=lambda i=index: self.save_one(i)).pack(pady=(2, 8))
            image_label.bind("<Button-1>", lambda event, i=index: self.show_selected_preview(i))
            self.preview_labels.append(image_label); self.note_labels.append(note); cards.columnconfigure(index, weight=1)
        cards.rowconfigure(0, weight=1)
        detail = ttk.LabelFrame(tab, text="340px 미리보기")
        detail.pack(fill="x", padx=18, pady=3)
        self.large_preview_label = ttk.Label(detail, text="A/B/C 카드 이미지를 클릭하면 표시됩니다", anchor="center")
        self.large_preview_label.pack(pady=3)
        self.selected_preview_var.trace_add("write", lambda *_: self.show_selected_preview(["A", "B", "C"].index(self.selected_preview_var.get())))
        self.save_all_button = ttk.Button(tab, text="3개 모두 저장", command=self.save_all, state="disabled")
        self.save_all_button.pack(pady=8, ipadx=30, ipady=5)

    def _tab_live_composer(self, notebook):
        tab = ttk.Frame(notebook); notebook.add(tab, text="Live Composer")
        toolbar = ttk.Frame(tab); toolbar.pack(fill="x", padx=10, pady=5)
        self.image_project_button = ttk.Button(toolbar, text="프로젝트 폴더 열기", command=self.open_image_project)
        self.image_project_button.pack(side="left")
        ttk.Button(toolbar, text="A/B/C 배경 생성", command=self.build_composer_backgrounds).pack(side="left", padx=5)
        self.image_generate_button = ttk.Button(toolbar, text="배경 생성", command=self.launch_image_generate)
        self.image_generate_button.pack(side="left", padx=(18, 3))
        self.image_edit_button = ttk.Button(toolbar, text="배경 편집", command=self.launch_image_edit)
        self.image_edit_button.pack(side="left", padx=3)
        self.image_refresh_button = ttk.Button(toolbar, text="image에서 새로고침", command=self.refresh_image_project)
        self.image_refresh_button.pack(side="left", padx=3)
        self._image_action_buttons = [self.image_project_button, self.image_generate_button,
                                      self.image_edit_button, self.image_refresh_button]
        ttk.Label(tab, textvariable=self.image_project_path, anchor="w", foreground="#34475b").pack(fill="x", padx=12)
        ttk.Label(tab, textvariable=self.image_bridge_status, anchor="w", foreground="#555").pack(fill="x", padx=12, pady=(0, 3))
        text_fields = ttk.Frame(tab); text_fields.pack(fill="x", padx=10, pady=(0, 4))
        for label, variable, width in (("Main title", self.composer_title, 25), ("Subtitle", self.composer_subtitle, 26),
                                       ("EP", self.composer_episode, 9), ("Story label", self.composer_story, 16)):
            ttk.Label(text_fields, text=label).pack(side="left", padx=(2, 3))
            ttk.Entry(text_fields, textvariable=variable, width=width).pack(side="left", padx=(0, 8))
        bridge_fields = ttk.Frame(tab); bridge_fields.pack(fill="x", padx=10, pady=(0, 4))
        ttk.Label(bridge_fields, text="Generate prompt").pack(side="left", padx=(2, 3))
        ttk.Entry(bridge_fields, textvariable=self.image_prompt, width=40).pack(side="left", padx=(0, 9))
        ttk.Label(bridge_fields, text="Edit instruction").pack(side="left", padx=(2, 3))
        ttk.Entry(bridge_fields, textvariable=self.image_edit_instruction, width=48).pack(side="left", fill="x", expand=True)
        ttk.Label(tab, textvariable=self.image_run_summary, anchor="w", foreground="#3e5c77", wraplength=1120).pack(fill="x", padx=12, pady=(0, 4))

        body = ttk.Frame(tab); body.pack(fill="both", expand=True, padx=10, pady=4)
        preview = ttk.Frame(body); preview.pack(side="left", fill="both", expand=True, padx=(0, 10))
        selection = ttk.Frame(preview); selection.pack(fill="x", pady=(0, 5))
        ttk.Label(selection, text="후보").pack(side="left")
        for code, label in (("A_PERSON", "A · PERSON"), ("B_EMOTION", "B · EMOTION"), ("C_STORY", "C · STORY")):
            ttk.Radiobutton(selection, text=label, value=code, variable=self.composer_code,
                            command=self._composer_candidate_changed).pack(side="left", padx=5)
        ttk.Label(selection, text="편집 블록").pack(side="left", padx=(16, 4))
        self.composer_role_combo = ttk.Combobox(selection, state="readonly", width=18,
            textvariable=self.composer_role, values=("channel_label", "story_label", "episode_badge", "main_title", "subtitle"))
        self.composer_role_combo.pack(side="left")
        self.composer_role_combo.bind("<<ComboboxSelected>>", lambda _event: self._draw_composer_canvas())
        ttk.Button(selection, text="Undo", command=self.composer_undo).pack(side="right", padx=2)
        ttk.Button(selection, text="Redo", command=self.composer_redo_action).pack(side="right", padx=2)

        self.composer_canvas_width, self.composer_canvas_height = 832, 468
        self.composer_canvas = tk.Canvas(preview, width=self.composer_canvas_width,
            height=self.composer_canvas_height, background="#1b1d22", highlightthickness=1,
            highlightbackground="#777")
        self.composer_canvas.pack(anchor="center", fill="none", expand=False)
        self.composer_canvas.create_text(416, 234, text="프로젝트 이미지를 열거나 A/B/C 배경을 생성하세요",
            fill="white", font=("Segoe UI", 15), tags=("placeholder",))
        self.composer_canvas.bind("<ButtonPress-1>", self._composer_drag_start)
        self.composer_canvas.bind("<B1-Motion>", self._composer_drag_motion)
        self.composer_canvas.bind("<ButtonRelease-1>", self._composer_drag_end)
        self.composer_info = tk.StringVar(value="1280 × 720 출력 · 변경 내용은 150ms debounce로 반영됩니다")
        ttk.Label(preview, textvariable=self.composer_info, anchor="w").pack(fill="x", pady=3)
        mini = ttk.Frame(preview); mini.pack(fill="x", pady=(5, 0))
        self.composer_preview_340 = ttk.Label(mini, text="340px 홈 미리보기", anchor="center", width=42)
        self.composer_preview_340.pack(side="left", padx=(50, 24))
        self.composer_preview_180 = ttk.Label(mini, text="180px 소형 미리보기", anchor="center", width=24)
        self.composer_preview_180.pack(side="left")

        panel = ttk.Frame(body, width=470); panel.pack(side="right", fill="y"); panel.pack_propagate(False)
        controls = ttk.LabelFrame(panel, text="실시간 타이포 컨트롤"); controls.pack(fill="x", pady=(0, 5))
        self._composer_scale(controls, 0, "Title size", self.composer_title_size, 48, 150, integer=True)
        self._composer_scale(controls, 1, "Outline width", self.composer_outline, 0, 22)
        self._composer_scale(controls, 2, "Shadow", self.composer_shadow, 0, 1.5)
        self._composer_scale(controls, 3, "Glow", self.composer_glow, 0, 1.5)
        self._composer_scale(controls, 4, "Line spacing", self.composer_line_spacing, 0.85, 1.55)
        self._composer_scale(controls, 5, "Letter spacing", self.composer_letter_spacing, -2.0, 4.0)
        align_row = ttk.Frame(controls); align_row.grid(row=6, column=0, columnspan=4, sticky="ew", padx=5, pady=2)
        ttk.Label(align_row, text="정렬").pack(side="left")
        ttk.Combobox(align_row, textvariable=self.composer_alignment, state="readonly", width=10,
                     values=("left", "center", "right")).pack(side="left", padx=4)
        ttk.Label(align_row, text="Anchor").pack(side="left", padx=(10, 2))
        ttk.Combobox(align_row, textvariable=self.composer_anchor, state="readonly", width=14,
            values=("lower-left", "lower-center", "lower-right", "upper-left", "upper-right", "center")).pack(side="left")
        for row, label, variable in ((7, "Fill", self.composer_fill), (8, "Stroke", self.composer_stroke),
                                     (9, "Highlight", self.composer_highlight)):
            ttk.Label(controls, text=label).grid(row=row, column=0, sticky="e", padx=4, pady=2)
            ttk.Entry(controls, textvariable=variable, width=12).grid(row=row, column=1, sticky="w", padx=3, pady=2)
            ttk.Label(controls, text="#RRGGBB").grid(row=row, column=2, sticky="w")
        toggles = ttk.Frame(controls); toggles.grid(row=10, column=0, columnspan=4, sticky="ew", padx=5)
        ttk.Checkbutton(toggles, text="Soft plate", variable=self.composer_soft_plate).pack(side="left")
        ttk.Checkbutton(toggles, text="배경 gradient", variable=self.composer_gradient).pack(side="left", padx=6)
        ttk.Checkbutton(toggles, text="안전영역", variable=self.composer_safe_overlay).pack(side="right")
        self.background_fit_info = tk.StringVar(value="배경 분석: 이미지 대기")
        ttk.Label(controls, textvariable=self.background_fit_info, foreground="#43546a", wraplength=440).grid(
            row=11, column=0, columnspan=4, sticky="w", padx=7, pady=2)
        for variable in (self.composer_title_size, self.composer_outline, self.composer_shadow,
                         self.composer_glow, self.composer_line_spacing, self.composer_letter_spacing,
                         self.composer_alignment, self.composer_anchor, self.composer_fill,
                         self.composer_stroke, self.composer_highlight, self.composer_soft_plate,
                         self.composer_gradient, self.composer_safe_overlay):
            variable.trace_add("write", self._composer_control_changed)
        for variable in (self.composer_title, self.composer_subtitle, self.composer_episode, self.composer_story):
            variable.trace_add("write", self._composer_control_changed)
        self.composer_anchor.trace_add("write", self._composer_apply_anchor)
        ttk.Button(panel, text="선택 후보에 편집 반영", command=self.apply_composer_result).pack(fill="x", pady=(0, 5))

        cards = ttk.LabelFrame(panel, text="스타일 카드 · 클릭 즉시 적용"); cards.pack(fill="both", expand=True)
        self.composer_style_tabs = ttk.Notebook(cards); self.composer_style_tabs.pack(fill="both", expand=True, padx=3, pady=3)
        self.composer_style_frames = {}
        for channel, title in (("Tokyo Chill", "Tokyo Chill"), ("OLD POP LOUNGE", "Old Pop Lounge")):
            frame = ttk.Frame(self.composer_style_tabs); self.composer_style_tabs.add(frame, text=title)
            self.composer_style_frames[channel] = frame
        self.composer_style_tabs.bind("<<NotebookTabChanged>>", lambda _event: self._load_composer_style_cards())

    @staticmethod
    def _composer_scale(parent, row, label, variable, low, high, integer=False):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="e", padx=4)
        scale = ttk.Scale(parent, from_=low, to=high, variable=variable, orient="horizontal", length=154)
        scale.grid(row=row, column=1, sticky="ew", padx=3, pady=2)
        ttk.Label(parent, textvariable=variable, width=6).grid(row=row, column=2, sticky="w")
        parent.columnconfigure(1, weight=1)

    def _composer_default_state(self, code):
        channel = self.composer_channel.get()
        names = preset_names(channel)
        style_name = self.composer_style.get()
        if style_name not in names:
            style_name = names[0]
        preset = get_preset(style_name, channel)
        layout = choose_layout(code, channel, self.composer_story.get(), self.composer_episode.get(), 108)
        positions = {
            "channel_label": (30, 20, 270, 68),
            "story_label": layout.badge_box,
            "episode_badge": (980, 20, 270, 68),
            "main_title": layout.title_box,
            "subtitle": (48, 662 if channel == "Tokyo Chill" else 654, 1160, 48),
        }
        return {"channel": channel, "style": style_name, "title_size": 108,
            "outline_width": preset.outline_width, "shadow_strength": 0.9, "glow_strength": 1.0,
            "line_spacing": 1.17, "letter_spacing": preset.letter_spacing,
            "alignment": layout.align, "anchor": {"A_PERSON": "lower-left", "B_EMOTION": "lower-center", "C_STORY": "upper-left"}.get(code, "lower-left"),
            "fill_color": preset.fill, "stroke_color": preset.outline, "highlight_color": preset.accent,
            "title_text": self.composer_title.get(), "subtitle_text": self.composer_subtitle.get(),
            "episode_text": self.composer_episode.get(), "story_text": self.composer_story.get(),
            "soft_plate": True, "gradient": True, "safe_overlay": False, "positions": positions}

    def _composer_snapshot(self, code=None):
        code = code or self.composer_code.get()
        return {"channel": self.composer_channel.get(), "style": self.composer_style.get(),
            "title_size": int(self.composer_title_size.get()), "outline_width": float(self.composer_outline.get()),
            "shadow_strength": float(self.composer_shadow.get()), "glow_strength": float(self.composer_glow.get()),
            "line_spacing": float(self.composer_line_spacing.get()), "letter_spacing": float(self.composer_letter_spacing.get()),
            "alignment": self.composer_alignment.get(), "anchor": self.composer_anchor.get(),
            "fill_color": self.composer_fill.get().strip(), "stroke_color": self.composer_stroke.get().strip(),
            "highlight_color": self.composer_highlight.get().strip(), "soft_plate": bool(self.composer_soft_plate.get()),
            "gradient": bool(self.composer_gradient.get()), "safe_overlay": bool(self.composer_safe_overlay.get()),
            "title_text": self.composer_title.get(), "subtitle_text": self.composer_subtitle.get(),
            "episode_text": self.composer_episode.get(), "story_text": self.composer_story.get(),
            "positions": {key: tuple(value) for key, value in self.composer_positions.get(code, {}).items()}}

    def _composer_candidate_changed(self):
        if not hasattr(self, "composer_canvas"):
            return
        code = self.composer_code.get()
        if code not in self.composer_states:
            self.composer_states[code] = self._composer_default_state(code)
            self.composer_positions[code] = dict(self.composer_states[code]["positions"])
        state = self.composer_states[code]
        self._composer_loading_state = True
        try:
            self.composer_channel.set(state["channel"]); self.composer_style.set(state["style"])
            self.composer_title_size.set(state["title_size"]); self.composer_outline.set(state["outline_width"])
            self.composer_shadow.set(state["shadow_strength"]); self.composer_glow.set(state["glow_strength"])
            self.composer_line_spacing.set(state["line_spacing"]); self.composer_letter_spacing.set(state["letter_spacing"])
            self.composer_alignment.set(state["alignment"]); self.composer_anchor.set(state["anchor"])
            self.composer_fill.set(state["fill_color"]); self.composer_stroke.set(state["stroke_color"])
            self.composer_highlight.set(state["highlight_color"]); self.composer_soft_plate.set(state["soft_plate"])
            self.composer_gradient.set(state["gradient"]); self.composer_safe_overlay.set(state["safe_overlay"])
            self.composer_title.set(state["title_text"]); self.composer_subtitle.set(state["subtitle_text"])
            self.composer_episode.set(state["episode_text"]); self.composer_story.set(state["story_text"])
            self.composer_positions[code] = dict(state["positions"])
        finally:
            self._composer_loading_state = False
        self._render_live_composer()

    def _composer_control_changed(self, *_):
        if self._composer_loading_state or not hasattr(self, "composer_canvas"):
            return
        code = self.composer_code.get()
        previous = self.composer_states.get(code)
        current = self._composer_snapshot(code)
        if previous is None:
            self.composer_states[code] = current
        elif current != previous:
            if self._composer_pending_before is None:
                self._composer_pending_before = previous
            self.composer_states[code] = current
            if self._composer_history_job:
                self.after_cancel(self._composer_history_job)
            self._composer_history_job = self.after(420, self._commit_composer_history)
        self._schedule_live_render()

    def _commit_composer_history(self):
        code = self.composer_code.get()
        if self._composer_pending_before is not None:
            history = self.composer_history.setdefault(code, [])
            history.append(self._composer_pending_before)
            del history[:-80]
            self.composer_redo.setdefault(code, []).clear()
            self._composer_pending_before = None
        self._composer_history_job = None

    def _schedule_live_render(self):
        if self._composer_render_job:
            self.after_cancel(self._composer_render_job)
        self.composer_info.set("렌더 대기 · 150ms debounce")
        self._composer_render_job = self.after(150, self._render_live_composer)

    def _render_live_composer(self):
        self._composer_render_job = None
        code = self.composer_code.get()
        base = self.composer_bases.get(code)
        if base is None:
            self.composer_canvas.delete("all")
            self.composer_canvas.create_text(416, 234, text="프로젝트 이미지를 열거나 A/B/C 배경을 생성하세요",
                fill="white", font=("Segoe UI", 15))
            return
        state = self._composer_snapshot(code)
        try:
            self.composer_result, self.composer_metadata = render_candidate_text(
                base.copy(), state["channel"], code, state["story_text"], state["episode_text"],
                state["title_text"], state["subtitle_text"], state["style"],
                self.auto_two_line.get(), self.emphasize_keyword.get(), self.keyword.get(),
                state["title_size"], outline_thickness=state["outline_width"],
                glow_intensity=state["glow_strength"], shadow_intensity=state["shadow_strength"],
                subject_boxes=self._composer_sidecar_subjects(),
                safe_zones=self._composer_sidecar_safe_zones(),
                show_safe_overlay=state["safe_overlay"], live_options=state)
            if not state["positions"]:
                roles = self.composer_metadata.get("roles", {})
                self.composer_positions[code] = {name: tuple(box) for name, box in roles.items()}
                state["positions"] = dict(self.composer_positions[code])
                self.composer_states[code] = state
            self._draw_composer_canvas()
            self._draw_composer_minis()
            fit = self.composer_metadata.get("background_fit", {})
            self.background_fit_info.set(
                f"가독성 {fit.get('readability', 0):.2f} · 피사체 충돌 {fit.get('subject_conflict', 0):.2f} · "
                f"주색 {fit.get('dominant_color', '#000000')} / 포인트 {fit.get('accent_color', '#FFFFFF')} · "
                f"자동 plate/gradient {'권장' if fit.get('soft_plate_recommended') else '선택'}")
            self.composer_info.set(f"1280 × 720 · {code} · {state['style']} · 150ms debounce 렌더 완료")
        except Exception as exc:
            self.composer_info.set(f"미리보기 오류: {exc}")
            logging.exception("Live Composer render failed")

    def _draw_composer_canvas(self):
        if self.composer_result is None:
            return
        rgb = cv2.cvtColor(self.composer_result, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb).resize((self.composer_canvas_width, self.composer_canvas_height), Image.Resampling.LANCZOS)
        self._composer_canvas_ref = ImageTk.PhotoImage(image)
        canvas = self.composer_canvas; canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=self._composer_canvas_ref)
        code, active = self.composer_code.get(), self.composer_role.get()
        state = self._composer_snapshot(code)
        boxes = state["positions"]
        sx = self.composer_canvas_width / 1280; sy = self.composer_canvas_height / 720
        for role, box in boxes.items():
            x, y, w, h = box
            color = "#45E6FF" if role == active else "#FFCA5C"
            dash = () if role == active else (3, 4)
            canvas.create_rectangle(x*sx, y*sy, (x+w)*sx, (y+h)*sy, outline=color,
                                    width=2 if role == active else 1, dash=dash)
            canvas.create_text(x*sx+4, y*sy+3, anchor="nw", text=role, fill=color,
                               font=("Segoe UI", 8, "bold"))
        title_bbox = self.composer_metadata.get("title", {}).get("bbox")
        if title_bbox and active == "main_title":
            x, y, w, h = title_bbox
            canvas.create_rectangle(x*sx, y*sy, (x+w)*sx, (y+h)*sy, outline="#FFFFFF", width=1)

    def _draw_composer_minis(self):
        if self.composer_result is None:
            return
        rgb = cv2.cvtColor(self.composer_result, cv2.COLOR_BGR2RGB)
        for label, size in ((self.composer_preview_340, (340, 191)), (self.composer_preview_180, (180, 101))):
            image = Image.fromarray(rgb).resize(size, Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(image)
            label.configure(image=photo, text="")
            if not hasattr(self, "_composer_mini_refs"):
                self._composer_mini_refs = []
            self._composer_mini_refs.append(photo)
        self._composer_mini_refs = self._composer_mini_refs[-2:]

    def _composer_drag_start(self, event):
        code, role = self.composer_code.get(), self.composer_role.get()
        boxes = self.composer_positions.get(code, {})
        if role not in boxes:
            return
        self._commit_composer_history()
        self._composer_drag = (code, role, event.x, event.y, tuple(boxes[role]), self._composer_snapshot(code))

    def _composer_drag_motion(self, event):
        if not self._composer_drag:
            return
        code, role, sx, sy, original, _before = self._composer_drag
        scale_x = self.composer_canvas_width / 1280; scale_y = self.composer_canvas_height / 720
        dx, dy = round((event.x - sx) / scale_x), round((event.y - sy) / scale_y)
        x, y, w, h = original
        x = max(0, min(1280 - w, x + dx)); y = max(0, min(720 - h, y + dy))
        state = self.composer_states[code]
        state["positions"][role] = (x, y, w, h)
        self.composer_positions[code][role] = (x, y, w, h)
        self._draw_composer_canvas()
        self._schedule_live_render()

    def _composer_drag_end(self, _event):
        if not self._composer_drag:
            return
        code, _role, _sx, _sy, _original, before = self._composer_drag
        after = self._composer_snapshot(code)
        if after != before:
            self.composer_history.setdefault(code, []).append(before)
            self.composer_redo.setdefault(code, []).clear()
        self._composer_drag = None

    def _apply_composer_state(self, state):
        code = self.composer_code.get()
        self._composer_loading_state = True
        try:
            self.composer_channel.set(state["channel"]); self.composer_style.set(state["style"])
            self.composer_title_size.set(state["title_size"]); self.composer_outline.set(state["outline_width"])
            self.composer_shadow.set(state["shadow_strength"]); self.composer_glow.set(state["glow_strength"])
            self.composer_line_spacing.set(state["line_spacing"]); self.composer_letter_spacing.set(state["letter_spacing"])
            self.composer_alignment.set(state["alignment"]); self.composer_anchor.set(state["anchor"])
            self.composer_fill.set(state["fill_color"]); self.composer_stroke.set(state["stroke_color"])
            self.composer_highlight.set(state["highlight_color"]); self.composer_soft_plate.set(state["soft_plate"])
            self.composer_gradient.set(state["gradient"]); self.composer_safe_overlay.set(state["safe_overlay"])
            self.composer_title.set(state["title_text"]); self.composer_subtitle.set(state["subtitle_text"])
            self.composer_episode.set(state["episode_text"]); self.composer_story.set(state["story_text"])
            self.composer_positions[code] = dict(state["positions"])
            self.composer_states[code] = state
        finally:
            self._composer_loading_state = False
        self._schedule_live_render()

    def composer_undo(self):
        self._commit_composer_history()
        code = self.composer_code.get(); history = self.composer_history.setdefault(code, [])
        if history:
            self.composer_redo.setdefault(code, []).append(self._composer_snapshot(code))
            self._apply_composer_state(history.pop())

    def composer_redo_action(self):
        self._commit_composer_history()
        code = self.composer_code.get(); redo = self.composer_redo.setdefault(code, [])
        if redo:
            self.composer_history.setdefault(code, []).append(self._composer_snapshot(code))
            self._apply_composer_state(redo.pop())

    def _composer_apply_anchor(self, *_):
        if self._composer_loading_state:
            return
        code = self.composer_code.get(); state = self._composer_snapshot(code)
        positions = state["positions"]; box = positions.get("main_title")
        if not box:
            return
        x, y, w, h = box; anchor = self.composer_anchor.get()
        x = {"lower-left": 42, "lower-center": (1280-w)//2, "lower-right": 1238-w,
             "upper-left": 52, "upper-right": 1228-w, "center": (1280-w)//2}.get(anchor, x)
        y = {"lower-left": 438, "lower-center": 414, "lower-right": 438,
             "upper-left": 94, "upper-right": 94, "center": 260}.get(anchor, y)
        positions["main_title"] = (x, y, w, h)
        state["alignment"] = "center" if anchor in ("lower-center", "center") else ("right" if anchor.endswith("right") else "left")
        self.composer_states[code] = state; self.composer_positions[code] = dict(positions)
        self._composer_loading_state = True
        try: self.composer_alignment.set(state["alignment"])
        finally: self._composer_loading_state = False
        self._schedule_live_render()

    def _load_composer_style_cards(self):
        if self._composer_cards_loaded:
            return
        self._composer_cards_loaded = True
        for channel, frame in self.composer_style_frames.items():
            for index, style in enumerate(PRESETS_BY_CHANNEL[channel]):
                card = ttk.Frame(frame, relief="ridge", borderwidth=1)
                card.grid(row=index // 3, column=index % 3, padx=3, pady=3, sticky="nsew")
                background = np.zeros((180, 320, 3), dtype=np.uint8)
                for row in range(180):
                    t = row / 179
                    background[row, :, :] = (np.array([26, 38, 58]) * (1-t) + np.array([88, 68, 72]) * t).astype(np.uint8)
                sample = render_title(background, "Tokyo night / 思い出", (10, 62, 300, 104),
                    style.name, channel, "center", 30, max_lines=2, supersample=1)
                photo = ImageTk.PhotoImage(Image.fromarray(cv2.cvtColor(sample.image, cv2.COLOR_BGR2RGB)).resize(
                    (112, 63), Image.Resampling.LANCZOS))
                self.composer_style_refs.append(photo)
                button = ttk.Button(card, image=photo, text=style.name, compound="top",
                    command=lambda style=style: self._composer_apply_style(style.name, style.channel))
                button.pack(fill="both", expand=True, padx=2, pady=2)
                frame.columnconfigure(index % 3, weight=1); frame.rowconfigure(index // 3, weight=1)

    def _composer_apply_style(self, style_name, channel):
        code = self.composer_code.get(); state = self.composer_states.get(code, self._composer_default_state(code))
        style = get_preset(style_name, channel)
        state.update(channel=channel, style=style_name, fill_color=style.fill,
                     stroke_color=style.outline, highlight_color=style.accent,
                     outline_width=style.outline_width, letter_spacing=style.letter_spacing)
        self._apply_composer_state(state)

    def _composer_sidecar_subjects(self):
        return self.composer_subjects.get(self.composer_code.get(), ())

    def _composer_sidecar_safe_zones(self):
        return self.composer_safe_zones.get(self.composer_code.get(), ())

    def open_composer_project(self):
        folder = filedialog.askdirectory(title="이미지 프로젝트 폴더 선택")
        if not folder:
            return
        root = Path(folder)
        assets = load_image_storage_assets(root)
        files = [path for path in root.iterdir() if path.suffix.casefold() in (".png", ".jpg", ".jpeg", ".webp")
                 and path.name.casefold() not in ("preview_reference.png", "reference_thumb.png", "canvas_clean.png", "cleaned_canvas.png")]
        source = assets.cleaned_canvas if assets.cleaned_canvas and assets.cleaned_canvas.is_file() else (files[0] if files else None)
        if source is None:
            return messagebox.showwarning("프로젝트", "폴더에서 사용할 이미지 파일을 찾지 못했습니다.")
        self.src.set(str(source)); self.reference_src.set(str(assets.reference_thumbnail or ""))
        self.composer_channel.set(self.channel.get())
        palette = assets.palette
        self.composer_fill.set(palette.get("fill_color", palette.get("fill", self.composer_fill.get())))
        self.composer_stroke.set(palette.get("stroke_color", palette.get("outline", self.composer_stroke.get())))
        self.composer_highlight.set(palette.get("highlight_color", palette.get("accent", self.composer_highlight.get())))
        positions = assets.composition.get("positions", assets.composition.get("roles", {}))
        code = self.composer_code.get()
        if isinstance(positions, dict):
            imported = {}
            for key, value in positions.items():
                if key not in ("channel_label", "story_label", "episode_badge", "main_title", "subtitle"):
                    continue
                box = value.get("bbox", value.get("box", value)) if isinstance(value, dict) else value
                if not isinstance(box, (list, tuple)) or len(box) != 4:
                    continue
                x, y, width, height = map(float, box)
                if max(abs(x), abs(y), abs(width), abs(height)) <= 1:
                    x, width, y, height = x * 1280, width * 1280, y * 720, height * 720
                imported[key] = tuple(round(item) for item in (x, y, width, height))
            state = self.composer_states.get(code, self._composer_default_state(code))
            state["positions"].update(imported)
            self.composer_states[code] = state
            self.composer_positions[code] = dict(state["positions"])
        self.build_composer_backgrounds()

    def refresh_composer_project(self):
        if not self.src.get():
            return self.open_composer_project()
        self.build_composer_backgrounds()

    def build_composer_backgrounds(self):
        if not self.src.get():
            return messagebox.showwarning("Live Composer", "먼저 프로젝트 폴더 또는 원본 이미지를 여세요.")
        try:
            self.composer_channel.set(self.channel.get())
            self.composer_bases.clear()
            self.composer_subjects.clear()
            self.composer_safe_zones.clear()
            generated = create_candidate_images(self.src.get(), self.composer_channel.get(), TEMPLATE_MODE,
                self.focus_mode.get(), self.protagonist, self.counterpart, self.story_type.get(),
                self.template_episode.get(), "", "", self.composer_style.get(), self.auto_two_line.get(),
                self.emphasize_keyword.get(), self.keyword.get(), self.composer_title_size.get(),
                render_text=False)
            for candidate in generated:
                self.composer_bases[candidate.code] = candidate.image.copy()
                self.composer_subjects[candidate.code] = tuple(candidate.typography.get("subject_boxes", ()))
                self.composer_safe_zones[candidate.code] = tuple(candidate.typography.get("safe_zones", ()))
                if candidate.code not in self.composer_states:
                    self.composer_states[candidate.code] = self._composer_default_state(candidate.code)
                state = self.composer_states[candidate.code]
                if not state["positions"]:
                    self.composer_positions[candidate.code] = dict(state["positions"])
            self.candidates = generated
            self._composer_candidate_changed()
            self.composer_info.set("A/B/C 무텍스트 배경 생성 완료 · 선택 후보의 글자 레이어를 편집하세요")
        except Exception as exc:
            logging.exception("Composer background creation failed")
            messagebox.showerror("Live Composer", str(exc))

    def _composer_placeholder(self, feature):
        messagebox.showinfo(feature, f"{feature} 연결 인터페이스를 준비했습니다. 실제 배경 생성/편집 서비스 호출은 후속 버전에서 연결합니다.")

    @staticmethod
    def _bridge_channel(value, fallback="Tokyo Chill"):
        value = str(value or "").strip().casefold().replace("_", " ").replace("-", " ")
        if value in ("old pop lounge", "oldpoplounge", "old pop", "senior classic"):
            return "OLD POP LOUNGE"
        if value in ("tokyo chill", "tokyo chill rap", "tokyo"):
            return "Tokyo Chill"
        return fallback

    @staticmethod
    def _bridge_episode(value):
        value = str(value or "").strip()
        if not value:
            return ""
        return value if value.upper().startswith("EP") else f"EP.{value.zfill(3)}"

    def open_image_project(self):
        folder = filedialog.askdirectory(title="이미지 프로젝트 폴더 선택",
            initialdir=str(self.image_project.folder) if self.image_project else None)
        if folder:
            self.load_image_project_folder(folder, refresh=False)

    def load_image_project_folder(self, folder, refresh=False):
        """Load project assets; refresh preserves the user's current text and control values."""
        project = load_image_project(folder)
        if project.source_image is None:
            self.image_project = project
            self.image_project_path.set(str(project.folder))
            self.image_bridge_status.set(self._image_bridge_status_text(project.status))
            messagebox.showwarning("Image Bridge", "프로젝트 폴더에서 캔버스나 이미지 파일을 찾지 못했습니다.")
            return False

        previous_project = self.image_project
        old_palette = dict(self._image_bridge_palette)
        self.image_project = project
        self.image_project_path.set(str(project.folder))
        self.image_bridge_status.set(self._image_bridge_status_text(project.status))
        self.reference_src.set(str(project.reference_image) if project.reference_image else "")
        if project.source_image and self.src.get() != str(project.source_image):
            self.src.set(str(project.source_image))
        self.protagonist = project.subject_points.get("protagonist")
        self.counterpart = project.subject_points.get("counterpart")
        self.focus_source = str(project.source_image)

        manifest, palette = project.manifest, project.palette
        channel = self._bridge_channel(manifest.get("channel"), self.channel.get())
        preferred = str(manifest.get("preferred_typography", "") or "").strip()
        if preferred not in preset_names(channel):
            preferred = preset_names(channel)[0]
        palette_values = {
            "fill_color": palette.get("fill_color"), "stroke_color": palette.get("stroke_color"),
            "highlight_color": palette.get("highlight_color"), "glow_strength": palette.get("glow_strength"),
            "shadow_strength": palette.get("shadow_strength"), "outline_width": palette.get("outline_width"),
        }
        variables = {"fill_color": self.composer_fill, "stroke_color": self.composer_stroke,
            "highlight_color": self.composer_highlight, "glow_strength": self.composer_glow,
            "shadow_strength": self.composer_shadow, "outline_width": self.composer_outline}

        if refresh:
            # A changed palette value is imported only if its control still matches the old imported value.
            for key, variable in variables.items():
                value = palette_values.get(key)
                if value in (None, ""):
                    continue
                prior = old_palette.get(key)
                if prior is not None and str(variable.get()) == str(prior):
                    variable.set(value)
            state_keys = {"fill_color": "fill_color", "stroke_color": "stroke_color",
                "highlight_color": "highlight_color", "glow_strength": "glow_strength",
                "shadow_strength": "shadow_strength", "outline_width": "outline_width"}
            for state in self.composer_states.values():
                for palette_key, state_key in state_keys.items():
                    prior = old_palette.get(palette_key)
                    if prior is not None and str(state.get(state_key)) == str(prior):
                        state[state_key] = variables[palette_key].get()
            old_positions = self._image_bridge_position_baselines
            new_positions = project.composition.get("positions", {})
            for code, state in self.composer_states.items():
                current_positions = state.get("positions", {})
                baseline = old_positions.get(code, {})
                for role, new_box in new_positions.items():
                    old_box = baseline.get(role, current_positions.get(role))
                    if old_box is not None and tuple(current_positions.get(role, ())) == tuple(old_box):
                        current_positions[role] = tuple(new_box)
                        baseline[role] = tuple(new_box)
                self.composer_positions[code] = dict(current_positions)
                self._image_bridge_position_baselines[code] = dict(baseline)
            self._image_bridge_palette = {key: value for key, value in palette_values.items() if value not in (None, "")}
        else:
            self.channel.set(channel)
            self.composer_channel.set(channel)
            self.typography_style.set(preferred)
            self.composer_style.set(preferred)
            self.template_title.set(str(manifest.get("title") or self.template_title.get()))
            self.template_subtitle.set(str(manifest.get("subtitle") or self.template_subtitle.get()))
            self.template_episode.set(self._bridge_episode(manifest.get("episode")) or self.template_episode.get())
            self.story_type.set(str(manifest.get("story_type") or self.story_type.get()))
            self.composer_title.set(self.template_title.get())
            self.composer_subtitle.set(self.template_subtitle.get())
            self.composer_episode.set(self.template_episode.get())
            self.composer_story.set(self.story_type.get())
            preset = get_preset(preferred, channel)
            palette_values = {key: value if value not in (None, "") else default for key, value, default in (
                ("fill_color", palette_values["fill_color"], preset.fill),
                ("stroke_color", palette_values["stroke_color"], preset.outline),
                ("highlight_color", palette_values["highlight_color"], preset.accent),
                ("glow_strength", palette_values["glow_strength"], 1.0),
                ("shadow_strength", palette_values["shadow_strength"], 0.9),
                ("outline_width", palette_values["outline_width"], preset.outline_width))}
            for key, variable in variables.items():
                variable.set(palette_values[key])
            self._image_bridge_palette = dict(palette_values)
            self.composer_states.clear()
            self.composer_positions = {code: {} for code in ("A_PERSON", "B_EMOTION", "C_STORY")}
            for code in self.composer_positions:
                state = self._composer_default_state(code)
                state.update(fill_color=self.composer_fill.get(), stroke_color=self.composer_stroke.get(),
                    highlight_color=self.composer_highlight.get(), glow_strength=self.composer_glow.get(),
                    shadow_strength=self.composer_shadow.get(), outline_width=self.composer_outline.get())
                state["positions"].update(project.composition.get("positions", {}))
                self.composer_states[code] = state
                self.composer_positions[code] = dict(state["positions"])
            self._image_bridge_position_baselines = {
                code: dict(state["positions"]) for code, state in self.composer_states.items()}

        if refresh and previous_project and previous_project.folder != project.folder:
            refresh = False
        self.build_composer_backgrounds()
        if project.warnings:
            self.status.set("Image Bridge: " + "; ".join(project.warnings))
        else:
            self.status.set("Image Bridge project loaded: " + project.folder.name)
        return True

    @staticmethod
    def _image_bridge_status_text(status):
        labels = (("clean_canvas", "clean canvas"), ("safe_zones", "safe zones"),
                  ("subjects", "subject boxes"), ("palette", "palette"), ("manifest", "manifest"))
        return " · ".join(f"{name} {'loaded' if status.get(key) else 'missing/fallback'}" for key, name in labels)

    def refresh_image_project(self):
        folder = self.image_project.folder if self.image_project else (Path(self.src.get()).parent if self.src.get() else None)
        if folder is None:
            return self.open_image_project()
        return self.load_image_project_folder(folder, refresh=self.image_project is not None)

    def _legacy_launch_image_action(self, action):
        if not self.image_project:
            return messagebox.showinfo("Image Bridge", "먼저 프로젝트 폴더를 열어 주세요.")
        result = launch_generate(self.image_project.folder) if action == "generate" else launch_edit(self.image_project.folder)
        messagebox.showinfo("Image Bridge", result.message)
        return result

    def _launch_image_action(self, action):
        if not self.image_project:
            return messagebox.showinfo("Image Bridge", "먼저 프로젝트 폴더를 열어 주세요.")
        if self._image_action_running:
            self.image_run_summary.set("An image-program operation is already running.")
            return
        folder = self.image_project.folder
        options = {"channel": self.composer_channel.get(), "story_type": self.composer_story.get(),
            "title": self.composer_title.get(), "subtitle": self.composer_subtitle.get(),
            "episode": self.composer_episode.get(), "preferred_typography": self.composer_style.get()}
        prompt = self.image_prompt.get().strip() if action == "generate" else ""
        edit_request = self.image_edit_instruction.get().strip() if action == "edit" else ""
        self._image_action_running = True
        self.image_run_summary.set(f"Image program {action} is running; validating generated bridge files…")
        for button in self._image_action_buttons:
            button.configure(state="disabled")

        def worker():
            try:
                if action == "generate":
                    result = launch_generate(folder, prompt, options)
                else:
                    result = launch_edit(folder, edit_request, options)
            except Exception as exc:
                result = LaunchResult(False, f"Image Bridge failed safely: {exc}", action=action, project_dir=folder)
            self.image_bridge_queue.put((action, folder, result))

        threading.Thread(target=worker, name=f"image-bridge-{action}", daemon=True).start()
        self.after(100, self._poll_image_bridge)

    def _poll_image_bridge(self):
        try:
            action, folder, result = self.image_bridge_queue.get_nowait()
        except queue.Empty:
            if self._image_action_running:
                self.after(100, self._poll_image_bridge)
            return
        self._complete_image_action(action, folder, result)

    def _complete_image_action(self, action, folder, result: LaunchResult):
        self._image_action_running = False
        for button in self._image_action_buttons:
            button.configure(state="normal")
        log_parts = [result.message]
        if result.return_code is not None:
            log_parts.append(f"exit code: {result.return_code}")
        if result.warnings:
            log_parts.append("warnings: " + "; ".join(result.warnings))
        if result.stdout.strip():
            log_parts.append("stdout: " + result.stdout.strip()[-1800:])
        if result.stderr.strip():
            log_parts.append("stderr: " + result.stderr.strip()[-1800:])
        summary = "\n".join(log_parts)
        self.image_run_summary.set(summary[-3000:])
        logging.info("Image Bridge %s for %s: %s", action, folder, summary)
        if result.launched:
            try:
                self.load_image_project_folder(folder, refresh=True)
                self.image_run_summary.set(summary[:2100] + "\nProject refreshed from returned canvas/sidecars.")
            except Exception as exc:
                detail = f"Image program succeeded, but project refresh failed safely: {exc}"
                logging.exception(detail)
                self.image_run_summary.set((summary + "\n" + detail)[-3000:])
                messagebox.showwarning("Image Bridge", detail)
        else:
            self.status.set("Image Bridge failed; existing project settings were retained.")
            messagebox.showerror("Image Bridge", result.message)
        return result

    def launch_image_generate(self):
        return self._launch_image_action("generate")

    def launch_image_edit(self):
        return self._launch_image_action("edit")

    def apply_composer_result(self):
        code = self.composer_code.get()
        if self.composer_result is None:
            return messagebox.showwarning("Live Composer", "먼저 A/B/C 배경을 생성하세요.")
        for candidate in self.candidates:
            if candidate.code == code:
                candidate.image = self.composer_result.copy()
                candidate.typography = self.composer_metadata
                break
        if self.candidates and hasattr(self, "preview_labels"):
            index = next((i for i, item in enumerate(self.candidates) if item.code == code), None)
            if index is not None:
                photo = ImageTk.PhotoImage(Image.fromarray(self.composer_result[:, :, ::-1]).resize((280, 158), Image.Resampling.LANCZOS))
                self.preview_refs[index] = photo
                self.preview_labels[index].configure(image=photo, text="")
        self.status.set(f"{code} Live Composer 편집이 저장 후보에 반영됐습니다.")

    def pick_reference(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.jpg *.jpeg *.png *.webp")], title="비교용 완성 썸네일 선택")
        if path:
            self.reference_src.set(path)
            self._show_reference()

    def _show_reference(self):
        if not self.reference_src.get():
            return messagebox.showinfo("참고 이미지", "선택된 참고 썸네일이 없습니다.")
        try:
            im = Image.open(self.reference_src.get()).convert("RGB")
            im.thumbnail((720, 405), Image.Resampling.LANCZOS)
            win = tk.Toplevel(self); win.title("참고용 완성 썸네일 · 후보 생성에는 사용하지 않음")
            ttk.Label(win, text="참고 전용이며 크롭·합성 입력으로 사용하지 않습니다.").pack(padx=8, pady=6)
            photo = ImageTk.PhotoImage(im); label = ttk.Label(win, image=photo); label.image = photo; label.pack(padx=8, pady=8)
        except Exception as exc:
            messagebox.showerror("참고 이미지 오류", str(exc))

    def make_previews(self):
        if not self.src.get(): return messagebox.showwarning("확인", "이미지를 선택하세요.")
        def work():
            self.status.set("얼굴/구도를 분석하고 있습니다..."); self.update_idletasks()
            self.candidates = create_candidate_images(self.src.get(), self.channel.get(), self.source_mode.get(), self.focus_mode.get(), self.protagonist, self.counterpart,
                                                      self.story_type.get(), self.template_episode.get(), self.template_title.get(), self.template_subtitle.get(),
                                                      self.typography_style.get(), self.auto_two_line.get(), self.emphasize_keyword.get(),
                                                      self.keyword.get(), self.title_size.get(),
                                                      manual_breaks=self.manual_breaks.get().replace("|", "\n"),
                                                      outline_thickness=self.outline_thickness.get(),
                                                      glow_intensity=self.glow_intensity.get(),
                                                      shadow_intensity=self.shadow_intensity.get(),
                                                      show_safe_overlay=self.safe_zone_overlay.get()); self.preview_refs.clear()
            for candidate, image_label, note_label in zip(self.candidates, self.preview_labels, self.note_labels):
                photo = ImageTk.PhotoImage(Image.fromarray(candidate.image[:, :, ::-1]).resize((280, 158), Image.Resampling.LANCZOS))
                self.preview_refs.append(photo); image_label.configure(image=photo, text="")
                type_note = candidate.typography or {}
                title_meta = type_note.get("title", {})
                style_key = type_note.get("typography_style")
                style_name = TYPOGRAPHY_PRESETS[style_key].name if style_key in TYPOGRAPHY_PRESETS else ""
                detail = f"{style_name} · {title_meta.get('font_size', '')} px · {title_meta.get('contrast', '')} · {title_meta.get('keyword', '')}"
                note_label.configure(text=candidate.composition + "\n" + detail)
            self.show_selected_preview(["A", "B", "C"].index(self.selected_preview_var.get()))
            scores = candidate_similarities(self.candidates)
            score_text = " · ".join(f"{pair} 차이 {100 * (1 - score):.1f}%" for pair, score in scores.items())
            if candidates_too_similar(self.candidates):
                self.diversity_state.set("후보 차이가 부족합니다. 원본 이미지 + 템플릿 모드를 권장합니다. · " + score_text)
            else:
                self.diversity_state.set("후보 차이 확인 · " + score_text)
            self.save_all_button.state(["!disabled"])
            self.status.set("미리보기 완료 · 원본은 변경되지 않았습니다.")
        return self._handle(work)

    def _choose_output(self):
        chosen = filedialog.askdirectory(initialdir=Path(self.src.get()).parent if self.src.get() else APP_HOME, title="후보 저장 폴더")
        return Path(chosen) if chosen else None

    def save_one(self, index):
        if not self.candidates: return messagebox.showwarning("확인", "먼저 A/B/C 미리보기를 생성하세요.")
        out = self._choose_output()
        if not out: return
        def work():
            saved = save_candidates(self.src.get(), out, self.candidates, self.candidates[index].code)
            self.last_output_dir = out; self.status.set("저장 완료: " + saved[0][2]); messagebox.showinfo("완료", f"{self.candidates[index].label} 후보를 저장했습니다.")
        return self._handle(work)

    def save_all(self):
        if not self.candidates: return messagebox.showwarning("확인", "먼저 A/B/C 미리보기를 생성하세요.")
        if candidates_too_similar(self.candidates):
            self.diversity_state.set("A/B/C 차이 부족 · 경고 확인 후 저장 가능")
            if not messagebox.askyesno("A/B/C 차이 부족", "후보 차이가 작습니다. 원본 이미지 + 템플릿 모드를 권장합니다. 그래도 저장할까요?"):
                return
        out = self._choose_output()
        if not out: return
        def work():
            saved = save_candidates(self.src.get(), out, self.candidates); self.last_output_dir = out
            self.status.set("3개 저장 완료: " + " | ".join(Path(item[2]).name for item in saved)); messagebox.showinfo("완료", "A/B/C 후보 3개와 manifest JSON을 저장했습니다.")
        return self._handle(work)

    def open_output_folder(self):
        if not self.last_output_dir or not Path(self.last_output_dir).is_dir(): return messagebox.showwarning("확인", "아직 저장된 결과 폴더가 없습니다.")
        try: os.startfile(str(self.last_output_dir))
        except AttributeError: subprocess.Popen(["xdg-open", str(self.last_output_dir)])

    def _tab_motion(self, notebook):
        tab = ttk.Frame(notebook); notebook.add(tab, text="② Motion Intro"); self.source_row(tab)
        for label, variable, values in [("프리셋", self.preset, list(PRESETS)), ("길이(초)", self.duration, [6, 8, 10, 12])]:
            row = ttk.Frame(tab); row.pack(fill="x", padx=16, pady=8); ttk.Label(row, text=label, width=14).pack(side="left")
            ttk.Combobox(row, textvariable=variable, values=values, state="readonly", width=35).pack(side="left")
        row = ttk.Frame(tab); row.pack(fill="x", padx=16, pady=8); ttk.Label(row, text="움직임 강도", width=14).pack(side="left")
        ttk.Scale(row, from_=0.5, to=1.5, variable=self.intensity, orient="horizontal", length=360).pack(side="left")
        ttk.Button(tab, text="MP4 만들기", command=self.go_motion).pack(pady=24, ipadx=35, ipady=9)
        ttk.Label(tab, text="1920×1080 · 30fps · H.264 · 내장 인코더 사용", foreground="#555").pack()

    def go_motion(self):
        if not self.src.get(): return messagebox.showwarning("확인", "이미지를 선택하세요.")
        source = Path(self.src.get()); output = filedialog.asksaveasfilename(initialdir=source.parent, initialfile=source.stem + "_MOTION.mp4", defaultextension=".mp4", filetypes=[("MP4", "*.mp4")])
        if not output: return
        def work():
            self.status.set("렌더링 중..."); self.update_idletasks(); render(source, output, self.preset.get(), self.duration.get(), intensity=self.intensity.get())
            self.status.set("완료: " + output); messagebox.showinfo("완료", "Motion Intro 생성 완료")
        return self._handle(work)

    def _tab_history(self, notebook):
        tab = ttk.Frame(notebook); notebook.add(tab, text="③ 테스트 기록")
        for label, variable in [("영상/회차", self.episode), ("A 결과", self.a), ("B 결과", self.b), ("C 결과", self.c)]:
            row = ttk.Frame(tab); row.pack(fill="x", padx=20, pady=7); ttk.Label(row, text=label, width=14).pack(side="left"); ttk.Entry(row, textvariable=variable, width=24).pack(side="left")
        row = ttk.Frame(tab); row.pack(fill="x", padx=20, pady=7); ttk.Label(row, text="승자", width=14).pack(side="left")
        ttk.Combobox(row, textvariable=self.winner, values=["A", "B", "C", "판정없음"], state="readonly", width=21).pack(side="left")
        ttk.Button(tab, text="테스트 결과 저장", command=self.save_history).pack(pady=18, ipadx=24, ipady=6)
        self.summary = tk.StringVar(value="아직 요약하지 않았습니다."); ttk.Label(tab, textvariable=self.summary, wraplength=900, justify="center").pack(padx=20, pady=12)
        ttk.Button(tab, text="현재 채널 누적 요약", command=lambda: self.summary.set(summarize(self.db, self.channel.get()))).pack()

    def save_history(self):
        def work():
            record_test(self.db, self.episode.get(), self.channel.get(), self.a.get(), self.b.get(), self.c.get(), self.winner.get())
            self.summary.set(summarize(self.db, self.channel.get())); self.status.set("테스트 기록 저장: " + str(self.db))
        return self._handle(work)


def _argument(flag):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv and sys.argv.index(flag) + 1 < len(sys.argv) else None


def main():
    # Full GUI smoke test of the Pro Editor (real Tk events), used for the packaged EXE.
    if len(sys.argv) >= 3 and sys.argv[1] == "--self-test-editor":
        from editor.selftest import main_self_test
        app = App()
        try:
            code = main_self_test(app, sys.argv[2], _argument("--capture"), _argument("--report"),
                                  "--bridge-generate" in sys.argv, bridge_prompt=_argument("--bridge-prompt"),
                                  keep_dir=_argument("--keep-dir"))
        finally:
            app.destroy()
        raise SystemExit(code)
    # Headless hook used only to validate the packaged engine on real Windows paths.
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-project":
        app = App()
        try:
            if not app.load_image_project_folder(sys.argv[2]):
                raise SystemExit(2)
            app.update_idletasks(); app.update()
            if len(app.composer_bases) != 3 or app.composer_result is None:
                raise RuntimeError("Image Bridge project did not produce all three live previews")
        finally:
            app.destroy()
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--self-test":
        generate_candidates(sys.argv[2], sys.argv[3], "Tokyo Chill", "완성 썸네일(글자 보호)", "자동")
        return
    if len(sys.argv) == 4 and sys.argv[1] == "--self-test-motion":
        render(sys.argv[2], sys.argv[3], "Tokyo Chill - Rain", duration=1, fps=2, width=640, height=360)
        return
    app = App()
    if "--smoke-test" in sys.argv:
        app.after(1200, app.destroy)
    app.mainloop()


if __name__ == "__main__":
    main()
