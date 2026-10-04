"""Tk widgets for the Pro Editor: scrollable panels, numeric/colour fields and the live font browser."""
from __future__ import annotations

import math
import re
import tkinter as tk
from tkinter import colorchooser, ttk

import numpy as np
import skia
from PIL import Image, ImageTk

from typography.layer_renderer import shaped

from .fonts import SCRIPT_TABS, EditorSettings, filter_families, missing_glyphs

HEX = re.compile(r"^#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")


class ScrollableFrame(ttk.Frame):
    """Vertical scroll container; the mouse wheel scrolls whichever panel is under the pointer."""

    def __init__(self, parent, width: int = 300, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, width=width, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        for widget in (self.canvas, self.inner):
            widget.bind("<Enter>", lambda _e: self._wheel(True))
            widget.bind("<Leave>", lambda _e: self._wheel(False))

    def _wheel(self, active: bool) -> None:
        if active:
            self.canvas.bind_all("<MouseWheel>", self._on_wheel)
        else:
            self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event) -> None:
        if self.canvas.winfo_height() < self.inner.winfo_reqheight():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


class NumberField:
    """Slider + spinbox pair; ``on_change(value)`` fires on every slider move (live editing)."""

    def __init__(self, parent, row: int, label: str, low: float, high: float, value: float, on_change,
                 integer: bool = False, step: float | None = None, width: int = 150):
        self.integer = integer
        self.on_change = on_change
        self._guard = False
        self.var = tk.DoubleVar(value=value)
        self.text = tk.StringVar(value=self._format(value))
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(4, 2), pady=1)
        self.scale = ttk.Scale(parent, from_=low, to=high, variable=self.var, orient="horizontal", length=width,
                               command=lambda _v: self._from_scale())
        self.scale.grid(row=row, column=1, sticky="ew", padx=2, pady=1)
        self.spin = ttk.Spinbox(parent, textvariable=self.text, from_=low, to=high, width=7,
                                increment=step or (1 if integer else max(0.01, round((high - low) / 100, 2))),
                                command=self._from_spin)
        self.spin.grid(row=row, column=2, sticky="w", padx=(2, 4), pady=1)
        self.spin.bind("<Return>", lambda _e: self._from_spin())
        self.spin.bind("<FocusOut>", lambda _e: self._from_spin())

    def _format(self, value: float) -> str:
        return str(int(round(value))) if self.integer else f"{value:.2f}".rstrip("0").rstrip(".")

    def _from_scale(self) -> None:
        if self._guard:
            return
        value = self.value()
        self._guard = True
        try:
            self.text.set(self._format(value))
        finally:
            self._guard = False
        self.on_change(value)

    def _from_spin(self) -> None:
        try:
            value = float(self.text.get())
        except ValueError:
            return
        self._guard = True
        try:
            self.var.set(value)
        finally:
            self._guard = False
        self.on_change(int(round(value)) if self.integer else value)

    def value(self) -> float:
        value = float(self.var.get())
        return int(round(value)) if self.integer else round(value, 2)

    def set(self, value: float) -> None:
        self._guard = True
        try:
            self.var.set(value)
            self.text.set(self._format(value))
        finally:
            self._guard = False


class ColorField:
    def __init__(self, parent, row: int, label: str, value: str, on_change):
        self.on_change = on_change
        self._guard = False
        self.var = tk.StringVar(value=value)
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(4, 2), pady=1)
        frame = ttk.Frame(parent)
        frame.grid(row=row, column=1, columnspan=2, sticky="ew", padx=2, pady=1)
        self.swatch = tk.Label(frame, width=3, relief="solid", borderwidth=1, cursor="hand2")
        self.swatch.pack(side="left", padx=(0, 4))
        self.entry = ttk.Entry(frame, textvariable=self.var, width=10)
        self.entry.pack(side="left")
        self.swatch.bind("<Button-1>", lambda _e: self.choose())
        self.var.trace_add("write", lambda *_: self._changed())
        self._paint(value)

    def _paint(self, value: str) -> None:
        if HEX.match(value or ""):
            self.swatch.configure(background=value[:7])

    def _changed(self) -> None:
        value = self.var.get().strip()
        if HEX.match(value):
            self._paint(value)
            if not self._guard:
                self.on_change(value.upper())

    def choose(self) -> None:
        current = self.var.get()[:7] if HEX.match(self.var.get()) else "#FFFFFF"
        result = colorchooser.askcolor(color=current, parent=self.entry)
        if result and result[1]:
            self.var.set(result[1].upper())

    def set(self, value: str) -> None:
        self._guard = True
        try:
            self.var.set(value)
            self._paint(value)
        finally:
            self._guard = False


def render_font_sample(text: str, family: str, weight: int, channel: str, height: int = 40,
                       max_width: int = 230, color=(245, 245, 245)) -> Image.Image:
    """Draw the actual title text in a family with HarfBuzz shaping (fallback glyphs included)."""
    size = height * 0.72
    result = shaped(text, round(size, 2), channel, family, int(weight), 0.0)
    width = max(8, min(max_width, math.ceil(result.advance) + 8))
    mask = np.zeros((height, width), np.uint8)
    surface = skia.Surface(mask, colorType=skia.ColorType.kAlpha_8_ColorType)
    canvas = surface.getCanvas()
    paint = skia.Paint(AntiAlias=True, Color=skia.ColorWHITE)
    for run in result.runs:
        font = skia.Font(run.typeface, run.size)
        font.setSubpixel(True)
        builder = skia.TextBlobBuilder()
        builder.allocRunPos(font, run.glyphs, [skia.Point(px, py) for px, py in run.positions])
        blob = builder.make()
        if blob is not None:
            canvas.drawTextBlob(blob, 4, height * 0.74, paint)
    del canvas, surface
    rgb = np.zeros((height, width, 3), np.uint8)
    rgb[:] = (38, 40, 48)
    alpha = mask.astype(np.float32)[:, :, None] / 255.0
    rgb = (rgb * (1 - alpha) + np.array(color, np.float32) * alpha).astype(np.uint8)
    return Image.fromarray(rgb)


class FontBrowser(ttk.Frame):
    """Installed-font list that previews the *current title* in every family (lazy, cached)."""

    ROW = 52

    def __init__(self, parent, settings: EditorSettings, get_sample, on_pick, get_channel):
        super().__init__(parent)
        self.settings = settings
        self.get_sample = get_sample
        self.on_pick = on_pick
        self.get_channel = get_channel
        self.catalog = ()
        self.families = []
        self._photos: dict[tuple, ImageTk.PhotoImage] = {}
        self._pending_draw = None
        self.current_family = ""
        self.query = tk.StringVar()
        self.script = tk.StringVar(value="All")
        self.bold_first = tk.BooleanVar(value=True)
        self.only_favorites = tk.BooleanVar(value=False)
        top = ttk.Frame(self); top.pack(fill="x", padx=3, pady=(3, 1))
        ttk.Label(top, text="검색").pack(side="left")
        entry = ttk.Entry(top, textvariable=self.query, width=16); entry.pack(side="left", fill="x", expand=True, padx=3)
        tabs = ttk.Frame(self); tabs.pack(fill="x", padx=3)
        for value, label in zip(SCRIPT_TABS, ("일본어", "한국어", "Latin", "전체")):
            ttk.Radiobutton(tabs, text=label, value=value, variable=self.script,
                            command=self.refresh).pack(side="left", padx=1)
        options = ttk.Frame(self); options.pack(fill="x", padx=3)
        ttk.Checkbutton(options, text="Display/Bold 우선", variable=self.bold_first, command=self.refresh).pack(side="left")
        ttk.Checkbutton(options, text="★만", variable=self.only_favorites, command=self.refresh).pack(side="left", padx=4)
        ttk.Button(options, text="자동(채널 기본)", command=lambda: self._pick("")).pack(side="right")
        self.recent_frame = ttk.Frame(self); self.recent_frame.pack(fill="x", padx=3, pady=(2, 0))
        self.status = tk.StringVar(value="폰트 목록 준비 중…")
        ttk.Label(self, textvariable=self.status, foreground="#555").pack(fill="x", padx=4)
        body = ttk.Frame(self); body.pack(fill="both", expand=True, padx=3, pady=3)
        self.canvas = tk.Canvas(body, background="#26282f", highlightthickness=0, height=300)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self._yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", lambda _e: self._schedule_draw())
        self.canvas.bind("<Button-1>", self._click)
        self.canvas.bind("<MouseWheel>", lambda e: (self.canvas.yview_scroll(int(-e.delta / 120) * 2, "units"),
                                                    self._schedule_draw()))
        self.query.trace_add("write", lambda *_: self.refresh())

    def load_catalog(self, catalog) -> None:
        self.catalog = catalog
        self.refresh()

    def _yview(self, *args) -> None:
        self.canvas.yview(*args)
        self._schedule_draw()

    def refresh(self) -> None:
        if not self.catalog:
            return
        self.families = filter_families(self.catalog, self.script.get(), self.query.get(), self.bold_first.get(),
                                        self.settings.favorite_fonts, self.settings.recent_fonts,
                                        self.only_favorites.get())
        self.status.set(f"{len(self.families)}개 글꼴 · 클릭하면 선택 레이어에 즉시 적용 · ★ 즐겨찾기")
        self.canvas.configure(scrollregion=(0, 0, 10, max(1, len(self.families) * self.ROW)))
        self._draw_recent()
        self._schedule_draw()

    def invalidate_samples(self) -> None:
        self._photos.clear()
        self._schedule_draw()

    def _draw_recent(self) -> None:
        for child in self.recent_frame.winfo_children():
            child.destroy()
        if self.settings.recent_fonts:
            ttk.Label(self.recent_frame, text="최근:").pack(side="left")
            for family in self.settings.recent_fonts[:4]:
                ttk.Button(self.recent_frame, text=family[:14], width=min(14, len(family) + 1),
                           command=lambda f=family: self._pick(f)).pack(side="left", padx=1)

    def _schedule_draw(self) -> None:
        if self._pending_draw is None:
            self._pending_draw = self.after(15, self._draw)

    def _draw(self) -> None:
        self._pending_draw = None
        canvas = self.canvas
        canvas.delete("all")
        if not self.families:
            return
        top = canvas.canvasy(0)
        height = max(1, canvas.winfo_height())
        width = max(200, canvas.winfo_width())
        first = max(0, int(top // self.ROW))
        last = min(len(self.families), int((top + height) // self.ROW) + 2)
        sample = (self.get_sample() or "Aa あ 한").strip().replace("\n", " ")[:18]
        channel = self.get_channel()
        rendered = 0
        for index in range(first, last):
            family = self.families[index]
            y = index * self.ROW
            selected = family.name == self.current_family
            canvas.create_rectangle(0, y, width, y + self.ROW - 1, fill="#3a4a66" if selected else "#26282f",
                                    outline="#30333b")
            favorite = family.name in self.settings.favorite_fonts
            canvas.create_text(width - 14, y + 14, text="★" if favorite else "☆", fill="#FFD34D",
                               font=("Segoe UI", 12), tags=("star",))
            missing = missing_glyphs(family.name, sample)
            label = f"{family.name}  ·  {family.scripts}  ·  {'/'.join(str(w) for w in family.weights)}"
            canvas.create_text(6, y + 4, anchor="nw", text=label, fill="#c9ccd6", font=("Segoe UI", 8))
            if missing:
                canvas.create_text(width - 30, y + 36, anchor="e", text=f"⚠ 대체 {len(missing)}자", fill="#ffb347",
                                   font=("Segoe UI", 8))
            key = (family.name, sample, channel)
            photo = self._photos.get(key)
            if photo is None and rendered < 10:
                weight = max(family.weights) if self.bold_first.get() else 700
                photo = ImageTk.PhotoImage(render_font_sample(sample, family.name, weight, channel, 30,
                                                              max(120, width - 70)))
                self._photos[key] = photo
                rendered += 1
            if photo is not None:
                canvas.create_image(4, y + 18, anchor="nw", image=photo)
            else:
                canvas.create_text(8, y + 30, anchor="w", text="…", fill="#888")
        if rendered >= 10:
            self._schedule_draw()  # keep filling the visible rows without blocking the UI

    def _click(self, event) -> None:
        y = self.canvas.canvasy(event.y)
        index = int(y // self.ROW)
        if not 0 <= index < len(self.families):
            return
        family = self.families[index].name
        if event.x > self.canvas.winfo_width() - 28 and (y % self.ROW) < 28:
            self.settings.toggle_favorite_font(family)
            self.refresh()
            return
        self._pick(family)

    def _pick(self, family: str) -> None:
        self.current_family = family
        if family:
            self.settings.use_font(family)
            self._draw_recent()
        self.on_pick(family)
        self._schedule_draw()

    def pick_index(self, index: int) -> None:
        """Test/automation hook: apply the n-th visible family."""
        if 0 <= index < len(self.families):
            self._pick(self.families[index].name)
