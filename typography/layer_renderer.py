"""Skia/HarfBuzz compositor for layer documents.

The editor canvas, the 340/180 px previews and the final export all call
``LayerRenderer.render`` so the preview is the export (WYSIWYG).  Text and badge
layers are rasterized once per visual property set and cached, so moving or
rotating a layer only re-composites cached rasters.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping

import cv2
import numpy as np
import skia

from .font_registry import get_font_registry
from .linebreak_engine import score_line_breaks
from .shaping_engine import ShapedRun, ShapedText, shape_text

_CACHE_EXCLUDED = {"id", "name", "role", "visible", "locked", "z_index", "x", "y", "rotation", "opacity"}
ASCENT = 0.88
DESCENT = 0.24


def color(value: str, alpha: float = 1.0) -> int:
    text = (value or "#000000").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) == 8:
        alpha *= int(text[6:8], 16) / 255.0
        text = text[:6]
    try:
        red, green, blue = (int(text[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        red = green = blue = 0
    return skia.ColorSetARGB(int(round(max(0.0, min(1.0, alpha)) * 255)), red, green, blue)


REFERENCE_SIZE = 100.0


@lru_cache(maxsize=8192)
def _reference_shape(text: str, channel: str, family: str, weight: int) -> ShapedText:
    return shape_text(text, REFERENCE_SIZE, channel, family or None, int(weight), 0.0,
                      kerning=True, ligatures=True, registry=get_font_registry())


@lru_cache(maxsize=8192)
def shaped(text: str, size: float, channel: str, family: str, weight: int, spacing: float) -> ShapedText:
    """HarfBuzz shaping is unhinted (scale = upem), so glyph positions scale linearly with
    size; shape once at a reference size and derive every size/tracking from it."""
    reference = _reference_shape(text, channel, family or "", int(weight))
    scale = float(size) / REFERENCE_SIZE
    runs = []
    extra = 0.0
    for run in reference.runs:
        positions = tuple((px * scale + extra + index * spacing, py * scale)
                          for index, (px, py) in enumerate(run.positions))
        advance = run.advance * scale + max(0, len(run.glyphs) - 1) * spacing
        extra += max(0, len(run.glyphs) - 1) * spacing
        runs.append(ShapedRun(run.text, run.face, run.glyphs, positions, advance, float(size), run.typeface))
    return ShapedText(text, tuple(runs), sum(run.advance for run in runs))


def _segments(line: str, word: str) -> list[tuple[str, bool]]:
    if not word or word not in line:
        return [(line, False)]
    parts: list[tuple[str, bool]] = []
    rest = line
    while word in rest:
        before, _, rest = rest.partition(word)
        if before:
            parts.append((before, False))
        parts.append((word, True))
    if rest:
        parts.append((rest, False))
    return parts


@dataclass(frozen=True)
class TextLayout:
    lines: tuple[str, ...]
    line_widths: tuple[float, ...]
    font_size: float
    line_step: float
    content_height: float
    families: tuple[str, ...]
    fallback_chars: tuple[str, ...]


def _line_width(layer, line: str) -> float:
    total = 0.0
    for segment, highlighted in _segments(line, layer.highlight_word):
        size = layer.font_size * (layer.highlight_scale if highlighted else 1.0)
        total += shaped(segment, round(size, 2), layer.channel, layer.font_family,
                        layer.font_weight, float(layer.letter_spacing)).advance
    return total


@lru_cache(maxsize=1024)
def _layout_cached(text, channel, family, weight, size, spacing, line_spacing, width,
                   max_lines, manual, highlight_word, highlight_scale) -> TextLayout:
    class _Spec:  # light adapter so _line_width can be shared with the drawing pass
        pass
    spec = _Spec()
    spec.channel, spec.font_family, spec.font_weight = channel, family, weight
    spec.font_size, spec.letter_spacing = size, spacing
    spec.highlight_word, spec.highlight_scale = highlight_word, highlight_scale
    if manual and "\n" in text:
        lines = tuple(" ".join(line.split()) for line in text.splitlines() if line.strip()) or ("",)
    else:
        normalized = " ".join(text.split())
        measure = lambda line: _line_width(spec, line)
        choices = score_line_breaks(normalized, measure, max(1.0, width), max(1, int(max_lines)))
        lines = choices[0].lines
        # The shared scorer never proposes a single line; a title that fits on one line keeps it
        # unless a multi-line split scores clearly better (same weights as the scorer).
        single_ratio = measure(normalized) / max(1.0, width)
        if single_ratio <= 1.0 and single_ratio * single_ratio * 0.8 <= choices[0].score:
            lines = (normalized,)
    widths = tuple(_line_width(spec, line) for line in lines)
    step = size * line_spacing
    families: set[str] = set()
    fallback: list[str] = []
    preferred = " ".join((family or "").casefold().split())
    for line in lines:
        for run in shaped(line, round(size, 2), channel, family, weight, spacing).runs:
            families.add(run.face.family)
            if preferred and " ".join(run.face.family.casefold().split()) != preferred:
                fallback.extend(ch for ch in run.text if not ch.isspace())
    content = (len(lines) - 1) * step + size * (ASCENT + DESCENT)
    return TextLayout(lines, widths, size, step, content, tuple(sorted(families)),
                      tuple(dict.fromkeys(fallback)))


def layout_text(layer) -> TextLayout:
    return _layout_cached(layer.text or "", layer.channel, layer.font_family or "", int(layer.font_weight),
                          round(float(layer.font_size), 2), float(layer.letter_spacing),
                          float(layer.line_spacing), round(float(layer.width), 1), int(layer.max_lines),
                          bool(layer.manual_line_breaks), layer.highlight_word or "",
                          float(layer.highlight_scale))


def _effect_pad(layer) -> float:
    outline = max(0.0, layer.outline_width) / 2 + max(0.0, layer.secondary_outline_width)
    glow = layer.glow_blur * 1.6 if layer.glow_opacity > 0 else 0.0
    shadow = (max(abs(layer.shadow_x), abs(layer.shadow_y)) + layer.shadow_blur * 1.6) if layer.shadow_opacity > 0 else 0.0
    return outline + max(glow, shadow) + 4


@dataclass
class _Raster:
    """Premultiplied BGRA patch at 1x; (left, top) is its offset from the layer box origin."""
    pixels: np.ndarray
    left: int
    top: int


def _skia_patch(left: float, top: float, right: float, bottom: float, supersample: int, draw) -> _Raster:
    left, top = math.floor(left), math.floor(top)
    width, height = max(1, math.ceil(right - left)), max(1, math.ceil(bottom - top))
    buffer = np.zeros((height * supersample, width * supersample, 4), dtype=np.uint8)
    surface = skia.Surface(buffer, colorType=skia.ColorType.kBGRA_8888_ColorType,
                           alphaType=skia.AlphaType.kPremul_AlphaType)
    canvas = surface.getCanvas()
    canvas.scale(supersample, supersample)
    canvas.translate(-left, -top)
    draw(canvas)
    del canvas, surface
    if supersample > 1:
        buffer = cv2.resize(buffer, (width, height), interpolation=cv2.INTER_AREA)
    return _Raster(buffer, left, top)


def _blobs_for_line(layer, line: str, start_x: float, baseline: float):
    cursor = start_x
    out = []
    for segment, highlighted in _segments(line, layer.highlight_word):
        size = round(layer.font_size * (layer.highlight_scale if highlighted else 1.0), 2)
        result = shaped(segment, size, layer.channel, layer.font_family, layer.font_weight,
                        float(layer.letter_spacing))
        for run in result.runs:
            font = skia.Font(run.typeface, run.size)
            font.setSubpixel(True)
            font.setEdging(skia.Font.Edging.kAntiAlias)
            builder = skia.TextBlobBuilder()
            builder.allocRunPos(font, run.glyphs, [skia.Point(px, py) for px, py in run.positions])
            blob = builder.make()
            if blob is not None:
                out.append((blob, cursor, baseline, highlighted, size))
        cursor += result.advance
    return out


def _rasterize_text(layer, supersample: int) -> _Raster:
    layout = layout_text(layer)
    width, height = float(layer.width), float(layer.height)
    top = (height - layout.content_height) / 2
    blobs = []
    extents = [0.0, 0.0, width, height]
    for index, (line, line_width) in enumerate(zip(layout.lines, layout.line_widths)):
        if layer.alignment == "center":
            x = (width - line_width) / 2
        elif layer.alignment == "right":
            x = width - line_width
        else:
            x = 0.0
        baseline = top + layout.font_size * ASCENT + index * layout.line_step
        blobs.extend(_blobs_for_line(layer, line, x, baseline))
        extents[0] = min(extents[0], x); extents[2] = max(extents[2], x + line_width)
        extents[1] = min(extents[1], baseline - layout.font_size * ASCENT * 1.1)
        extents[3] = max(extents[3], baseline + layout.font_size * DESCENT)
    pad = _effect_pad(layer)
    left, top_e = math.floor(extents[0] - pad), math.floor(extents[1] - pad)
    width_px = max(1, math.ceil(extents[2] + pad - left))
    height_px = max(1, math.ceil(extents[3] + pad - top_e))
    ss = max(1, int(supersample))
    outline = max(0.0, float(layer.outline_width))
    secondary = max(0.0, float(layer.secondary_outline_width))
    total_stroke = outline + 2 * secondary

    def mask(selector, stroke: float) -> np.ndarray:
        """Skia A8 coverage of the selected glyph blobs (fill, or fill + round-joined stroke)."""
        buffer = np.zeros((height_px * ss, width_px * ss), np.uint8)
        surface = skia.Surface(buffer, colorType=skia.ColorType.kAlpha_8_ColorType)
        canvas = surface.getCanvas()
        canvas.scale(ss, ss); canvas.translate(-left, -top_e)
        paint = skia.Paint(AntiAlias=True, Color=skia.ColorWHITE)
        if stroke > 0:
            paint.setStyle(skia.Paint.kStrokeAndFill_Style)
            paint.setStrokeWidth(stroke); paint.setStrokeJoin(skia.Paint.kRound_Join)
        for blob, x, y, highlighted, _size in blobs:
            if selector(highlighted):
                canvas.drawTextBlob(blob, x, y, paint)
        del canvas, surface
        if ss > 1:
            buffer = cv2.resize(buffer, (width_px, height_px), interpolation=cv2.INTER_AREA)
        return buffer.astype(np.float32) / 255.0

    every = lambda _highlighted: True
    plain_fill = mask(lambda highlighted: not highlighted, 0.0)
    highlight_fill = mask(lambda highlighted: highlighted, 0.0) if layer.highlight_word else None
    outline_mask = mask(every, outline) if outline > 0 else None
    outer_mask = mask(every, total_stroke) if secondary > 0 else None
    silhouette = outer_mask if outer_mask is not None else (outline_mask if outline_mask is not None else
                 np.maximum(plain_fill, highlight_fill) if highlight_fill is not None else plain_fill)

    # Premultiplied B, G, R, A planes in 0..1; per-plane cv2 ops are SIMD and allocation-light.
    planes = [np.zeros((height_px, width_px), np.float32) for _ in range(4)]

    def over(coverage: np.ndarray, rgb: tuple[float, float, float] | np.ndarray, alpha: float = 1.0):
        a = coverage if alpha >= 1.0 else cv2.multiply(coverage, alpha)
        inverse = cv2.subtract(1.0, a)
        for index in range(4):
            cv2.multiply(planes[index], inverse, dst=planes[index])
            if index == 3:
                cv2.add(planes[index], a, dst=planes[index])
            elif isinstance(rgb, np.ndarray):  # per-row gradient colours, shape (rows, 1, 3)
                cv2.add(planes[index], a * rgb[:, :, index], dst=planes[index])
            elif rgb[index] > 0:
                cv2.scaleAdd(a, float(rgb[index]), planes[index], dst=planes[index])

    def bgr(value: str) -> tuple[float, float, float]:
        b, g, r, _a = _bgra(value)
        return b / 255.0, g / 255.0, r / 255.0

    if layer.glow_opacity > 0 and layer.glow_blur > 0:
        spread = max(1, round(layer.glow_blur * 0.25))
        glow = cv2.dilate(silhouette, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * spread + 1, 2 * spread + 1)))
        glow = cv2.GaussianBlur(glow, (0, 0), max(0.5, layer.glow_blur * 0.5))
        over(np.clip(glow * 1.25, 0, 1), bgr(layer.glow_color), float(layer.glow_opacity))
    if layer.shadow_opacity > 0:
        shift = np.float32([[1, 0, float(layer.shadow_x)], [0, 1, float(layer.shadow_y)]])
        shadow = cv2.warpAffine(silhouette, shift, (width_px, height_px), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        if layer.shadow_blur > 0:
            shadow = cv2.GaussianBlur(shadow, (0, 0), max(0.5, layer.shadow_blur * 0.5))
        over(shadow, bgr(layer.shadow_color), float(layer.shadow_opacity))
    if outer_mask is not None:
        over(outer_mask, bgr(layer.secondary_outline_color))
    if outline_mask is not None:
        over(outline_mask, bgr(layer.outline_color))
    if layer.gradient:
        ramp = np.zeros(height_px, np.float32)
        rows = np.arange(height_px, dtype=np.float32) + top_e + 0.5
        for index in range(len(layout.lines)):
            baseline = top + layout.font_size * ASCENT + index * layout.line_step
            line_top = baseline - layout.font_size * ASCENT * 0.95
            line_bottom = baseline + layout.font_size * DESCENT * 0.4
            inside = (rows >= line_top - layout.line_step * 0.5) & (rows < line_bottom + layout.line_step * 0.5)
            ramp[inside] = np.clip((rows[inside] - line_top) / max(1.0, line_bottom - line_top), 0, 1)
        start, end = np.array(bgr(layer.fill), np.float32), np.array(bgr(layer.gradient_end), np.float32)
        colors = (start[None, :] * (1 - ramp[:, None]) + end[None, :] * ramp[:, None])[:, None, :]
        over(plain_fill, colors)
    else:
        over(plain_fill, bgr(layer.fill))
    if highlight_fill is not None:
        over(highlight_fill, bgr(layer.highlight_color))
    pixels = cv2.convertScaleAbs(cv2.merge(planes), alpha=255.0)
    return _Raster(pixels, left, top_e)


def _badge_path(shape: str, w: float, h: float, radius: float) -> skia.Path:
    path = skia.Path()
    if shape == "ribbon":
        tip = min(h * 0.38, w * 0.3)
        path.moveTo(0, 0); path.lineTo(w - tip, 0); path.lineTo(w, h / 2)
        path.lineTo(w - tip, h); path.lineTo(0, h); path.close()
    elif shape == "tag":
        notch = min(h * 0.32, w * 0.25)
        path.moveTo(notch, 0); path.lineTo(w, 0); path.lineTo(w, h); path.lineTo(notch, h)
        path.lineTo(0, h / 2); path.close()
    else:
        r = h / 2 if shape == "pill" else (min(radius, h / 2) if shape in ("rounded", "sticker") else 0)
        path.addRRect(skia.RRect.MakeRectXY(skia.Rect.MakeWH(w, h), r, r))
    return path


def _rasterize_badge(layer, supersample: int) -> _Raster:
    w, h = max(4.0, float(layer.width)), max(4.0, float(layer.height))
    pad = max(0.0, layer.border_width) + (8 if layer.shape == "sticker" else 2)
    return _skia_patch(-pad, -pad, w + pad, h + pad, supersample, lambda canvas: _draw_badge(canvas, layer, w, h))


def _draw_badge(canvas, layer, w: float, h: float) -> None:
    path = _badge_path(layer.shape, w, h, layer.radius)
    if layer.shape == "sticker":
        shadow = skia.Paint(AntiAlias=True, Color=color("#000000", 0.45))
        shadow.setMaskFilter(skia.MaskFilter.MakeBlur(skia.BlurStyle.kNormal_BlurStyle, 3))
        canvas.save(); canvas.translate(2, 3); canvas.drawPath(path, shadow); canvas.restore()
    canvas.drawPath(path, skia.Paint(AntiAlias=True, Color=color(layer.fill)))
    if layer.border_width > 0:
        border = skia.Paint(AntiAlias=True, Color=color(layer.border_color), Style=skia.Paint.kStroke_Style,
                            StrokeWidth=float(layer.border_width))
        canvas.drawPath(path, border)
    text = " ".join((layer.text or "").split())
    if text:
        inner = w - 2 * layer.padding - (h * 0.3 if layer.shape in ("ribbon", "tag") else 0)
        size = float(layer.font_size)
        result = shaped(text, round(size, 2), layer.channel, layer.font_family, layer.font_weight, 0.0)
        while result.advance > inner and size > 9:
            size *= 0.92
            result = shaped(text, round(size, 2), layer.channel, layer.font_family, layer.font_weight, 0.0)
        offset = h * 0.15 if layer.shape == "tag" else (-h * 0.12 if layer.shape == "ribbon" else 0.0)
        x = (w - result.advance) / 2 + offset
        baseline = h / 2 + size * (ASCENT - DESCENT) / 2
        paint = skia.Paint(AntiAlias=True, Color=color(layer.text_color))
        for run in result.runs:
            font = skia.Font(run.typeface, run.size); font.setSubpixel(True)
            builder = skia.TextBlobBuilder()
            builder.allocRunPos(font, run.glyphs, [skia.Point(px, py) for px, py in run.positions])
            blob = builder.make()
            if blob is not None:
                canvas.drawTextBlob(blob, x, baseline, paint)


def read_image_any(path: str | Path) -> np.ndarray | None:
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(data, cv2.IMREAD_UNCHANGED)
    except (OSError, ValueError):
        return None


def _bgra(value: str, alpha: float = 1.0) -> tuple[int, int, int, float]:
    argb = color(value, alpha)
    return argb & 0xFF, (argb >> 8) & 0xFF, (argb >> 16) & 0xFF, ((argb >> 24) & 0xFF) / 255.0


def _premultiply(array: np.ndarray) -> np.ndarray:
    """BGR/BGRA/gray image -> premultiplied BGRA uint8."""
    if array.ndim == 2:
        array = cv2.cvtColor(array, cv2.COLOR_GRAY2BGR)
    if array.shape[2] == 3:
        return cv2.cvtColor(array, cv2.COLOR_BGR2BGRA)
    alpha = array[:, :, 3:4].astype(np.float32) / 255.0
    out = array.copy()
    out[:, :, :3] = (array[:, :, :3].astype(np.float32) * alpha).astype(np.uint8)
    return out


def _rounded_mask(width: int, height: int, radius: float, inset: float = 0.0, shape: str = "rounded") -> np.ndarray:
    """Anti-aliased coverage (float32 0..1) of a rounded rect / ellipse via signed distance."""
    ys = np.arange(height, dtype=np.float32)[:, None] + 0.5
    xs = np.arange(width, dtype=np.float32)[None, :] + 0.5
    hw, hh = width / 2 - inset, height / 2 - inset
    if hw <= 0 or hh <= 0:
        return np.zeros((height, width), np.float32)
    dx, dy = np.abs(xs - width / 2), np.abs(ys - height / 2)
    if shape == "ellipse":
        nx, ny = dx / hw, dy / hh
        dist = (np.sqrt(nx * nx + ny * ny) - 1.0) * min(hw, hh)
    else:
        r = max(0.0, min(radius, hw, hh))
        qx, qy = dx - (hw - r), dy - (hh - r)
        outside = np.sqrt(np.maximum(qx, 0) ** 2 + np.maximum(qy, 0) ** 2)
        dist = outside + np.minimum(np.maximum(qx, qy), 0) - r
    return np.clip(0.5 - dist, 0.0, 1.0).astype(np.float32)


def _solid_patch(mask: np.ndarray, bgra: tuple[int, int, int, float]) -> np.ndarray:
    b, g, r, a = bgra
    alpha = mask * a
    patch = np.empty(mask.shape + (4,), np.uint8)
    patch[:, :, 0] = (alpha * b).astype(np.uint8); patch[:, :, 1] = (alpha * g).astype(np.uint8)
    patch[:, :, 2] = (alpha * r).astype(np.uint8); patch[:, :, 3] = (alpha * 255).astype(np.uint8)
    return patch


def _over(top: np.ndarray, bottom: np.ndarray) -> np.ndarray:
    inverse = 255 - top[:, :, 3:4].astype(np.uint16)
    return (top.astype(np.uint16) + (bottom.astype(np.uint16) * inverse + 127) // 255).clip(0, 255).astype(np.uint8)


def _shape_raster(layer) -> _Raster:
    w, h = max(1, round(layer.width)), max(1, round(layer.height))
    kind = "ellipse" if layer.shape == "ellipse" else "rounded"
    radius = float(layer.radius) if layer.shape == "rounded" else 0.0
    fill = _rounded_mask(w, h, radius, 0.0, kind)
    patch = _solid_patch(fill, _bgra(layer.fill))
    if layer.border_width > 0:
        inner = _rounded_mask(w, h, max(0.0, radius - layer.border_width), float(layer.border_width), kind)
        border = _solid_patch(np.clip(fill - inner, 0.0, 1.0), _bgra(layer.border_color))
        patch = _over(border, patch)
    return _Raster(patch, 0, 0)


def _overlay_raster(layer) -> _Raster:
    w, h = max(1, round(layer.width)), max(1, round(layer.height))
    soft = max(0.0, float(layer.blur)) * 0.5
    pad = math.ceil(soft * 2.5) if layer.kind != "label_strip" and soft > 0 else 0
    radius = min(float(layer.radius), 8.0) if layer.kind == "label_strip" else float(layer.radius)
    mask = _rounded_mask(w, h, radius)
    strength = max(0.0, min(1.0, float(layer.strength)))
    ys = (np.arange(h, dtype=np.float32)[:, None] + 0.5) / h
    xs = (np.arange(w, dtype=np.float32)[None, :] + 0.5) / w
    if layer.kind in ("gradient_black", "gradient_white"):
        if layer.direction == "center":
            t = np.sqrt(((xs - 0.5) * 2) ** 2 + ((ys - 0.5) * 2) ** 2)
        else:
            t = {"bottom": 1 - ys, "top": ys, "left": xs, "right": 1 - xs}.get(layer.direction, 1 - ys)
            t = np.broadcast_to(t, (h, w))
        mask = mask * np.interp(t, (0.0, 0.45, 1.0), (1.0, 0.55, 0.0)).astype(np.float32)
    elif layer.kind == "vignette":
        r = np.sqrt((xs - 0.5) ** 2 + (ys - 0.5) ** 2) / math.sqrt(0.5)
        mask = mask * np.interp(r, (0.0, 0.42, 1.0), (0.0, 0.0, 1.0)).astype(np.float32)
    if pad:
        mask = cv2.copyMakeBorder(mask, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
        mask = cv2.GaussianBlur(mask, (0, 0), soft)
    default = "#FFFFFF" if layer.kind == "gradient_white" else "#000000"
    return _Raster(_solid_patch(mask, _bgra(layer.color or default, strength)), -pad, -pad)


def _blend_into(target: np.ndarray, patch: np.ndarray, x: int, y: int, opacity: float = 1.0) -> None:
    """Premultiplied source-over of a BGRA patch onto a BGR canvas at an integer offset."""
    th, tw = target.shape[:2]
    ph, pw = patch.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(tw, x + pw), min(th, y + ph)
    if x1 <= x0 or y1 <= y0:
        return
    src = patch[y0 - y:y1 - y, x0 - x:x1 - x]
    if opacity < 0.999:
        src = cv2.multiply(src, (opacity, opacity, opacity, opacity), dtype=cv2.CV_8U)
    alpha = src[:, :, 3]
    if not alpha.any():
        return
    region = target[y0:y1, x0:x1]
    inverse = cv2.merge((255 - alpha,) * 3)
    target[y0:y1, x0:x1] = cv2.add(src[:, :, :3], cv2.multiply(region, inverse, scale=1 / 255.0))


def _place_matrix(layer, raster: _Raster) -> np.ndarray:
    """Affine map from patch pixels to canvas pixels (rotation about the layer centre)."""
    cx, cy = layer.center
    angle = math.radians(float(layer.rotation))
    cos, sin = math.cos(angle), math.sin(angle)
    ox = raster.left - float(layer.width) / 2
    oy = raster.top - float(layer.height) / 2
    return np.array([[cos, -sin, cx + cos * ox - sin * oy],
                     [sin, cos, cy + sin * ox + cos * oy]], dtype=np.float64)


def _warp_patch(layer, raster: _Raster, canvas_size: tuple[int, int]):
    """Return (patch, x, y) in canvas space; rotation warps the premultiplied patch bilinearly."""
    patch = raster.pixels
    if not layer.rotation:
        cx, cy = layer.center
        return patch, round(cx - layer.width / 2 + raster.left), round(cy - layer.height / 2 + raster.top)
    matrix = _place_matrix(layer, raster)
    ph, pw = patch.shape[:2]
    corners = np.array([[0, 0, 1], [pw, 0, 1], [0, ph, 1], [pw, ph, 1]], dtype=np.float64) @ matrix.T
    x0 = max(0, math.floor(corners[:, 0].min())); y0 = max(0, math.floor(corners[:, 1].min()))
    x1 = min(canvas_size[0], math.ceil(corners[:, 0].max())); y1 = min(canvas_size[1], math.ceil(corners[:, 1].max()))
    if x1 <= x0 or y1 <= y0:
        return None, 0, 0
    shifted = matrix.copy(); shifted[0, 2] -= x0; shifted[1, 2] -= y0
    warped = cv2.warpAffine(patch, shifted, (x1 - x0, y1 - y0), flags=cv2.INTER_LINEAR,
                            borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
    return warped, x0, y0


class LayerRenderer:
    """Composites ``ThumbnailDocument`` layers; shared by the editor canvas, previews and export.

    Glyphs and badges are vector-rendered by Skia/HarfBuzz into cached premultiplied
    patches. Compositing, rotation and soft overlays use OpenCV (this Skia wheel's CPU
    blend path is ~20x slower), so a drag only re-blends cached patches.
    """

    def __init__(self, supersample: int = 1, cache_size: int = 160):
        self.supersample = supersample
        self.cache_size = cache_size
        self._rasters: OrderedDict[tuple, _Raster] = OrderedDict()
        self._fitted: OrderedDict[tuple, _Raster] = OrderedDict()
        self._files: dict[str, np.ndarray | None] = {}
        self.stats = {"raster_hits": 0, "raster_misses": 0}

    @staticmethod
    def raster_key(layer) -> tuple:
        values = layer.to_dict()
        return tuple(sorted((key, value) for key, value in values.items() if key not in _CACHE_EXCLUDED))

    def _remember(self, cache: OrderedDict, key, value):
        cache[key] = value
        while len(cache) > self.cache_size:
            cache.popitem(last=False)
        return value

    def raster(self, layer) -> _Raster:
        key = self.raster_key(layer)
        cached = self._rasters.get(key)
        if cached is not None:
            self._rasters.move_to_end(key)
            self.stats["raster_hits"] += 1
            return cached
        self.stats["raster_misses"] += 1
        if layer.type == "text":
            raster = _rasterize_text(layer, self.supersample)
        elif layer.type == "badge":
            raster = _rasterize_badge(layer, self.supersample)
        elif layer.type == "shape":
            raster = _shape_raster(layer)
        else:
            raster = _overlay_raster(layer)
        return self._remember(self._rasters, key, raster)

    def source_array(self, source: str, images: Mapping[str, np.ndarray]) -> np.ndarray | None:
        array = images.get(source) if source else None
        if array is None and source and not source.startswith("asset://"):
            if source not in self._files:
                self._files[source] = read_image_any(source)
            array = self._files[source]
        return array

    def _picture_raster(self, layer, images) -> _Raster | None:
        array = self.source_array(layer.source, images)
        if array is None:
            return None
        w, h = max(1, round(layer.width)), max(1, round(layer.height))
        fit = getattr(layer, "fit", "cover")
        key = (layer.source, array.shape, array.__array_interface__["data"][0], w, h, fit)
        cached = self._fitted.get(key)
        if cached is not None:
            self._fitted.move_to_end(key)
            return cached
        ih, iw = array.shape[:2]
        left = top = 0
        if fit == "stretch":
            fitted = cv2.resize(array, (w, h), interpolation=cv2.INTER_AREA)
        elif fit == "contain":
            scale = min(w / iw, h / ih)
            fw, fh = max(1, round(iw * scale)), max(1, round(ih * scale))
            fitted = cv2.resize(array, (fw, fh), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
            left, top = (w - fw) // 2, (h - fh) // 2
        else:
            scale = max(w / iw, h / ih)
            sw, sh = w / scale, h / scale
            sx, sy = int((iw - sw) / 2), int((ih - sh) / 2)
            crop = array[sy:sy + max(1, round(sh)), sx:sx + max(1, round(sw))]
            if crop.shape[1] == w and crop.shape[0] == h:
                fitted = crop.copy()
            else:
                fitted = cv2.resize(crop, (w, h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        return self._remember(self._fitted, key, _Raster(_premultiply(fitted), left, top))

    def _blur_plate(self, canvas: np.ndarray, layer) -> None:
        w, h = max(1, round(layer.width)), max(1, round(layer.height))
        mask = _rounded_mask(w, h, float(layer.radius))
        coverage_patch = np.dstack([(mask * 255).astype(np.uint8)] * 4)
        warped, x, y = _warp_patch(layer, _Raster(coverage_patch, 0, 0), (canvas.shape[1], canvas.shape[0]))
        if warped is None:
            return
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(canvas.shape[1], x + warped.shape[1]), min(canvas.shape[0], y + warped.shape[0])
        if x1 <= x0 or y1 <= y0:
            return
        sigma = max(0.8, float(layer.blur) * 0.7)
        margin = math.ceil(sigma * 3)
        gx0, gy0 = max(0, x0 - margin), max(0, y0 - margin)
        gx1, gy1 = min(canvas.shape[1], x1 + margin), min(canvas.shape[0], y1 + margin)
        blurred = cv2.GaussianBlur(canvas[gy0:gy1, gx0:gx1], (0, 0), sigma)[y0 - gy0:y1 - gy0, x0 - gx0:x1 - gx0]
        coverage = warped[y0 - y:y1 - y, x0 - x:x1 - x, 3:4].astype(np.float32) / 255.0
        coverage *= max(0.0, min(1.0, float(layer.opacity)))
        region = canvas[y0:y1, x0:x1].astype(np.float32)
        canvas[y0:y1, x0:x1] = (blurred * coverage + region * (1 - coverage)).astype(np.uint8)
        tint = _solid_patch(mask, _bgra(layer.color, max(0.0, min(1.0, float(layer.strength))) * 0.35))
        warped_tint, tx, ty = _warp_patch(layer, _Raster(tint, 0, 0), (canvas.shape[1], canvas.shape[0]))
        if warped_tint is not None:
            _blend_into(canvas, warped_tint, tx, ty, float(layer.opacity))

    def _signature(self, layers, images, background_color: str) -> tuple:
        parts = [background_color]
        for layer in layers:
            if layer.type in ("background", "image"):
                array = self.source_array(layer.source, images)
                content = (layer.source, getattr(layer, "fit", ""),
                           None if array is None else (array.shape, array.__array_interface__["data"][0]))
            else:
                content = self.raster_key(layer)
            parts.append((layer.id, content, layer.visible, layer.x, layer.y, layer.width, layer.height,
                          layer.rotation, layer.opacity))
        return tuple(parts)

    def render(self, document, images: Mapping[str, np.ndarray] | None = None, *,
               skip_ids=(), background_color: str = "#101114", split_at: str | None = None) -> np.ndarray:
        """Render visible layers at document size; returns BGR uint8 (identical for preview/export).

        ``split_at`` (the layer being edited) reuses a cached composite of every layer below it,
        which is pixel-identical to compositing them again.
        """
        images = images or {}
        size = (int(document.canvas_width), int(document.canvas_height))
        ordered = document.ordered()
        index = next((i for i, layer in enumerate(ordered) if layer.id == split_at), None) if split_at else None
        if index and not skip_ids:
            below = ordered[:index]
            signature = self._signature(below, images, background_color) + (size,)
            if getattr(self, "_below_signature", None) != signature:
                self._below_canvas = self.render(_LayerView(document, below), images,
                                                 background_color=background_color)
                self._below_signature = signature
            canvas = self._below_canvas.copy()
            return self._composite(canvas, ordered[index:], images, size, skip_ids)
        b, g, r, _a = _bgra(background_color)
        canvas = np.empty((size[1], size[0], 3), np.uint8)
        canvas[:] = (b, g, r)
        return self._composite(canvas, ordered, images, size, skip_ids)

    def _composite(self, canvas: np.ndarray, layers, images, size, skip_ids) -> np.ndarray:
        for layer in layers:
            if not layer.visible or layer.id in skip_ids or layer.opacity <= 0:
                continue
            if layer.type == "overlay" and layer.kind == "blur_plate":
                self._blur_plate(canvas, layer)
                continue
            if layer.type in ("background", "image"):
                raster = self._picture_raster(layer, images)
                if raster is None:
                    continue
                pixels = raster.pixels
                if (layer.type == "background" and not layer.rotation and layer.opacity >= 0.999
                        and round(layer.x) == 0 and round(layer.y) == 0 and raster.left == 0 and raster.top == 0
                        and pixels.shape[:2] == canvas.shape[:2] and bool((pixels[:, :, 3] == 255).all())):
                    canvas[:] = pixels[:, :, :3]
                    continue
            else:
                raster = self.raster(layer)
            patch, x, y = _warp_patch(layer, raster, size)
            if patch is not None:
                _blend_into(canvas, patch, x, y, max(0.0, min(1.0, float(layer.opacity))))
        return canvas


class _LayerView:
    """Document stand-in exposing a subset of layers (used for the below-selection cache)."""

    def __init__(self, document, layers):
        self.canvas_width, self.canvas_height = document.canvas_width, document.canvas_height
        self._layers = list(layers)

    def ordered(self):
        return list(self._layers)


def downscale(image_bgr: np.ndarray, width: int) -> np.ndarray:
    """Same INTER_AREA reduction the 340/180 px previews use."""
    height = max(1, round(image_bgr.shape[0] * width / image_bgr.shape[1]))
    return cv2.resize(image_bgr, (width, height), interpolation=cv2.INTER_AREA)
