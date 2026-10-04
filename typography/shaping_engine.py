"""HarfBuzz glyph shaping with installed-font fallback for mixed-script runs."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import skia
import uharfbuzz as hb

from .font_registry import FontFace, FontRegistry, get_font_registry


@dataclass(frozen=True)
class ShapedRun:
    text: str
    face: FontFace
    glyphs: tuple[int, ...]
    positions: tuple[tuple[float, float], ...]
    advance: float
    size: float
    typeface: object


@dataclass(frozen=True)
class ShapedText:
    text: str
    runs: tuple[ShapedRun, ...]
    advance: float


@lru_cache(maxsize=128)
def _font_data(path: str) -> bytes:
    return Path(path).read_bytes()


@lru_cache(maxsize=128)
def _typeface(path: str, index: int):
    face = skia.Typeface.MakeFromFile(path, index)
    if face is None:
        raise RuntimeError(f"Skia could not load installed font: {path}")
    return face


def _font_runs(text: str, registry: FontRegistry, channel: str, preferred: str | None,
               weight: int):
    runs = []
    for char in text:
        face = registry.resolve(char, channel, preferred, weight)
        key = (str(face.path), face.index)
        if runs and runs[-1][0] == key:
            runs[-1] = (key, runs[-1][1] + char, face)
        else:
            runs.append((key, char, face))
    return runs


def shape_text(text: str, size: float, channel: str = "Tokyo Chill", preferred_family: str | None = None,
               weight: int = 700, letter_spacing: float = 0.0, kerning: bool = True,
               ligatures: bool = True, registry: FontRegistry | None = None) -> ShapedText:
    registry = registry or get_font_registry()
    shaped_runs = []
    cursor = 0.0
    features = {"kern": int(kerning), "liga": int(ligatures), "clig": int(ligatures)}
    for _, run_text, face in _font_runs(text, registry, channel, preferred_family, weight):
        data = _font_data(str(face.path))
        blob = hb.Blob(data)
        hb_face = hb.Face(blob, face.index)
        hb_font = hb.Font(hb_face)
        upem = hb_face.upem or 1000
        hb_font.scale = (upem, upem)
        hb.ot_font_set_funcs(hb_font)
        buffer = hb.Buffer()
        buffer.add_str(run_text)
        buffer.guess_segment_properties()
        hb.shape(hb_font, buffer, features)
        positions = []
        glyphs = []
        run_cursor = 0.0
        scale = size / upem
        for info, pos in zip(buffer.glyph_infos, buffer.glyph_positions):
            glyphs.append(int(info.codepoint))
            x = run_cursor + pos.x_offset * scale
            y = -pos.y_offset * scale
            positions.append((cursor + x, y))
            run_cursor += pos.x_advance * scale + letter_spacing
        run_cursor -= letter_spacing if glyphs else 0
        typeface = _typeface(str(face.path), face.index)
        shaped_runs.append(ShapedRun(run_text, face, tuple(glyphs), tuple(positions),
                                     run_cursor, size, typeface))
        cursor += run_cursor
    return ShapedText(text, tuple(shaped_runs), cursor)


def measure_text(text: str, size: float, **kwargs) -> float:
    return shape_text(text, size, **kwargs).advance
