"""Supersampled Skia/HarfBuzz vector title renderer and text safe-area placer."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import skia

from .font_registry import FontRegistry, get_font_registry
from .linebreak_engine import LineBreakCandidate, choose_line_break, score_line_breaks
from .shaping_engine import ShapedText, shape_text
from .text_style import TextStyle, get_preset


@dataclass(frozen=True)
class RenderedTitle:
    image: np.ndarray
    lines: tuple[str, ...]
    keyword: str
    font_size: int
    contrast: str
    bbox: tuple[int, int, int, int]
    chosen_break_score: float
    fallback_families: tuple[str, ...]


def _rgba(hex_color: str, alpha: int = 255) -> int:
    value = hex_color.strip().lstrip("#")
    if len(value) == 8:
        alpha = int(value[6:8], 16); value = value[:6]
    red, green, blue = (int(value[index:index + 2], 16) for index in (0, 2, 4))
    return skia.ColorSetARGB(alpha, red, green, blue)


def _measure(text: str, size: float, channel: str, preferred: str | None,
             letter_spacing: float, registry: FontRegistry) -> float:
    return shape_text(text, size, channel, preferred, 800, letter_spacing, registry=registry).advance


def _select_line_candidate(text: str, initial_size: int, box, channel: str, style: TextStyle,
                           max_lines: int, manual_breaks: str, letter_spacing: float,
                           registry: FontRegistry):
    width = box[2]
    available_height = box[3]
    minimum_size = 22 if initial_size < 60 else 36
    for font_size in range(initial_size, minimum_size - 1, -2):
        measure = lambda line: _measure(line, font_size, channel, style.preferred_family, letter_spacing, registry)
        if manual_breaks.strip():
            chosen = choose_line_break(text, measure, width, max_lines, manual_breaks)
            if chosen.width_ratio <= 1.03 and len(chosen.lines) * font_size * 1.17 <= available_height:
                return chosen, font_size
        choices = score_line_breaks(text, measure, width, max_lines)
        acceptable = [candidate for candidate in choices if candidate.width_ratio <= 1.0
                      and len(candidate.lines) * font_size * 1.17 <= available_height]
        if acceptable:
            return acceptable[0], font_size
    measure = lambda line: _measure(line, minimum_size, channel, style.preferred_family, letter_spacing, registry)
    chosen = choose_line_break(text, measure, width, max_lines, manual_breaks)
    return chosen, minimum_size


def _line_segments(line: str, keyword: str):
    if keyword and keyword in line:
        before, _, after = line.partition(keyword)
        return [(before, False), (keyword, True), (after, False)]
    return [(line, False)]


def _draw_shaped_line(canvas: skia.Canvas, text: str, keyword: str, start_x: float, baseline: float,
                      font_size: int, channel: str, style: TextStyle, outline: float,
                      shadow_intensity: float, glow_intensity: float, letter_spacing: float,
                      registry: FontRegistry, supersample: int) -> float:
    cursor = start_x
    for segment, highlighted in _line_segments(text, keyword):
        if not segment:
            continue
        size = font_size * (1.11 if highlighted else 1.0)
        shaped = shape_text(segment, size, channel, style.preferred_family, 900,
                            letter_spacing, kerning=True, ligatures=True, registry=registry)
        for run in shaped.runs:
            positions = [skia.Point(px * supersample, py * supersample) for px, py in run.positions]
            blob_builder = skia.TextBlobBuilder()
            blob_builder.allocRunPos(skia.Font(run.typeface, run.size * supersample), run.glyphs, positions)
            blob = blob_builder.make()
            if blob is None:
                continue
            base = style.accent if highlighted else style.fill
            gradient = skia.GradientShader.MakeLinear(
                [skia.Point(cursor * supersample, (baseline - size) * supersample),
                 skia.Point((cursor + shaped.advance) * supersample, baseline * supersample)],
                [_rgba(base), _rgba(style.gradient_end if not highlighted else style.accent)])
            if glow_intensity > 0 and style.glow_blur > 0:
                glow = skia.Paint(AntiAlias=True, Color=_rgba(style.glow, round(190 * glow_intensity)))
                glow.setMaskFilter(skia.MaskFilter.MakeBlur(skia.BlurStyle.kNormal_BlurStyle,
                    max(0.1, style.glow_blur * glow_intensity * supersample)))
                glow.setStyle(skia.Paint.kStroke_Style)
                glow.setStrokeWidth((outline + 7) * supersample)
                canvas.drawTextBlob(blob, cursor * supersample, baseline * supersample, glow)
            if shadow_intensity > 0:
                shadow = skia.Paint(AntiAlias=True, Color=_rgba(style.shadow, round(220 * shadow_intensity)))
                shadow.setMaskFilter(skia.MaskFilter.MakeBlur(skia.BlurStyle.kNormal_BlurStyle,
                    max(0.1, style.shadow_blur * shadow_intensity * supersample)))
                canvas.drawTextBlob(blob, (cursor + 4 * shadow_intensity) * supersample,
                                    (baseline + 5 * shadow_intensity) * supersample, shadow)
            stroke = skia.Paint(AntiAlias=True, Color=_rgba(style.outline))
            stroke.setStyle(skia.Paint.kStroke_Style)
            stroke.setStrokeWidth(max(1, outline) * supersample)
            stroke.setStrokeJoin(skia.Paint.kRound_Join)
            canvas.drawTextBlob(blob, cursor * supersample, baseline * supersample, stroke)
            fill = skia.Paint(AntiAlias=True, Color=_rgba(base))
            if gradient:
                fill.setShader(gradient)
            canvas.drawTextBlob(blob, cursor * supersample, baseline * supersample, fill)
        cursor += shaped.advance
    return cursor - start_x


def _normalize_zone(zone, width: int, height: int):
    if isinstance(zone, dict):
        zone = zone.get("bbox", zone.get("box", zone.get("rect")))
    if not isinstance(zone, (list, tuple)) or len(zone) != 4:
        return None
    x, y, w, h = map(float, zone)
    if max(abs(x), abs(y), abs(w), abs(h)) <= 1:
        x, w, y, h = x * width, w * width, y * height, h * height
    return tuple(map(int, (x, y, w, h)))


def _contrast(rgb: np.ndarray, rect: tuple[int, int, int, int]) -> str:
    x, y, width, height = rect
    sample = rgb[max(0, y):min(rgb.shape[0], y + height), max(0, x):min(rgb.shape[1], x + width)]
    if sample.size == 0:
        return "light"
    luminance = float(np.mean(sample[:, :, 0] * 0.2126 + sample[:, :, 1] * 0.7152 + sample[:, :, 2] * 0.0722))
    return "dark" if luminance >= 154 else "light"


def render_title(image_bgr: np.ndarray, text: str, rect: tuple[int, int, int, int],
                 style_name: str, channel: str = "Tokyo Chill", align: str = "left",
                 size_option: str = "Auto", outline_thickness: float | None = None,
                 glow_intensity: float = 1.0, shadow_intensity: float = 0.9,
                 highlight_word: str = "", max_lines: int = 3, manual_breaks: str = "",
                 safe_zones=(), subject_boxes=(), supersample: int = 2,
                 show_safe_overlay: bool = False, registry: FontRegistry | None = None) -> RenderedTitle:
    registry = registry or get_font_registry()
    style = get_preset(style_name, channel)
    image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    x, y, width, height = rect
    safe = [_normalize_zone(zone, image_bgr.shape[1], image_bgr.shape[0]) for zone in safe_zones]
    safe = [zone for zone in safe if zone]
    subjects = [_normalize_zone(box, image_bgr.shape[1], image_bgr.shape[0]) for box in subject_boxes]
    subjects = [box for box in subjects if box]
    candidates = [(x, y, width, height)]
    if align != "right":
        candidates.append((image_bgr.shape[1] - x - width, y, width, height))
    def overlap(box, obstacle):
        bx, by, bw, bh = box; ox, oy, ow, oh = obstacle
        area = max(0, min(bx + bw, ox + ow) - max(bx, ox)) * max(0, min(by + bh, oy + oh) - max(by, oy))
        return area / max(1, bw * bh)
    rect = min(candidates, key=lambda candidate: (sum(overlap(candidate, zone) * 5 for zone in safe)
                                                  + sum(overlap(candidate, box) * 1.8 for box in subjects)))
    x, y, width, height = rect
    nominal = int(size_option) if isinstance(size_option, (int, float)) else {"Auto": 106, "Small": 78, "Medium": 100, "Large": 126}.get(size_option, 106)
    if style.senior:
        nominal = round(nominal * 1.10)
    chosen, font_size = _select_line_candidate(text, nominal, rect, channel, style, max_lines,
                                               manual_breaks, style.letter_spacing, registry)
    scaled = skia.Surface.MakeRasterN32Premul(image_bgr.shape[1] * supersample,
                                               image_bgr.shape[0] * supersample)
    canvas = scaled.getCanvas()
    canvas.clear(skia.ColorTRANSPARENT)
    background = skia.Image.fromarray(np.dstack((image_rgb, np.full(image_rgb.shape[:2], 255, dtype=np.uint8))))
    canvas.drawImageRect(background, skia.Rect.MakeWH(image_bgr.shape[1] * supersample,
                         image_bgr.shape[0] * supersample), skia.SamplingOptions(skia.FilterMode.kLinear))
    if show_safe_overlay:
        overlay = skia.Paint(AntiAlias=True, Color=skia.ColorSetARGB(72, 255, 38, 68))
        for zone in safe:
            zx, zy, zw, zh = zone
            canvas.drawRect(skia.Rect.MakeXYWH(zx * supersample, zy * supersample,
                                               zw * supersample, zh * supersample), overlay)
    rows = chosen.lines
    baseline_step = min(font_size * 1.17, height / max(1, len(rows)))
    total_height = baseline_step * len(rows)
    baseline = y + (height - total_height) / 2 + font_size * 0.94
    extents: list[tuple[int, int, int, int]] = []
    keyword = highlight_word if highlight_word and highlight_word in text else ""
    used_families = set()
    for index, line in enumerate(rows):
        line_width = _measure(line, font_size, channel, style.preferred_family, style.letter_spacing, registry)
        if align == "center":
            line_x = x + (width - line_width) / 2
        elif align == "right":
            line_x = x + width - line_width
        else:
            line_x = x
        base = baseline + index * baseline_step
        _draw_shaped_line(canvas, line, keyword, line_x, base, font_size, channel, style,
                          outline_thickness if outline_thickness is not None else style.outline_width,
                          shadow_intensity, glow_intensity, style.letter_spacing, registry, supersample)
        extents.append((round(line_x), round(base - font_size), round(line_width), round(font_size * 1.2)))
        used_families.update(run.face.family for run in shape_text(line, font_size, channel,
                                style.preferred_family, 800, style.letter_spacing, registry=registry).runs)
    snapshot = scaled.makeImageSnapshot()
    rendered = snapshot.toarray(colorType=skia.ColorType.kRGBA_8888_ColorType)
    if supersample > 1:
        rendered = cv2.resize(rendered, (image_bgr.shape[1], image_bgr.shape[0]), interpolation=cv2.INTER_AREA)
    output = cv2.cvtColor(rendered[:, :, :3], cv2.COLOR_RGB2BGR)
    min_x = min((e[0] for e in extents), default=x); min_y = min((e[1] for e in extents), default=y)
    max_x = max((e[0] + e[2] for e in extents), default=x); max_y = max((e[1] + e[3] for e in extents), default=y)
    return RenderedTitle(output, rows, keyword, font_size,
                         "dark-ink" if _contrast(image_rgb, rect) == "dark" else "light-ink",
                         (min_x, min_y, max_x - min_x, max_y - min_y), chosen.score,
                         tuple(sorted(used_families)))


def render_title_to_png(*args, **kwargs) -> bytes:
    result = render_title(*args, **kwargs)
    rgb = cv2.cvtColor(result.image, cv2.COLOR_BGR2RGB)
    surface = skia.Image.fromarray(rgb).encodeToData(skia.EncodedImageFormat.kPNG)
    return bytes(surface)
