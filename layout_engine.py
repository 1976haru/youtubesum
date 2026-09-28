"""Composition-specific geometry routed through Skia/HarfBuzz typography."""
from __future__ import annotations

import cv2
import numpy as np

from typography.svg_badge_renderer import render_svg_png, badge_svg
from typography.text_renderer_skia import render_title
from typography.text_style import get_preset
from typography.thumbnail_layouts import choose_layout


def _composite_badge(image_bgr: np.ndarray, rgba: np.ndarray, x: int, y: int) -> None:
    height, width = rgba.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(image_bgr.shape[1], x + width), min(image_bgr.shape[0], y + height)
    if x1 <= x0 or y1 <= y0:
        return
    overlay = rgba[y0 - y:y1 - y, x0 - x:x1 - x]
    alpha = overlay[:, :, 3:4].astype(np.float32) / 255.0
    rgb = overlay[:, :, :3][:, :, ::-1]
    image_bgr[y0:y1, x0:x1] = (rgb * alpha + image_bgr[y0:y1, x0:x1] * (1 - alpha)).astype(np.uint8)


def render_candidate_text(image_bgr: np.ndarray, channel: str, code: str, story_type: str,
                          episode: str, title: str, subtitle: str, style: str,
                          auto_two_line: bool = True, emphasize_keyword: bool = True,
                          keyword: str = "", size_option: str = "Auto", *,
                          outline_thickness: float | None = None, glow_intensity: float = 1.0,
                          shadow_intensity: float = 0.9, manual_breaks: str = "",
                          subject_boxes=(), safe_zones=(), show_safe_overlay: bool = False) -> tuple[np.ndarray, dict]:
    """Render candidate metadata, vector labels, and styled title on a 1280x720 frame."""
    preset = get_preset(style, channel)
    max_lines = 3 if auto_two_line else 1
    layout = choose_layout(code, channel, story_type, episode, size_option,
                           subject_boxes=subject_boxes, safe_zones=safe_zones)
    title_text = (title or ("思い出の夜" if channel == "Tokyo Chill" else "懐かしい記憶")).strip()
    result = render_title(image_bgr, title_text, layout.title_box, preset.name, channel,
        layout.align, size_option, outline_thickness, glow_intensity, shadow_intensity,
        keyword if emphasize_keyword else "", max_lines, manual_breaks, safe_zones,
        subject_boxes, 2, show_safe_overlay)
    output = result.image.copy()
    if subtitle.strip():
        subtitle_y = 668 if channel == "Tokyo Chill" else 660
        caption = render_title(output, subtitle.strip(), (48, subtitle_y, 1160, 46),
            preset.name, channel, "left", 31 if channel == "Tokyo Chill" else 34,
            outline_thickness=1.2, glow_intensity=0.25, shadow_intensity=0.35,
            max_lines=1, supersample=2)
        output = caption.image
    # The top channel tag stays subdued; the candidate badge differs by A/B/C.
    channel_badge = render_svg_png(badge_svg(channel.upper(), "mini", 270, 68,
        fill=preset.outline, accent=preset.accent, color="#FFFFFF"), supersample=2,
        text=channel.upper())
    _composite_badge(output, channel_badge, 30, 20)
    label = f"{code[0]} · {layout.badge_text}"
    badge = render_svg_png(badge_svg(label, layout.badge_kind, layout.badge_box[2],
        layout.badge_box[3], fill=preset.outline, accent=preset.accent,
        color="#FFFFFF"), supersample=2, text=label)
    _composite_badge(output, badge, layout.badge_box[0], layout.badge_box[1])
    return output, {
        "typography_style": preset.key,
        "typography_name": preset.name,
        "title": {"lines": result.lines, "keyword": result.keyword, "font_size": result.font_size,
                  "contrast": result.contrast, "bbox": list(result.bbox),
                  "line_score": result.chosen_break_score,
                  "font_families": list(result.fallback_families)},
        "title_box": list(layout.title_box), "variant": code,
        "badge": layout.badge_text,
    }
