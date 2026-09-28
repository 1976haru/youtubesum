"""Installed font inventory, metadata extraction, and script-aware fallback."""
from __future__ import annotations

import os
import sys
import unicodedata
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTCollection, TTFont

logging.getLogger("fontTools.ttLib.tables._p_o_s_t").setLevel(logging.ERROR)


PREFERRED_FAMILIES = {
    "Tokyo Chill": ("Yu Gothic UI", "Yu Gothic", "Meiryo", "Noto Sans JP", "BIZ UDPGothic",
                    "Malgun Gothic", "Noto Sans KR", "Segoe UI", "Arial", "Noto Sans"),
    "OLD POP LOUNGE": ("Malgun Gothic", "Noto Sans KR", "Yu Gothic UI", "Yu Gothic", "Meiryo",
                       "Noto Sans JP", "BIZ UDPGothic", "Segoe UI", "Arial", "Noto Sans"),
}
SCRIPT_FAMILIES = {
    "ja": ("Yu Gothic UI", "Yu Gothic", "Meiryo", "Noto Sans JP", "BIZ UDPGothic"),
    "ko": ("Malgun Gothic", "Noto Sans KR", "Yu Gothic UI", "Yu Gothic", "Meiryo"),
    "en": ("Segoe UI", "Arial", "Noto Sans", "Yu Gothic UI", "Malgun Gothic"),
}


@dataclass(frozen=True)
class FontFace:
    path: Path
    index: int
    family: str
    subfamily: str
    weight: int
    style: str
    variable_axes: tuple[tuple[str, float, float, float], ...]
    codepoints: frozenset[int]

    def supports(self, char: str) -> bool:
        return ord(char) in self.codepoints or char.isspace()


def _name(ttfont: TTFont, ids: tuple[int, ...], fallback: str) -> str:
    table = ttfont.get("name")
    if not table:
        return fallback
    for name_id in ids:
        for record in table.names:
            if record.nameID == name_id:
                try:
                    value = record.toUnicode().strip()
                    if value:
                        return value
                except (UnicodeDecodeError, AttributeError):
                    continue
    return fallback


def _inspect_font(path: Path, index: int) -> FontFace | None:
    font = None
    try:
        font = TTFont(str(path), fontNumber=index, lazy=True, recalcBBoxes=False, recalcTimestamp=False)
        family = _name(font, (16, 1), path.stem)
        subfamily = _name(font, (17, 2), "Regular")
        weight = int(getattr(font.get("OS/2"), "usWeightClass", 400))
        italic = bool(getattr(font.get("post"), "italicAngle", 0)) or "italic" in subfamily.casefold()
        axes = tuple((axis.axisTag, float(axis.minValue), float(axis.defaultValue), float(axis.maxValue))
                     for axis in font.get("fvar", ()).axes) if "fvar" in font else ()
        cmap: set[int] = set()
        for table in font["cmap"].tables:
            if table.isUnicode():
                cmap.update(table.cmap)
        return FontFace(path, index, family, subfamily, weight,
                        "italic" if italic else "normal", axes, frozenset(cmap))
    except Exception:
        return None
    finally:
        if font is not None:
            font.close()


def installed_font_directories() -> tuple[Path, ...]:
    dirs: list[Path] = []
    if sys.platform == "win32":
        windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
        dirs.append(windows / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    else:
        dirs.extend((Path("/usr/share/fonts"), Path.home() / ".fonts", Path.home() / ".local/share/fonts"))
    return tuple(directory for directory in dirs if directory.is_dir())


class FontRegistry:
    """Cached index of installed fonts; proprietary font assets are never bundled."""
    def __init__(self, faces: tuple[FontFace, ...] | None = None):
        self.faces = faces if faces is not None else self._scan()
        self.by_family: dict[str, list[FontFace]] = {}
        for face in self.faces:
            self.by_family.setdefault(self._key(face.family), []).append(face)

    @staticmethod
    def _key(family: str) -> str:
        return " ".join(unicodedata.normalize("NFKC", family).casefold().split())

    @staticmethod
    def _font_files(directory: Path):
        for suffix in ("*.ttf", "*.otf", "*.ttc", "*.otc"):
            yield from directory.glob(suffix)

    def _scan(self) -> tuple[FontFace, ...]:
        faces = []
        for directory in installed_font_directories():
            for path in self._font_files(directory):
                indexes = (0,)
                if path.suffix.casefold() in (".ttc", ".otc"):
                    collection = None
                    try:
                        collection = TTCollection(str(path), lazy=True)
                        indexes = tuple(range(len(collection.fonts)))
                    except Exception:
                        continue
                    finally:
                        if collection is not None:
                            collection.close()
                faces.extend(face for index in indexes if (face := _inspect_font(path, index)) is not None)
        # Keep the cache lean: deduplicate duplicate family/style/cmap faces by file face.
        unique = {(str(face.path).casefold(), face.index): face for face in faces}
        return tuple(unique.values())

    def resolve(self, char: str, channel: str = "Tokyo Chill", preferred: str | None = None,
                weight: int = 700) -> FontFace:
        script = script_of(char)
        family_order = ([preferred] if preferred else []) + list(SCRIPT_FAMILIES[script])
        family_order += list(PREFERRED_FAMILIES.get(channel, ()))
        seen = set()
        for family in family_order:
            key = self._key(family)
            if key in seen:
                continue
            seen.add(key)
            candidates = self.by_family.get(key, ())
            candidates = [face for face in candidates if face.supports(char)]
            if candidates:
                return min(candidates, key=lambda face: (abs(face.weight - weight), face.style != "normal"))
        candidates = [face for face in self.faces if face.supports(char)]
        if candidates:
            return min(candidates, key=lambda face: (abs(face.weight - weight), face.style != "normal"))
        if self.faces:
            return self.faces[0]
        raise RuntimeError("No installed fonts with Unicode coverage were found.")

    def family_metadata(self) -> list[dict]:
        return [{"family": face.family, "subfamily": face.subfamily, "weight": face.weight,
                 "style": face.style, "path": str(face.path), "face_index": face.index,
                 "variable_axes": [{"tag": tag, "min": low, "default": default, "max": high}
                                   for tag, low, default, high in face.variable_axes]}
                for face in self.faces]


def script_of(char: str) -> str:
    name = unicodedata.name(char, "")
    if "HIRAGANA" in name or "KATAKANA" in name or "CJK" in name or "IDEOGRAPH" in name:
        return "ja"
    if "HANGUL" in name:
        return "ko"
    return "en"


@lru_cache(maxsize=1)
def get_font_registry() -> FontRegistry:
    return FontRegistry()
