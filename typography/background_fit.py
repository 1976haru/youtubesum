"""Image-aware layout, contrast, and adaptive background treatments."""
from __future__ import annotations

import colorsys
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class BackgroundAnalysis:
    mean_luminance: float
    luminance_variance: float
    dominant_color: str
    accent_color: str
    subject_conflict: float
    readability: float
    recommend_soft_plate: bool
    recommend_gradient: bool


def _hex(bgr) -> str:
    b, g, r = (int(v) for v in bgr)
    return f"#{r:02X}{g:02X}{b:02X}"


def analyze_background(image_bgr: np.ndarray, rect: tuple[int, int, int, int], subject_boxes=()) -> BackgroundAnalysis:
    x, y, width, height = map(int, rect)
    h, w = image_bgr.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + width), min(h, y + height)
    roi = image_bgr[y0:y1, x0:x1]
    if roi.size == 0:
        roi = image_bgr
        x0, y0, x1, y1 = 0, 0, w, h
    # Keep enough spatial detail to detect busy texture; a 64x36 area resize
    # smooths fine patterns away and incorrectly labels them as calm.
    tiny = cv2.resize(roi, (256, 144), interpolation=cv2.INTER_AREA)
    lab = cv2.cvtColor(tiny, cv2.COLOR_BGR2LAB)
    luminance = lab[:, :, 0].astype(np.float32) / 255.0
    mean_lum = float(np.mean(luminance))
    variance = float(np.var(luminance))
    quantized = (tiny.astype(np.uint16) // 32).clip(0, 7)
    codes = quantized[:, :, 0] * 64 + quantized[:, :, 1] * 8 + quantized[:, :, 2]
    counts = np.bincount(codes.ravel(), minlength=512)
    colors = []
    for index in np.argsort(counts)[-2:][::-1]:
        mask = codes == index
        colors.append(np.median(tiny[mask], axis=0) if np.any(mask) else np.array([0, 0, 0]))
    dominant = _hex(colors[0])
    accent = _hex(colors[1] if len(colors) > 1 else colors[0])
    title_box = (x0, y0, x1 - x0, y1 - y0)
    conflicts = []
    for box in subject_boxes:
        if isinstance(box, dict):
            box = box.get("bbox", box.get("box", box.get("rect")))
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        sx, sy, sw, sh = map(float, box)
        if max(abs(sx), abs(sy), abs(sw), abs(sh)) <= 1:
            sx, sw, sy, sh = sx * w, sw * w, sy * h, sh * h
        overlap = max(0, min(x1, sx + sw) - max(x0, sx)) * max(0, min(y1, sy + sh) - max(y0, sy))
        conflicts.append(overlap / max(1, title_box[2] * title_box[3]))
    conflict = min(1.0, sum(conflicts))
    # Busy texture and a subject behind the headline both reduce the score.
    readability = float(np.clip(1.0 - variance * 4.5 - conflict * 0.75, 0.0, 1.0))
    return BackgroundAnalysis(mean_lum, variance, dominant, accent, conflict, readability,
                              readability < 0.68, readability < 0.82)


def apply_adaptive_backdrop(image_bgr: np.ndarray, rect: tuple[int, int, int, int], *,
                            soft_plate: bool = True, gradient: bool = True,
                            anchor: str = "left", subject_boxes=(), auto: bool = True) -> tuple[np.ndarray, BackgroundAnalysis]:
    analysis = analyze_background(image_bgr, rect, subject_boxes)
    output = image_bgr.copy()
    x, y, width, height = map(int, rect)
    h, w = output.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + width), min(h, y + height)
    if x1 <= x0 or y1 <= y0:
        return output, analysis
    yy, xx = np.mgrid[y0:y1, x0:x1]
    nx = (xx - x0) / max(1, x1 - x0 - 1)
    ny = (yy - y0) / max(1, y1 - y0 - 1)
    alpha = np.zeros_like(nx, dtype=np.float32)
    if gradient or (auto and analysis.recommend_gradient):
        t = 1.0 - nx if anchor == "right" else nx
        alpha = np.maximum(alpha, (0.34 * np.clip(1 - t, 0, 1) ** 1.5 + 0.04).astype(np.float32))
        alpha = np.maximum(alpha, (0.26 * np.clip((ny - 0.35) / 0.65, 0, 1) ** 1.4).astype(np.float32))
    if soft_plate or (auto and analysis.recommend_soft_plate):
        edge_x = np.minimum(nx, 1 - nx)
        edge_y = np.minimum(ny, 1 - ny)
        softness = np.clip(edge_x * 13, 0, 1) * np.clip(edge_y * 13, 0, 1)
        alpha = np.maximum(alpha, (softness * 0.22).astype(np.float32))
    if np.any(alpha):
        roi = output[y0:y1, x0:x1].astype(np.float32)
        # Dark ink is a stable contrast bed for white/gold channel lettering.
        output[y0:y1, x0:x1] = np.clip(roi * (1 - alpha[..., None]), 0, 255).astype(np.uint8)
    return output, analysis


# ---------------------------------------------------------------------------
# v0.6 background-aware typography ("배경 맞춤") and readability meter
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class RegionAnalysis:
    mean_color: str
    mean_luminance: float
    local_contrast: float
    edge_density: float
    palette: tuple[str, ...]
    dominant_color: str
    accent_color: str
    subject_overlap: float
    readability: float
    face_overlap: float = 0.0


def head_region(box) -> tuple[float, float, float, float]:
    """Face/head part of a subject box: tall full-figure boxes keep their top 35%, face boxes stay whole."""
    x, y, w, h = box
    if h > w * 1.6:
        return x + w * 0.1, y, w * 0.8, h * 0.35
    return x, y, w, h


def _rgb(hex_color: str) -> tuple[float, float, float]:
    value = (hex_color or "#000000").strip().lstrip("#")[:6].ljust(6, "0")
    try:
        return tuple(int(value[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return 0.0, 0.0, 0.0


def _hex_rgb(rgb) -> str:
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02X}" for c in rgb)


def relative_luminance(hex_color: str) -> float:
    def channel(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (channel(c) for c in _rgb(hex_color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(first: str, second: str) -> float:
    a, b = relative_luminance(first), relative_luminance(second)
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def _shift(hex_color: str, lightness: float | None = None, saturation: float | None = None,
           hue_mix: tuple[str, float] | None = None) -> str:
    h, l, s = colorsys.rgb_to_hls(*_rgb(hex_color))
    if hue_mix:
        h2, _l2, _s2 = colorsys.rgb_to_hls(*_rgb(hue_mix[0]))
        h = h * (1 - hue_mix[1]) + h2 * hue_mix[1]
    return _hex_rgb(colorsys.hls_to_rgb(h, l if lightness is None else lightness,
                                        s if saturation is None else saturation))


def _boxes(subject_boxes, width: int, height: int):
    for box in subject_boxes or ():
        if isinstance(box, dict):
            box = box.get("bbox", box.get("box", box.get("rect")))
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        x, y, w, h = map(float, box)
        if max(abs(x), abs(y), abs(w), abs(h)) <= 1:
            x, w, y, h = x * width, w * width, y * height, h * height
        yield x, y, w, h


def analyze_text_region(image_bgr: np.ndarray, rect, subject_boxes=()) -> RegionAnalysis:
    """Luminance, local contrast, palette, edge density and subject overlap under a text box."""
    h, w = image_bgr.shape[:2]
    x, y, width, height = (int(round(v)) for v in rect)
    x0, y0, x1, y1 = max(0, x), max(0, y), min(w, x + max(1, width)), min(h, y + max(1, height))
    if x1 <= x0 or y1 <= y0:
        x0, y0, x1, y1 = 0, 0, w, h
    roi = image_bgr[y0:y1, x0:x1]
    base = analyze_background(image_bgr, (x0, y0, x1 - x0, y1 - y0), subject_boxes)
    sample = cv2.resize(roi, (min(320, max(8, roi.shape[1])), min(180, max(8, roi.shape[0]))),
                        interpolation=cv2.INTER_AREA)
    lightness = cv2.cvtColor(sample, cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.float32) / 255.0
    edges = cv2.Canny(cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY), 60, 160)
    mean_bgr = sample.reshape(-1, 3).mean(axis=0)
    pixels = cv2.resize(sample, (48, 27), interpolation=cv2.INTER_AREA).reshape(-1, 3).astype(np.float32)
    clusters = 5
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 12, 1.0)
    cv2.setRNGSeed(7)
    _compact, labels, centers = cv2.kmeans(pixels, clusters, None, criteria, 2, cv2.KMEANS_PP_CENTERS)
    counts = np.bincount(labels.ravel(), minlength=clusters)
    palette = tuple(_hex(centers[index]) for index in np.argsort(counts)[::-1])
    area = float((x1 - x0) * (y1 - y0))
    overlap = face = 0.0
    for box in _boxes(subject_boxes, w, h):
        for target, region in (("all", box), ("face", head_region(box))):
            sx, sy, sw, sh = region
            amount = max(0.0, min(x1, sx + sw) - max(x0, sx)) * max(0.0, min(y1, sy + sh) - max(y0, sy)) / area
            if target == "all":
                overlap += amount
            else:
                face += amount
    return RegionAnalysis(_hex(mean_bgr), float(lightness.mean()), float(lightness.std()),
                          float(np.count_nonzero(edges)) / max(1, edges.size), palette,
                          base.dominant_color, base.accent_color, min(1.0, overlap), base.readability,
                          min(1.0, face))


LEVELS = ("GOOD", "WARNING", "POOR")


def _worst(*levels: str) -> str:
    return max(levels, key=LEVELS.index)


def readability_report(props: dict, analysis: RegionAnalysis, *, role: str = "title",
                       canvas_width: int = 1280) -> dict:
    """GOOD/WARNING/POOR for contrast and at 340/180 px, plus contrast/face/busy warnings."""
    fill = props.get("fill", "#FFFFFF")
    font_size = float(props.get("font_size", 96))
    outline = float(props.get("outline_width", 0)) / 2 + float(props.get("secondary_outline_width", 0))
    outline_color = props.get("outline_color", "#000000")
    direct = contrast_ratio(fill, analysis.mean_color)
    effective = direct
    if outline >= max(1.5, font_size * 0.022):
        effective = max(effective, contrast_ratio(fill, outline_color) * 0.9)
    if float(props.get("shadow_opacity", 0)) >= 0.4:
        effective *= 1.08
    busy = analysis.edge_density > 0.10 or analysis.local_contrast > 0.22
    if busy and not props.get("has_plate"):
        effective *= max(0.55, 1.0 - max(analysis.edge_density - 0.10, analysis.local_contrast - 0.22, 0.0) * 2.5)
    contrast_level = "GOOD" if effective >= 4.5 else ("WARNING" if effective >= 3.0 else "POOR")
    glyph = font_size * 0.72
    px340, px180 = glyph * 340 / canvas_width, glyph * 180 / canvas_width
    title = role in ("title", "main_title")
    level340 = "GOOD" if px340 >= (12 if title else 6.5) else ("WARNING" if px340 >= (8 if title else 5) else "POOR")
    level180 = "GOOD" if px180 >= (6.5 if title else 4) else ("WARNING" if px180 >= (4.5 if title else 3) else "POOR")
    face_warning = analysis.face_overlap > 0.04
    messages = []
    if contrast_level != "GOOD":
        messages.append(f"배경 대비 부족 ({effective:.1f}:1)")
    if busy:
        messages.append("배경이 복잡함 · plate/gradient 권장")
    if face_warning:
        messages.append(f"얼굴과 {analysis.face_overlap:.0%} 겹침")
    elif analysis.subject_overlap > 0.08:
        messages.append(f"인물 몸통과 {analysis.subject_overlap:.0%} 겹침 (얼굴은 비어 있음)")
    if level340 != "GOOD":
        messages.append(f"340px에서 글자 {px340:.1f}px")
    overall = _worst(contrast_level, level340, "WARNING" if face_warning else "GOOD", level180 if title else "GOOD")
    return {"level": overall, "contrast_level": contrast_level, "contrast": round(effective, 2),
            "direct_contrast": round(direct, 2), "px340": round(px340, 1), "px180": round(px180, 1),
            "level340": level340, "level180": level180, "contrast_warning": contrast_level != "GOOD",
            "face_warning": face_warning, "busy_warning": busy, "messages": messages}


# Channel identity: Tokyo Chill = cinematic/urban/youthful, OLD POP LOUNGE = calm/large/high readability.
CHANNEL_LOOK = {
    "Tokyo Chill": {"light_fill": "#FFFFFF", "dark_fill": "#121826", "highlight": "#FFE23A",
                    "outline_ratio": 0.085, "glow": 0.32, "plate": "gradient_black", "plate_strength": 0.62,
                    "outline_hue": "#1A2A55", "shadow": 0.55},
    "OLD POP LOUNGE": {"light_fill": "#FFF4DC", "dark_fill": "#3A2618", "highlight": "#F2C46B",
                       "outline_ratio": 0.095, "glow": 0.08, "plate": "plate", "plate_strength": 0.42,
                       "outline_hue": "#4A2E1C", "shadow": 0.5},
}


def suggest_text_style(analysis: RegionAnalysis, channel: str, mode: str = "fit", current: dict | None = None,
                       project_palette: dict | None = None) -> dict:
    """Channel-aware style suggestion for a text layer.

    mode: fit (배경에 맞춤), stronger (더 강하게), softer (더 부드럽게), contrast (대비만 보정).
    Returns TextLayer property updates plus an optional ``plate`` overlay suggestion (None = none).
    """
    look = CHANNEL_LOOK.get(channel, CHANNEL_LOOK["Tokyo Chill"])
    current = dict(current or {})
    palette = project_palette or {}
    font_size = float(current.get("font_size", 96))
    dark_background = analysis.mean_luminance < 0.58
    busy = analysis.edge_density > 0.10 or analysis.local_contrast > 0.2
    updates: dict = {}
    if mode in ("stronger", "softer"):
        stronger = mode == "stronger"
        updates["outline_width"] = round(max(0.0, float(current.get("outline_width", 8)) * (1.3 if stronger else 0.72)
                                             + (2 if stronger else 0)), 1)
        updates["shadow_opacity"] = round(min(1.0, max(0.0, float(current.get("shadow_opacity", 0.5))
                                                       + (0.2 if stronger else -0.18))), 2)
        updates["shadow_blur"] = round(max(0.0, float(current.get("shadow_blur", 6)) * (1.15 if stronger else 0.8)), 1)
        glow = float(current.get("glow_opacity", 0.0))
        cap = 0.85 if channel == "Tokyo Chill" else 0.25
        updates["glow_opacity"] = round(min(cap, glow + 0.15 if stronger else glow * 0.55), 2)
        if updates["glow_opacity"] > 0 and float(current.get("glow_blur", 0)) <= 0:
            updates["glow_blur"] = round(font_size * 0.12, 1)
        updates["plate"] = ({"kind": look["plate"], "strength": min(0.85, look["plate_strength"] + 0.12),
                             "color": "#000000"} if stronger else None)
        return updates

    candidates = [palette["fill_color"]] if palette.get("fill_color") else []
    candidates.append(look["light_fill"] if dark_background else look["dark_fill"])
    fill = next((value for value in candidates if contrast_ratio(value, analysis.mean_color) >= 4.5), candidates[-1])
    if relative_luminance(fill) > 0.4:
        # Light ink gets a deep outline that keeps the background's hue so text and image read as one.
        outline = _shift(analysis.dominant_color, lightness=0.09, saturation=0.45, hue_mix=(look["outline_hue"], 0.35))
    else:
        outline = "#FFFFFF" if channel == "Tokyo Chill" else "#FFF6E6"
    if palette.get("stroke_color") and contrast_ratio(fill, palette["stroke_color"]) >= 4.5:
        outline = palette["stroke_color"]
    updates.update(fill=fill, outline_color=outline)
    if mode == "contrast":
        return updates

    ratio = look["outline_ratio"] * (1.2 if busy else 1.0)
    updates["outline_width"] = round(max(3.0, min(26.0, font_size * ratio)), 1)
    updates["shadow_color"] = "#000000" if dark_background else _shift(analysis.dominant_color, lightness=0.18)
    updates["shadow_opacity"] = round(min(0.85, look["shadow"] + (0.15 if busy else 0.0)), 2)
    updates["shadow_blur"] = round(font_size * 0.07, 1)
    updates["shadow_x"] = round(font_size * 0.025, 1)
    updates["shadow_y"] = round(font_size * 0.04, 1)
    accent = palette.get("highlight_color")
    if not accent:
        vivid = [c for c in analysis.palette + (analysis.accent_color,) if colorsys.rgb_to_hls(*_rgb(c))[2] > 0.25]
        accent = _shift(vivid[0] if vivid else look["highlight"], lightness=0.66 if dark_background else 0.42,
                        saturation=0.9)
        if contrast_ratio(accent, outline) < 3.0:
            accent = look["highlight"]
    updates["highlight_color"] = accent
    if dark_background and look["glow"] > 0:
        updates.update(glow_color=_shift(accent, lightness=0.6, saturation=0.85), glow_opacity=look["glow"],
                       glow_blur=round(font_size * 0.14, 1))
    else:
        updates["glow_opacity"] = 0.0
    report = readability_report({**current, **updates}, analysis)
    needs_plate = busy or report["contrast_level"] != "GOOD"
    updates["plate"] = ({"kind": look["plate"], "strength": look["plate_strength"],
                         "color": "#000000" if dark_background or look["plate"] == "gradient_black" else "#FFFFFF"}
                        if needs_plate else None)
    return updates
