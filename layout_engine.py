"""Composition-specific text geometry; visual glyph treatments live in typography_engine."""
from __future__ import annotations

from PIL import Image, ImageDraw
import cv2
import numpy as np

from typography_engine import (TYPOGRAPHY_PRESETS, contrast_mode, draw_support_text,
                               draw_thumbnail_title, preset_key)


LAYOUTS = {
    "A_PERSON": {"tokyo": (48, 392, 850, 250, "left"), "old": (48, 378, 1120, 270, "left"), "variant": "person"},
    "B_EMOTION": {"tokyo": (230, 404, 1000, 236, "center"), "old": (130, 390, 1080, 260, "center"), "variant": "emotion"},
    "B_MEMORY": {"tokyo": (230, 404, 1000, 236, "center"), "old": (130, 390, 1080, 260, "center"), "variant": "emotion"},
    "C_STORY": {"tokyo": (52, 96, 760, 258, "left"), "old": (58, 92, 910, 280, "left"), "variant": "story"},
    "C_SCENERY": {"tokyo": (52, 96, 760, 258, "left"), "old": (58, 92, 910, 280, "left"), "variant": "story"},
}


def _contrast_color(rgb: np.ndarray, box: tuple[int, int, int, int], light: str, dark: str) -> str:
    return dark if contrast_mode(rgb, box) == "dark" else light


def render_candidate_text(image_bgr: np.ndarray, channel: str, code: str, story_type: str,
                          episode: str, title: str, subtitle: str, style: str,
                          auto_two_line: bool = True, emphasize_keyword: bool = True,
                          keyword: str = "", size_option: str = "Auto") -> tuple[np.ndarray, dict]:
    """Apply metadata and title styles to an image using a candidate-specific layout."""
    style_id = preset_key(style, channel)
    preset = TYPOGRAPHY_PRESETS[style_id]
    old = channel == "OLD POP LOUNGE"
    layout = LAYOUTS.get(code, LAYOUTS["A_PERSON"])
    key = "old" if old else "tokyo"
    title_box = layout[key]
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    canvas = Image.fromarray(rgb).convert("RGBA")
    draw = ImageDraw.Draw(canvas, "RGBA")
    base_array = np.asarray(canvas.convert("RGB"))

    # The story-card treatment is deliberately the only preset with a solid card.
    # Other looks rely on chromatic accents, glyph outline, shadow and controlled glow.
    x, y, width, height, align = title_box
    if preset.card_fill:
        draw.rounded_rectangle((x - 22, y - 18, x + width + 18, y + height + 14),
                               radius=24 if not old else 18, fill=preset.card_fill)

    meta_light = "#FFFFFF" if not old else "#FFF3D3"
    meta_dark = "#171B23" if not old else "#382214"
    # Channel / story / episode stay in a slim upper band and never compete with title scale.
    brand_box = (38, 18, 340, 44)
    story_box = (742, 18, 1025, 44)
    episode_box = (1048, 18, 228, 46)
    brand_color = _contrast_color(base_array, brand_box, meta_light, meta_dark)
    story_color = _contrast_color(base_array, story_box, preset.accent, preset.dark_accent)
    episode_color = _contrast_color(base_array, episode_box, meta_light, meta_dark)
    meta_size = 29 if old else 25
    draw_support_text(draw, (42, 20), "OLD POP LOUNGE" if old else "TOKYO CHILL", meta_size,
                      brand_color, outline="#11151D", outline_width=2)
    label = {"남자 이야기": "MAN'S STORY", "여자 이야기": "WOMAN'S STORY",
             "두 사람 이야기": "TWO STORIES", "자동": "STORY"}.get(story_type, story_type or "STORY")
    draw_support_text(draw, (750, 20), label, meta_size - 2, story_color,
                      outline="#11151D", outline_width=2)
    draw_support_text(draw, (1055, 20), (episode or "EP.001").upper(), meta_size - 1,
                      episode_color, outline="#11151D", outline_width=2)

    title_meta = draw_thumbnail_title(canvas, title, (x, y, width, height), style_id,
                                      auto_two_line, emphasize_keyword, keyword,
                                      size_option=size_option, align=align,
                                      variant=layout["variant"])
    # Keep the supporting copy in a visually subordinate bottom rail.
    subtitle_box = (38, 672, 1100, 34)
    subtitle_color = _contrast_color(base_array, subtitle_box, preset.accent, preset.dark_accent)
    sub_size = 31 if old else 26
    draw_support_text(draw, (44, 674), (subtitle or "").strip(), sub_size,
                      subtitle_color, outline="#10131A", outline_width=2)
    result = cv2.cvtColor(np.asarray(canvas.convert("RGB")), cv2.COLOR_RGB2BGR)
    return result, {"typography_style": style_id, "title": title_meta, "title_box": list(title_box),
                    "variant": layout["variant"]}
