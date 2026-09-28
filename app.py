from __future__ import annotations

import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk
from motion_engine import PRESETS, render
from thumbnail_engine import APP_VERSION, create_candidate_images, generate_candidates, record_test, save_candidates, summarize


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
        self.geometry("1180x760"); self.minsize(1040, 700)
        self.src = tk.StringVar(); self.channel = tk.StringVar(value="Tokyo Chill")
        self.source_mode = tk.StringVar(value="완성 썸네일(글자 보호)")
        self.focus_mode = tk.StringVar(value="자동")
        self.preset = tk.StringVar(value="Tokyo Chill - Rain"); self.duration = tk.IntVar(value=8)
        self.intensity = tk.DoubleVar(value=1.0); self.status = tk.StringVar(value="이미지를 선택하세요.")
        self.episode = tk.StringVar(value="EP001"); self.a = tk.StringVar(); self.b = tk.StringVar(); self.c = tk.StringVar()
        self.winner = tk.StringVar(value="B"); self.db = APP_HOME / "youtube_test_history.csv"
        self.candidates = []; self.preview_refs = []; self.last_output_dir = None
        self.protagonist = None; self.counterpart = None; self.focus_source = None
        ttk.Label(self, text="YOUTUBE DYNAMIC THUMBNAIL STUDIO", font=("Segoe UI", 18, "bold")).pack(pady=(14, 2))
        ttk.Label(self, text=f"v{APP_VERSION} · 3후보 미리보기 + Motion Intro · FFmpeg 포함", foreground="#555").pack()
        ttk.Label(self, text="Motion uses FFmpeg · LGPLv3 · 같은 폴더 ydts_ffmpeg로 호환 빌드 교체 가능", foreground="#555").pack()
        ttk.Button(self, text="오픈소스 라이선스", command=self.show_licenses).pack(anchor="e", padx=18, pady=(0, 2))
        notebook = ttk.Notebook(self); notebook.pack(fill="both", expand=True, padx=14, pady=10)
        self._tab_candidates(notebook); self._tab_motion(notebook); self._tab_history(notebook)
        ttk.Label(self, textvariable=self.status, wraplength=1100).pack(pady=(0, 8))
        self.src.trace_add("write", self._source_changed)
        self.source_mode.trace_add("write", lambda *_: self._update_mode_guard())
        self.focus_mode.trace_add("write", lambda *_: self._update_focus_state())
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

    def _update_mode_guard(self):
        if not hasattr(self, "mode_guard"):
            return
        completed = self.source_mode.get() == "완성 썸네일(글자 보호)"
        self.mode_guard.set("글자/로고 보호 ON · 크롭 금지" if completed else "원본 이미지 모드 · 안전 크롭 허용")

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
            self.focus_source = source; self._update_focus_state(); dialog.destroy()

    def _tab_candidates(self, notebook):
        tab = ttk.Frame(notebook); notebook.add(tab, text="① 3후보 미리보기"); self.source_row(tab)
        row = ttk.Frame(tab); row.pack(fill="x", padx=16, pady=(4, 2))
        ttk.Label(row, text="채널", width=8).pack(side="left")
        ttk.Combobox(row, textvariable=self.channel, values=["Tokyo Chill", "OLD POP LOUNGE"], state="readonly", width=18).pack(side="left")
        ttk.Label(row, text="입력 유형", width=9).pack(side="left", padx=(12, 0))
        ttk.Combobox(row, textvariable=self.source_mode, values=["완성 썸네일(글자 보호)", "텍스트 없는 원본 이미지"], state="readonly", width=23).pack(side="left")
        ttk.Label(row, text="주인공", width=7).pack(side="left", padx=(12, 0))
        ttk.Combobox(row, textvariable=self.focus_mode, values=["자동", "왼쪽 인물", "오른쪽 인물", "두 사람"], state="readonly", width=12).pack(side="left")
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
        cards = ttk.Frame(tab); cards.pack(fill="both", expand=True, padx=10, pady=6)
        self.preview_labels, self.note_labels = [], []
        for index, title in enumerate(("A · PERSON", "B · EMOTION / MEMORY", "C · STORY / SCENERY")):
            card = ttk.LabelFrame(cards, text=title); card.grid(row=0, column=index, sticky="nsew", padx=5)
            image_label = ttk.Label(card, text="미리보기 대기", anchor="center"); image_label.pack(fill="both", expand=True, padx=5, pady=5)
            note = ttk.Label(card, text="", wraplength=330, justify="center"); note.pack(padx=5, pady=3)
            ttk.Button(card, text="이 후보만 저장", command=lambda i=index: self.save_one(i)).pack(pady=(2, 8))
            self.preview_labels.append(image_label); self.note_labels.append(note); cards.columnconfigure(index, weight=1)
        cards.rowconfigure(0, weight=1)
        ttk.Button(tab, text="3개 모두 저장", command=self.save_all).pack(pady=8, ipadx=30, ipady=5)

    def make_previews(self):
        if not self.src.get(): return messagebox.showwarning("확인", "이미지를 선택하세요.")
        def work():
            self.status.set("얼굴/구도를 분석하고 있습니다..."); self.update_idletasks()
            self.candidates = create_candidate_images(self.src.get(), self.channel.get(), self.source_mode.get(), self.focus_mode.get(), self.protagonist, self.counterpart); self.preview_refs.clear()
            for candidate, image_label, note_label in zip(self.candidates, self.preview_labels, self.note_labels):
                photo = ImageTk.PhotoImage(Image.fromarray(candidate.image[:, :, ::-1]).resize((340, 191), Image.Resampling.LANCZOS))
                self.preview_refs.append(photo); image_label.configure(image=photo, text=""); note_label.configure(text=candidate.composition)
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


def main():
    # Headless hook used only to validate the packaged engine on real Windows paths.
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
