"""Composition-specific geometry routed through Skia/HarfBuzz typography."""
from __future__ import annotations

import cv2
import numpy as np

from typography.svg_badge_renderer import render_svg_png, badge_svg
from typography.text_renderer_skia import render_title
from typography.text_style import get_preset
from typography.thumbnail_layouts import choose_layout
from typography.background_fit import apply_adaptive_backdrop


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
                          subject_boxes=(), safe_zones=(), show_safe_overlay: bool = False,
                          live_options: dict | None = None) -> tuple[np.ndarray, dict]:
    """Render candidate metadata, vector labels, and styled title on a 1280x720 frame."""
    preset = get_preset(style, channel)
    max_lines = 3 if auto_two_line else 1
    layout = choose_layout(code, channel, story_type, episode, size_option,
                           subject_boxes=subject_boxes, safe_zones=safe_zones)
    live = live_options or {}
    roles = {
        "channel_label": (30, 20, 270, 68),
        "story_label": layout.badge_box,
        "episode_badge": (980, 20, 270, 68),
        "main_title": layout.title_box,
        "subtitle": (48, 662 if channel == "Tokyo Chill" else 654, 1160, 48),
    }
    for role, box in live.get("positions", {}).items():
        if role in roles and len(box) == 4:
            roles[role] = tuple(max(0, int(value)) for value in box)
    title_box = roles["main_title"]
    align = live.get("alignment", layout.align)
    title_text = (title or ("思い出の夜" if channel == "Tokyo Chill" else "懐かしい記憶")).strip()
    output, bg_analysis = apply_adaptive_backdrop(image_bgr, title_box,
        soft_plate=bool(live.get("soft_plate", True)), gradient=bool(live.get("gradient", True)),
        anchor=align, subject_boxes=subject_boxes, auto=bool(live.get("auto_backdrop", True)))
    result = render_title(output, title_text, title_box, preset.name, channel,
        align, live.get("title_size", size_option), live.get("outline_width", outline_thickness),
        live.get("glow_strength", glow_intensity), live.get("shadow_strength", shadow_intensity),
        keyword if emphasize_keyword else "", max_lines, manual_breaks, safe_zones,
        subject_boxes, 2, show_safe_overlay, fill_color=live.get("fill_color"),
        stroke_color=live.get("stroke_color"), highlight_color=live.get("highlight_color"),
        letter_spacing=live.get("letter_spacing"), line_spacing=live.get("line_spacing", 1.17))
    output = result.image.copy()
    if subtitle.strip():
        subtitle_box = roles["subtitle"]
        output, _ = apply_adaptive_backdrop(output, subtitle_box,
            soft_plate=bool(live.get("soft_plate", True)), gradient=bool(live.get("gradient", True)),
            anchor="left", subject_boxes=subject_boxes, auto=bool(live.get("auto_backdrop", True)))
        caption = render_title(output, subtitle.strip(), subtitle_box,
            preset.name, channel, "left", 31 if channel == "Tokyo Chill" else 34,
            outline_thickness=1.2, glow_intensity=0.25, shadow_intensity=0.35,
            max_lines=1, supersample=2)
        output = caption.image
    # The top channel tag stays subdued; the candidate badge differs by A/B/C.
    channel_box = roles["channel_label"]
    channel_badge = render_svg_png(badge_svg(channel.upper(), "mini", channel_box[2], channel_box[3],
        fill=preset.outline, accent=preset.accent, color="#FFFFFF"), supersample=2,
        text=channel.upper())
    _composite_badge(output, channel_badge, channel_box[0], channel_box[1])
    role_name = {"A_PERSON": "PERSON", "B_EMOTION": "EMOTION", "C_STORY": "STORY"}.get(code, layout.badge_text.split(" · ")[0])
    story_value = story_type if story_type not in ("", "자동", "Auto") else role_name
    story_label = f"{code[0]} · {story_value}"
    story_box = roles["story_label"]
    badge = render_svg_png(badge_svg(story_label, layout.badge_kind, story_box[2], story_box[3],
        fill=preset.outline, accent=preset.accent, color="#FFFFFF"), supersample=2, text=story_label)
    _composite_badge(output, badge, story_box[0], story_box[1])
    episode_box = roles["episode_badge"]
    episode_label = episode or "EP.001"
    ep_badge = render_svg_png(badge_svg(episode_label, "ep", episode_box[2], episode_box[3],
        fill=preset.outline, accent=preset.accent, color="#FFFFFF"), supersample=2, text=episode_label)
    _composite_badge(output, ep_badge, episode_box[0], episode_box[1])
    return output, {
        "typography_style": preset.key,
        "typography_name": preset.name,
        "title": {"lines": result.lines, "keyword": result.keyword, "font_size": result.font_size,
                  "contrast": result.contrast, "bbox": list(result.bbox),
                  "line_score": result.chosen_break_score,
                  "font_families": list(result.fallback_families)},
        "title_box": list(title_box), "variant": code,
        "badge": story_label,
        "roles": {name: list(box) for name, box in roles.items()},
        "background_fit": {"mean_luminance": bg_analysis.mean_luminance,
            "dominant_color": bg_analysis.dominant_color, "accent_color": bg_analysis.accent_color,
            "subject_conflict": bg_analysis.subject_conflict, "readability": bg_analysis.readability,
            "soft_plate_recommended": bg_analysis.recommend_soft_plate,
            "gradient_recommended": bg_analysis.recommend_gradient},
    }
