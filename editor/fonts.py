"""Installed-font browser model: family catalog, CJK coverage filters, favorites/recent, fallback checks.

Fonts come only from the cached system registry; nothing is bundled or downloaded.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from typography.font_registry import FontRegistry, get_font_registry

from .io_utils import atomic_write_json, read_json

JAPANESE_PROBE = "あア漢字夜"
KOREAN_PROBE = "한글밤"
LATIN_PROBE = "AaZz09"
DISPLAY_WORDS = re.compile(r"(black|heavy|bold|display|impact|poster|extra|ultra|pop|round|maru|gothic)", re.I)
SCRIPT_TABS = ("Japanese", "Korean", "Latin", "All")


@dataclass(frozen=True)
class FontFamily:
    name: str
    weights: tuple[int, ...]
    japanese: bool
    korean: bool
    latin: bool
    display: bool
    face_count: int

    @property
    def scripts(self) -> str:
        return " ".join(label for flag, label in ((self.japanese, "JA"), (self.korean, "KO"), (self.latin, "EN")) if flag)


def _covers(faces, probe: str) -> bool:
    return any(all(face.supports(char) for char in probe) for face in faces)


@lru_cache(maxsize=4)
def _catalog_for(registry_id: int, registry: FontRegistry) -> tuple[FontFamily, ...]:
    families: dict[str, list] = {}
    names: dict[str, str] = {}
    for face in registry.faces:
        if face.family.startswith("@"):
            continue  # vertical-writing aliases
        key = FontRegistry._key(face.family)
        families.setdefault(key, []).append(face)
        names.setdefault(key, face.family)
    catalog = []
    for key, faces in families.items():
        weights = tuple(sorted({face.weight for face in faces}))
        catalog.append(FontFamily(names[key], weights, _covers(faces, JAPANESE_PROBE), _covers(faces, KOREAN_PROBE),
                                  _covers(faces, LATIN_PROBE),
                                  max(weights) >= 700 or bool(DISPLAY_WORDS.search(names[key])), len(faces)))
    return tuple(sorted(catalog, key=lambda family: family.name.casefold()))


def build_catalog(registry: FontRegistry | None = None) -> tuple[FontFamily, ...]:
    """Cached per registry; the Windows font folder is scanned once per process, never per edit."""
    registry = registry or get_font_registry()
    return _catalog_for(id(registry), registry)


def filter_families(catalog, script: str = "All", query: str = "", bold_first: bool = False,
                    favorites=(), recent=(), only_favorites: bool = False) -> list[FontFamily]:
    query = " ".join(query.casefold().split())
    favorite_keys = {FontRegistry._key(name) for name in favorites}
    recent_order = {FontRegistry._key(name): index for index, name in enumerate(recent)}
    result = []
    for family in catalog:
        if script == "Japanese" and not family.japanese:
            continue
        if script == "Korean" and not family.korean:
            continue
        if script == "Latin" and not family.latin:
            continue
        if query and query not in family.name.casefold():
            continue
        key = FontRegistry._key(family.name)
        if only_favorites and key not in favorite_keys:
            continue
        result.append(family)

    def rank(family: FontFamily):
        key = FontRegistry._key(family.name)
        return (key not in favorite_keys, recent_order.get(key, 10_000),
                (not family.display) if bold_first else False, family.name.casefold())
    return sorted(result, key=rank)


def family_faces(family: str, registry: FontRegistry | None = None):
    registry = registry or get_font_registry()
    return registry.by_family.get(FontRegistry._key(family), [])


def missing_glyphs(family: str, text: str, registry: FontRegistry | None = None) -> list[str]:
    """Characters the chosen family cannot draw (they will render with a fallback font)."""
    faces = family_faces(family, registry)
    if not family:
        return []
    missing = []
    for char in dict.fromkeys(text or ""):
        if char.isspace():
            continue
        if not any(face.supports(char) for face in faces):
            missing.append(char)
    return missing


def nearest_weight(family: str, wanted: int, registry: FontRegistry | None = None) -> int:
    weights = sorted({face.weight for face in family_faces(family, registry)})
    return min(weights, key=lambda weight: abs(weight - wanted)) if weights else int(wanted)


class EditorSettings:
    """Favorites / recent fonts and styles, persisted atomically beside the app logs."""

    def __init__(self, path: str | Path | None):
        self.path = Path(path) if path else None
        data = read_json(self.path, {}) if self.path else {}
        data = data if isinstance(data, dict) else {}
        self.favorite_fonts: list[str] = list(data.get("favorite_fonts", []))
        self.recent_fonts: list[str] = list(data.get("recent_fonts", []))
        self.favorite_styles: list[str] = list(data.get("favorite_styles", []))
        self.recent_styles: list[str] = list(data.get("recent_styles", []))
        self.autosave: bool = bool(data.get("autosave", False))

    def to_dict(self) -> dict:
        return {"favorite_fonts": self.favorite_fonts, "recent_fonts": self.recent_fonts,
                "favorite_styles": self.favorite_styles, "recent_styles": self.recent_styles,
                "autosave": self.autosave}

    def save(self) -> None:
        if self.path:
            try:
                atomic_write_json(self.path, self.to_dict())
            except OSError:
                pass

    @staticmethod
    def _bump(items: list[str], value: str, limit: int) -> None:
        if value in items:
            items.remove(value)
        items.insert(0, value)
        del items[limit:]

    def use_font(self, family: str) -> None:
        self._bump(self.recent_fonts, family, 12); self.save()

    def use_style(self, style_key: str) -> None:
        self._bump(self.recent_styles, style_key, 8); self.save()

    def toggle_favorite_font(self, family: str) -> bool:
        if family in self.favorite_fonts:
            self.favorite_fonts.remove(family); state = False
        else:
            self.favorite_fonts.insert(0, family); state = True
        self.save()
        return state

    def toggle_favorite_style(self, style_key: str) -> bool:
        if style_key in self.favorite_styles:
            self.favorite_styles.remove(style_key); state = False
        else:
            self.favorite_styles.insert(0, style_key); state = True
        self.save()
        return state
