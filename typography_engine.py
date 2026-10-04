"""Backward-compatible exports for the Professional Typography Engine."""
from __future__ import annotations

import re

import cv2
import numpy as np
from PIL import Image

from typography.font_registry import get_font_registry, script_of
from typography.linebreak_engine import choose_line_break
from typography.text_renderer_skia import _measure, render_title
from typography.text_style import (PRESETS_BY_CHANNEL, TYPOGRAPHY_PRESETS, get_preset,
                                   preset_names)


def preset_key(value: str | None, channel: str = "Tokyo Chill") -> str:
    return get_preset(value, channel).key


def split_title(text: str, enabled: bool = True) -> tuple[str, ...]:
    normalized = " ".join((text or "").split())
    if not normalized or not enabled:
        return (normalized,)
    registry = get_font_registry()
    style = get_preset(None, "Tokyo Chill")
    size = 104
    measure = lambda line: _measure(line, size, "Tokyo Chill", style.preferred_family,
                                    style.letter_spacing, registry)
    words = normalized.split(" ")
    if len(words) > 1:
        breaks = []
        for index in range(1, len(words)):
            left, right = " ".join(words[:index]), " ".join(words[index:])
            left_width, right_width = measure(left), measure(right)
            breaks.append((abs(index - len(words) / 2), abs(left_width - right_width),
                           (left, right)))
        return min(breaks, key=lambda item: (item[0], item[1]))[2]
    max_width = max(400, _measure(normalized, size, "Tokyo Chill", style.preferred_family,
                                  style.letter_spacing, registry)) * 0.56
    return choose_line_break(normalized,
        lambda line: _measure(line, size, "Tokyo Chill", style.preferred_family,
                              style.letter_spacing, registry), max_width, 2).lines


def choose_keyword(text: str, keyword: str = "") -> str:
    if keyword and keyword in text:
        return keyword
    japanese_parts = [part for chunk in re.split(r"[のがをにでともはへ、。！？!?]", text or "")
                      for part in re.findall(r"[\u3040-\u30ff\u3400-\u9fff]+", chunk)]
    if japanese_parts:
        return max(enumerate(japanese_parts), key=lambda item: (len(item[1]), item[0]))[1]
    tokens = re.findall(r"[A-Za-z0-9]+|[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]+", text or "")
    useful = [token for token in tokens if len(token) > 1]
    return max(useful, key=len) if useful else (text or "")[:2]


def contrast_mode(image_rgb: np.ndarray, box: tuple[int, int, int, int]) -> str:
    x, y, width, height = box
    sample = image_rgb[max(0, y):min(image_rgb.shape[0], y + height),
                       max(0, x):min(image_rgb.shape[1], x + width)]
    if not sample.size:
        return "light"
    lum = float(np.mean(sample[:, :, 0] * 0.2126 + sample[:, :, 1] * 0.7152 + sample[:, :, 2] * 0.0722))
    return "dark" if lum >= 154 else "light"


def draw_thumbnail_title(base: Image.Image, text: str, box: tuple[int, int, int, int],
                         style: str, auto_two_line: bool = True, emphasize: bool = True,
                         keyword: str = "", size_option: str = "Auto", align: str = "left",
                         variant: str = "person", outline_thickness: float | None = None,
                         glow_intensity: float = 1.0, shadow_intensity: float = 0.9,
                         manual_breaks: str = "") -> dict:
    """Compatibility adapter; all glyph painting is vector Skia + HarfBuzz."""
    rgb = np.asarray(base.convert("RGB"))
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    channel = "OLD POP LOUNGE" if get_preset(style, "Tokyo Chill").channel == "OLD POP LOUNGE" else "Tokyo Chill"
    result = render_title(bgr, text, box, style, channel, align, size_option, outline_thickness,
        glow_intensity, shadow_intensity, keyword if emphasize else "", 2 if auto_two_line else 1,
        manual_breaks, supersample=2)
    base.paste(Image.fromarray(cv2.cvtColor(result.image, cv2.COLOR_BGR2RGB)).convert(base.mode))
    return {"lines": result.lines, "keyword": result.keyword, "font_size": result.font_size,
            "contrast": result.contrast, "positions": [(result.bbox[0], result.bbox[1])],
            "preset": get_preset(style, channel).key, "variant": variant,
            "outline_width": outline_thickness or get_preset(style, channel).outline_width,
            "glow_radius": get_preset(style, channel).glow_blur,
            "bbox": result.bbox, "font_families": result.fallback_families}


def _installed_font(size: int, script: str, bold: bool = True):
    registry = get_font_registry()
    mapped = {"ja": "ja", "japanese": "ja", "ko": "ko", "hangul": "ko"}.get(script, "en")
    return registry.resolve("日" if mapped == "ja" else ("한" if mapped == "ko" else "A"), weight=700 if bold else 400)


def draw_support_text(draw, xy, text: str, size: int, fill: str,
                      outline: str = "#10131A", outline_width: int = 2) -> None:
    """Legacy callers should use layout_engine's vector label renderer instead."""
    del draw, xy, text, size, fill, outline, outline_width
