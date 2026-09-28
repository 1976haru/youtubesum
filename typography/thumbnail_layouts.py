"""Distinct thumbnail title/label layouts with safe-zone and subject avoidance."""
from __future__ import annotations

from dataclasses import dataclass


CANVAS_SIZE = (1280, 720)


@dataclass(frozen=True)
class ThumbnailLayout:
    code: str
    title_box: tuple[int, int, int, int]
    align: str
    badge_box: tuple[int, int, int, int]
    badge_kind: str
    badge_text: str
    max_lines: int
    nominal_size: int


_LAYOUT_OPTIONS = {
    "A_PERSON": {
        "Tokyo Chill": (((42, 380, 790, 280), "left"), ((448, 430, 790, 250), "right")),
        "OLD POP LOUNGE": (((52, 370, 840, 290), "left"), ((388, 430, 840, 250), "right")),
    },
    "B_EMOTION": {
        "Tokyo Chill": (((206, 370, 868, 290), "center"), ((220, 290, 850, 260), "center")),
        "OLD POP LOUNGE": (((148, 370, 984, 290), "center"), ((150, 288, 980, 270), "center")),
    },
    "B_MEMORY": {
        "Tokyo Chill": (((206, 370, 868, 290), "center"), ((220, 290, 850, 260), "center")),
        "OLD POP LOUNGE": (((148, 370, 984, 290), "center"), ((150, 288, 980, 270), "center")),
    },
    "C_STORY": {
        "Tokyo Chill": (((52, 94, 720, 290), "left"), ((500, 94, 725, 290), "right")),
        "OLD POP LOUNGE": (((58, 92, 840, 290), "left"), ((380, 92, 840, 290), "right")),
    },
    "C_SCENERY": {
        "Tokyo Chill": (((52, 94, 720, 290), "left"), ((500, 94, 725, 290), "right")),
        "OLD POP LOUNGE": (((58, 92, 840, 290), "left"), ((380, 92, 840, 290), "right")),
    },
}


def _overlap_ratio(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a; bx, by, bw, bh = b
    overlap = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))
    return overlap / max(1, aw * ah)


def _box(value, canvas_size=CANVAS_SIZE):
    if isinstance(value, dict):
        value = value.get("bbox", value.get("box", value.get("rect")))
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    x, y, w, h = map(float, value)
    if max(abs(x), abs(y), abs(w), abs(h)) <= 1.0:
        width, height = canvas_size
        return round(x * width), round(y * height), round(w * width), round(h * height)
    return round(x), round(y), round(w), round(h)


def choose_layout(code: str, channel: str, story_type: str, episode: str, title_size: str = "Auto",
                  subject_boxes=(), safe_zones=(), canvas_size=CANVAS_SIZE) -> ThumbnailLayout:
    options = _LAYOUT_OPTIONS.get(code, _LAYOUT_OPTIONS["A_PERSON"])[channel]
    subjects = [box for item in subject_boxes if (box := _box(item, canvas_size))]
    hazards = [box for item in safe_zones if (box := _box(item, canvas_size))]
    best = None
    for candidate, align in options:
        subject_cost = sum(_overlap_ratio(candidate, box) for box in subjects)
        safe_cost = sum(_overlap_ratio(candidate, box) for box in hazards)
        anchor_bias = 0.0
        if code.startswith("C_"):
            anchor_bias = 0 if (candidate[0] < canvas_size[0] / 2) == (align == "left") else 0.08
        score = safe_cost * 10 + subject_cost * 2 + anchor_bias
        if best is None or score < best[0]:
            best = (score, candidate, align)
    _, title_box, align = best
    names = {"A_PERSON": "PERSON", "B_EMOTION": "EMOTION", "B_MEMORY": "MEMORY",
             "C_STORY": "STORY", "C_SCENERY": "SCENERY"}
    badge_kind = "ribbon" if channel == "OLD POP LOUNGE" else "sticker"
    if code.startswith("A_"):
        bx, by = (40, 360) if title_box[0] < canvas_size[0] / 2 else (930, 360)
    elif code.startswith("B_"):
        bx, by = canvas_size[0] - 300, 20
        badge_kind = "ep"
    else:
        bx, by = (canvas_size[0] - 300, 20) if align == "left" else (32, 98)
        badge_kind = "mini"
    font = int(title_size) if isinstance(title_size, (int, float)) else {"Auto": 106, "Small": 78, "Medium": 100, "Large": 126}.get(title_size, 106)
    if channel == "OLD POP LOUNGE":
        font = round(font * 1.12)
    if code.startswith("B_"):
        font = round(font * 0.92)
    if code.startswith("C_"):
        font = round(font * 0.88)
    return ThumbnailLayout(code, title_box, align, (bx, by, 280, 76), badge_kind,
                           f"{names.get(code, 'STORY')} · {episode or 'EP.001'}",
                           3, font)
