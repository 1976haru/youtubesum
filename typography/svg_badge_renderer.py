"""Small vector SVG badges rendered to transparent Skia PNG overlays."""
from __future__ import annotations

import html
from pathlib import Path
import re

import cv2
import numpy as np
import skia


_TEMPLATES = {
    "ep": '<rect x="2" y="5" width="{w}" height="{h}" rx="18" fill="{bg}" stroke="{accent}" stroke-width="4"/>',
    "mini": '<rect x="2" y="8" width="{w}" height="{h}" rx="9" fill="{bg}"/><rect x="2" y="8" width="9" height="{h}" rx="4" fill="{accent}"/>',
    "sticker": '<path d="M12 4 H{w1} L{w} {h1} L{w1} {h} H12 Q3 {h} 3 {h1} V13 Q3 4 12 4Z" fill="{bg}" stroke="{accent}" stroke-width="4"/>',
    "ribbon": '<path d="M2 7 H{w1} L{w} {h1} L{w1} {h} H2Z" fill="{bg}" stroke="{accent}" stroke-width="3"/>',
}


def badge_svg(text: str, kind: str = "mini", width: int = 280, height: int = 76,
              fill: str = "#111827", accent: str = "#62E8FF", color: str = "#FFFFFF") -> str:
    safe = html.escape((text or "")[:48])
    shape = _TEMPLATES.get(kind, _TEMPLATES["mini"]).format(w=width - 4, h=height - 12,
        w1=width - 36, h1=height // 2, bg=fill, accent=accent)
    font_size = 24 if len(safe) < 14 else (20 if len(safe) < 22 else 17)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<defs><filter id="s"><feGaussianBlur stdDeviation="3"/></filter></defs>{shape}'
            f'<text x="{width/2:.1f}" y="{height/2+font_size*.34:.1f}" text-anchor="middle" '
            f'font-family="sans-serif" font-size="{font_size}" font-weight="800" fill="{color}">{safe}</text></svg>')


def render_svg_png(svg: str, supersample: int = 2, text: str = "",
                   text_color: str = "#FFFFFF") -> np.ndarray:
    svg = re.sub(r"<text\b[\s\S]*?</text>", "", svg)
    document = skia.SVGDOM.MakeFromStream(skia.MemoryStream(svg.encode("utf-8")))
    if document is None:
        raise ValueError("Invalid SVG badge template")
    size = document.containerSize()
    width, height = round(size.width() * supersample), round(size.height() * supersample)
    surface = skia.Surface.MakeRasterN32Premul(width, height)
    canvas = surface.getCanvas()
    canvas.scale(supersample, supersample)
    document.render(canvas)
    if text:
        safe = (text or "")[:48]
        font_size = 24 if len(safe) < 14 else (20 if len(safe) < 22 else 17)
        font = skia.Font(skia.Typeface.MakeFromName("Segoe UI", skia.FontStyle()), font_size)
        font.setEmbolden(True)
        paint = skia.Paint(AntiAlias=True, Color=skia.ColorWHITE)
        if text_color.upper() != "#FFFFFF":
            value = text_color.lstrip("#")
            red, green, blue = (int(value[i:i+2], 16) for i in (0, 2, 4))
            paint.setColor(skia.ColorSetARGB(255, red, green, blue))
        canvas.drawString(safe, (size.width() - font.measureText(safe)) / 2,
                          size.height() / 2 + font_size * 0.34, font, paint)
    pixels = surface.makeImageSnapshot().toarray(colorType=skia.ColorType.kRGBA_8888_ColorType)
    if supersample > 1:
        pixels = cv2.resize(pixels, (round(size.width()), round(size.height())), interpolation=cv2.INTER_AREA)
    return pixels


def render_badge_png(path, *args, **kwargs) -> np.ndarray:
    pixels = render_svg_png(badge_svg(*args, **kwargs), text=args[0] if args else kwargs.get("text", ""))
    encoded = skia.Image.fromarray(pixels).encodeToData(skia.EncodedImageFormat.kPNG)
    Path(path).write_bytes(bytes(encoded))
    return pixels
