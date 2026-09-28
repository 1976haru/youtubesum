"""Image-aware layout, contrast, and adaptive background treatments."""
from __future__ import annotations

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
