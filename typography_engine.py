"""OS-font-only thumbnail typography, kept independent of candidate geometry/layout."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


@dataclass(frozen=True)
class TypographyPreset:
    key: str
    channel: str
    name: str
    ink: str
    dark_ink: str
    accent: str
    dark_accent: str
    outline: str
    shadow: str
    glow: str
    outline_width: int
    shadow_offset: tuple[int, int]
    glow_radius: int
    card_fill: tuple[int, int, int, int] | None = None
    senior: bool = False


_PRESET_DEFS = (
    ("cinematic_chill", "Tokyo Chill", "CINEMATIC CHILL", "#F8FAFF", "#142135", "#73E8FF", "#087790", "#101827", "#050913", "#56D9F4", 5, (3, 7), 6, None, False),
    ("japanese_impact", "Tokyo Chill", "JAPANESE IMPACT", "#FFFFFF", "#211216", "#FFE23A", "#B51D2C", "#18080A", "#31060C", "#FF344D", 9, (5, 8), 5, None, False),
    ("romantic_neon", "Tokyo Chill", "ROMANTIC NEON", "#FFF7FE", "#2A1232", "#FF72C8", "#9D176E", "#29102F", "#1A0824", "#FF36C7", 5, (4, 7), 15, None, False),
    ("emotional_mono", "Tokyo Chill", "EMOTIONAL MONO", "#FFFFFF", "#181818", "#DADADA", "#3B3B3B", "#111111", "#000000", "#D8E3EF", 4, (3, 6), 4, None, False),
    ("story_card", "Tokyo Chill", "STORY CARD", "#FFF4DC", "#271A16", "#FFD273", "#68412A", "#271A16", "#100B08", "#FFC968", 4, (3, 6), 5, (18, 22, 31, 205), False),
    ("night_drive", "Tokyo Chill", "NIGHT DRIVE", "#F4FBFF", "#13243A", "#65F3D7", "#08705F", "#071423", "#050817", "#25DCCB", 5, (4, 8), 12, None, False),
    ("senior_classic", "OLD POP LOUNGE", "SENIOR CLASSIC", "#FFF3D3", "#382214", "#FFD36C", "#885018", "#392315", "#21140A", "#F0C36A", 6, (3, 7), 3, None, True),
    ("senior_emotional", "OLD POP LOUNGE", "SENIOR EMOTIONAL", "#FFF9F3", "#3D2028", "#F1A7A9", "#8E3947", "#43242C", "#211015", "#F2A1AA", 6, (3, 7), 5, None, True),
    ("first_snow", "OLD POP LOUNGE", "FIRST SNOW", "#F9FCFF", "#1C3043", "#C5E9FA", "#3F718F", "#243B50", "#101D2B", "#B8E7FF", 6, (3, 7), 7, None, True),
    ("autumn_memory", "OLD POP LOUNGE", "AUTUMN MEMORY", "#FFF3DF", "#392116", "#EFB46D", "#8B4F23", "#45291A", "#241309", "#D89757", 6, (3, 7), 4, None, True),
    ("cafe_warm", "OLD POP LOUNGE", "CAFE WARM", "#FFF8E8", "#362315", "#E9C58E", "#73502F", "#392A20", "#21160D", "#D7B67B", 6, (3, 7), 3, None, True),
    ("christmas_glow", "OLD POP LOUNGE", "CHRISTMAS GLOW", "#FFF9E8", "#382019", "#F3C85F", "#8B2426", "#40201D", "#220D12", "#ED6460", 6, (3, 7), 9, None, True),
)
TYPOGRAPHY_PRESETS = {
    row[0]: TypographyPreset(row[0], row[1], row[2], *row[3:]) for row in _PRESET_DEFS
}
PRESETS_BY_CHANNEL = {
    channel: tuple(p for p in TYPOGRAPHY_PRESETS.values() if p.channel == channel)
    for channel in ("Tokyo Chill", "OLD POP LOUNGE")
}


def preset_names(channel: str) -> tuple[str, ...]:
    return tuple(p.name for p in PRESETS_BY_CHANNEL.get(channel, ()))


def preset_key(value: str | None, channel: str = "Tokyo Chill") -> str:
    if value in TYPOGRAPHY_PRESETS:
        return value
    for preset in PRESETS_BY_CHANNEL.get(channel, ()):
        if value == preset.name:
            return preset.key
    available = PRESETS_BY_CHANNEL.get(channel, ())
    if not available:
        raise ValueError(f"Unknown typography channel: {channel}")
    return available[0].key


def _script_of(char: str) -> str:
    code = ord(char)
    if 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F or 0xAC00 <= code <= 0xD7AF:
        return "ko"
    if 0x3040 <= code <= 0x30FF or 0x3400 <= code <= 0x9FFF or 0xF900 <= code <= 0xFAFF:
        return "ja"
    return "en"


@lru_cache(maxsize=512)
def _installed_font(size: int, script: str, bold: bool = True):
    """Resolve an installed Windows/system family; no font assets are bundled."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        names = {
            "ja": (("YuGothUIB.ttc", "YuGothUI.ttf", "YuGothB.ttc", "meiryob.ttc", "NotoSansJP-Bold.otf",
                     "NotoSansJP-VF.otf", "BIZ-UDGothicB.ttc", "YuGothM.ttc", "meiryo.ttc") if bold else
                   ("YuGothUI.ttf", "YuGothR.ttc", "meiryo.ttc", "NotoSansJP-Regular.otf",
                    "BIZ-UDGothicR.ttc", "YuGothM.ttc")),
            "ko": (("malgunbd.ttf", "NotoSansKR-Bold.ttf", "NotoSansKR-VF.ttf", "malgun.ttf") if bold else
                   ("malgun.ttf", "NotoSansKR-Regular.ttf", "NotoSansKR-VF.ttf", "malgunsl.ttf")),
            "en": (("segoeuib.ttf", "arialbd.ttf", "NotoSans-Bold.TTF", "segoeui.ttf") if bold else
                   ("segoeui.ttf", "arial.ttf", "NotoSans-Regular.TTF")),
        }[script]
        candidates.extend(fonts / name for name in names)
    else:
        candidates.extend((Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
                           Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")))
    for path in candidates:
        if path.is_file():
            try:
                return ImageFont.truetype(str(path), size=size, index=0)
            except (OSError, TypeError):
                pass
    return ImageFont.load_default()


def _runs(text: str, size: int, keyword: str | None = None, keyword_scale: float = 1.0):
    segments = []
    if keyword and keyword in text:
        before, _, after = text.partition(keyword)
        if before:
            segments.append((before, False))
        segments.append((keyword, True))
        if after:
            segments.append((after, False))
    else:
        segments.append((text, False))
    runs = []
    for segment, emphasized in segments:
        font_size = max(12, int(round(size * keyword_scale)) if emphasized else size)
        for char in segment:
            script = _script_of(char)
            font = _installed_font(font_size, script, bold=True)
            marker = (script, emphasized, font_size)
            if runs and runs[-1][0] == marker:
                runs[-1] = (marker, runs[-1][1] + char, font)
            else:
                runs.append((marker, char, font))
    return runs


def _runs_width(runs) -> float:
    return sum(float(font.getlength(text)) for _, text, font in runs)


def split_title(text: str, enabled: bool = True) -> tuple[str, ...]:
    """Split at a word boundary where available, otherwise near the visual midpoint."""
    text = " ".join((text or "").split())
    if not text or not enabled:
        return (text,)
    words = text.split(" ")
    if len(words) > 1:
        choices = []
        for index in range(1, len(words)):
            left, right = " ".join(words[:index]), " ".join(words[index:])
            choices.append((abs(len(left) - len(right)), left, right))
        if max(map(len, words)) < max(8, int(len(text) * 0.78)):
            _, left, right = min(choices)
            return left, right
    if len(text) < 8:
        return (text,)
    weights = [1.0 if _script_of(ch) in ("ja", "ko") else 0.56 for ch in text]
    total = sum(weights)
    running = 0.0
    split_at = 1
    for i, weight in enumerate(weights[:-1], start=1):
        running += weight
        split_at = i
        if running >= total / 2:
            break
    for offset in range(0, len(text)):
        idx = min(len(text) - 1, max(1, split_at + (offset // 2 + 1) * (1 if offset % 2 == 0 else -1)))
        if text[idx - 1] not in "、。・,.;:!?…—-" and text[idx] not in "、。・,.;:!?…—-":
            split_at = idx
            break
    return text[:split_at].rstrip(), text[split_at:].lstrip()


def choose_keyword(text: str, keyword: str = "") -> str:
    text = " ".join((text or "").split())
    requested = (keyword or "").strip()
    if requested and requested in text:
        return requested
    words = re.findall(r"[A-Za-z0-9]+|[가-힣]+|[ぁ-ゖァ-ヺ一-龯々ー]+", text)
    useful = [word for word in words if len(word) > 1 and word.lower() not in {"the", "and", "with", "from", "this"}]
    if useful:
        selected = max(useful, key=lambda word: (len(word), min(text.find(word), 9999)))
        if len(selected) > 5 and _script_of(selected[0]) in ("ja", "ko"):
            return selected[-3:]
        return selected
    compact = re.sub(r"\s+", "", text)
    if len(compact) >= 2:
        start = max(0, (len(compact) - 2) // 2)
        return compact[start:start + min(3, len(compact))]
    return compact


def _rgb(hex_color: str) -> tuple[int, int, int]:
    value = hex_color.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def contrast_mode(image_rgb: np.ndarray, box: tuple[int, int, int, int]) -> str:
    """Choose light/dark text from the luminance under the title area."""
    x, y, width, height = box
    sample = image_rgb[max(0, y):min(image_rgb.shape[0], y + height),
                       max(0, x):min(image_rgb.shape[1], x + width)]
    if sample.size == 0:
        return "light"
    luminance = float(np.mean(sample[:, :, 0] * 0.2126 + sample[:, :, 1] * 0.7152 + sample[:, :, 2] * 0.0722))
    return "dark" if luminance >= 154 else "light"


def _line_layout(line: str, size: int, keyword: str, emphasize: bool, scale: float):
    return _runs(line, size, keyword if emphasize else None, scale)


def _draw_glyph_runs(draw, xy, runs, fill, outline, outline_width):
    x, y = xy
    for (_, emphasized, _), text, font in runs:
        color = fill[1] if emphasized else fill[0]
        draw.text((round(x), round(y)), text, font=font, fill=color,
                  stroke_width=outline_width, stroke_fill=outline)
        x += float(font.getlength(text))


def draw_thumbnail_title(base: Image.Image, text: str, box: tuple[int, int, int, int],
                         style: str, auto_two_line: bool = True, emphasize: bool = True,
                         keyword: str = "", size_option: str = "Auto", align: str = "left",
                         variant: str = "person") -> dict:
    """Draw a high-impact, contrast-aware, outlined/glowing title over an RGB/RGBA canvas."""
    preset = TYPOGRAPHY_PRESETS[preset_key(style)]
    rgb_base = np.asarray(base.convert("RGB"))
    x, y, width, height = box
    bright_bg = contrast_mode(rgb_base, box) == "dark"
    ink = _rgb(preset.dark_ink if bright_bg else preset.ink)
    accent = _rgb(preset.dark_accent if bright_bg else preset.accent)
    title = " ".join((text or "").split())
    if not title:
        title = "懐かしい夜" if preset.senior else "思い出の夜"
    lines = split_title(title, auto_two_line)
    picked_keyword = choose_keyword(title, keyword) if emphasize else ""
    channel_base = {"Auto": (104, 114), "Small": (78, 90), "Medium": (98, 110), "Large": (120, 132)}
    preferred = channel_base.get(size_option, channel_base["Auto"])[1 if preset.senior else 0]
    if size_option == "Auto" and len(title) > 16:
        preferred -= 10
    if variant == "person":
        preferred = int(preferred * 1.06)
    elif variant == "story":
        preferred = int(preferred * 0.94)
    font_size = preferred
    scale = (1.20 if variant == "emotion" else 1.12) if emphasize and picked_keyword else 1.0
    while font_size > (46 if preset.senior else 38):
        layouts = [_line_layout(line, font_size, picked_keyword, emphasize, scale) for line in lines]
        widths = [_runs_width(runs) for runs in layouts]
        line_height = font_size * 1.10
        if max(widths, default=0) <= width - preset.outline_width * 2 - 8 and len(lines) * line_height <= height:
            break
        font_size -= 2
    layouts = [_line_layout(line, font_size, picked_keyword, emphasize, scale) for line in lines]
    widths = [_runs_width(runs) for runs in layouts]
    line_height = font_size * 1.10
    y0 = y + max(0, (height - line_height * len(lines)) / 2)
    ink_rgba = (*ink, 255); accent_rgba = (*accent, 255)
    stroke = _rgb(preset.outline)
    shadow = _rgb(preset.shadow)
    outline_width = preset.outline_width + (2 if variant == "person" else (-1 if variant == "story" else 0))
    # Render to a glyph layer, then derive independent shadow/glow layers.
    glyph = Image.new("RGBA", base.size, (0, 0, 0, 0))
    glyph_draw = ImageDraw.Draw(glyph)
    positions = []
    for index, runs in enumerate(layouts):
        line_width = widths[index]
        if align == "center":
            line_x = x + max(0, (width - line_width) / 2)
        elif align == "right":
            line_x = x + max(0, width - line_width)
        else:
            line_x = x
        line_y = y0 + index * line_height
        _draw_glyph_runs(glyph_draw, (line_x, line_y), runs, (ink_rgba, accent_rgba), (*stroke, 255), max(2, outline_width))
        positions.append((round(line_x), round(line_y)))
    mask = glyph.getchannel("A")
    result = base.convert("RGBA")
    glow_radius = preset.glow_radius + (3 if variant == "emotion" else 0)
    if glow_radius:
        glow_mask = mask.filter(ImageFilter.GaussianBlur(glow_radius))
        glow_layer = Image.new("RGBA", base.size, (*_rgb(preset.glow), 0))
        glow_layer.putalpha(glow_mask.point(lambda a: int(a * 0.58)))
        result.alpha_composite(glow_layer)
    shadow_mask = Image.new("L", base.size, 0)
    shadow_mask.paste(mask, preset.shadow_offset)
    shadow_layer = Image.new("RGBA", base.size, (*shadow, 0))
    shadow_layer.putalpha(shadow_mask.point(lambda a: int(a * 0.78)))
    result.alpha_composite(shadow_layer)
    result.alpha_composite(glyph)
    base.paste(result.convert(base.mode), (0, 0))
    return {"lines": lines, "keyword": picked_keyword, "font_size": font_size,
            "contrast": "dark-ink" if bright_bg else "light-ink", "positions": positions,
            "preset": preset.key, "variant": variant, "outline_width": max(2, outline_width),
            "glow_radius": glow_radius}


def draw_support_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, size: int,
                      fill: str, outline: str = "#10131A", outline_width: int = 2) -> None:
    """Small hierarchy-safe channel/episode/subtitle lettering."""
    cursor = xy[0]
    grouped: list[tuple[str, str]] = []
    for char in text:
        script = _script_of(char)
        if grouped and grouped[-1][0] == script:
            grouped[-1] = (script, grouped[-1][1] + char)
        else:
            grouped.append((script, char))
    for script, run in grouped:
        font = _installed_font(size, script, bold=True)
        draw.text((cursor, xy[1]), run, font=font, fill=fill, stroke_width=outline_width, stroke_fill=outline)
        cursor += int(font.getlength(run))
