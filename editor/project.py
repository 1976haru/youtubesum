"""A/B/C candidate documents, generator conversion, bridge background swaps and project files."""
from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from thumbnail_engine import APP_VERSION, STRATEGIES, TEMPLATE_MODE, create_candidate_images
from typography.layer_renderer import LayerRenderer, layout_text
from typography.text_style import get_preset
from typography.thumbnail_layouts import choose_layout
from typography_engine import choose_keyword

from .document import (BackgroundLayer, BadgeLayer, History, Layer, OverlayLayer, TextLayer, ThumbnailDocument,
                       layer_from_dict, new_id)
from .geometry import aabb, overlap_ratio
from .io_utils import atomic_write_json, read_image, read_json, write_image

PROJECT_FORMAT = "youtubesum-thumbnail-project"
PROJECT_VERSION = 1
PROJECT_FILENAME = "thumbnail_project.json"
SLOTS = ("A", "B", "C")
SLOT_LABELS = {"A": "A · PERSON", "B": "B · EMOTION / MEMORY", "C": "C · STORY / SCENERY"}
SHARED_ROLES = ("episode_badge", "channel_label")
TEXT_ROLES = ("main_title", "subtitle", "channel_label", "story_label", "episode_badge")


def slot_code(slot: str, channel: str) -> str:
    return STRATEGIES.get(channel, STRATEGIES["Tokyo Chill"])[SLOTS.index(slot)][0]


def image_key(slot: str, array: np.ndarray) -> str:
    digest = hashlib.sha1(np.ascontiguousarray(array).tobytes()).hexdigest()[:12]
    return f"asset://bg_{slot}_{digest}.png"


def _px_boxes(boxes, width: int = 1280, height: int = 720) -> list[list[float]]:
    result = []
    for box in boxes or ():
        if isinstance(box, dict):
            box = box.get("bbox", box.get("box", box.get("rect")))
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        x, y, w, h = map(float, box)
        if max(abs(x), abs(y), abs(w), abs(h)) <= 1:
            x, w, y, h = x * width, w * width, y * height, h * height
        result.append([round(x, 1), round(y, 1), round(w, 1), round(h, 1)])
    return result


def ink_box(layer: Layer) -> tuple[float, float, float, float]:
    """Document-space AABB of what is actually drawn; text uses its line extents, not the wrap box."""
    if not isinstance(layer, TextLayer):
        return aabb(layer)
    layout = layout_text(layer)
    widths = layout.line_widths or (0.0,)
    if layer.alignment == "center":
        lefts = [(layer.width - width) / 2 for width in widths]
    elif layer.alignment == "right":
        lefts = [layer.width - width for width in widths]
    else:
        lefts = [0.0 for _ in widths]
    x0 = min(lefts); x1 = max(left + width for left, width in zip(lefts, widths))
    y0 = (layer.height - layout.content_height) / 2; y1 = y0 + layout.content_height
    proxy = Layer(x=layer.x + x0, y=layer.y + y0, width=max(1.0, x1 - x0), height=max(1.0, y1 - y0))
    # Rotate about the *layer* centre, not the ink centre.
    cx, cy = layer.center
    pcx, pcy = proxy.center
    angle = math.radians(layer.rotation)
    dx, dy = pcx - cx, pcy - cy
    proxy.x += (dx * math.cos(angle) - dy * math.sin(angle)) - dx
    proxy.y += (dx * math.sin(angle) + dy * math.cos(angle)) - dy
    proxy.rotation = layer.rotation
    return aabb(proxy)


def sync_text_height(layer: Layer, keep_center: bool = True) -> None:
    """Text boxes hug their content height so the selection box matches the glyphs."""
    if isinstance(layer, TextLayer) and layer.auto_height:
        height = round(layout_text(layer).content_height, 1)
        if abs(height - layer.height) > 0.05:
            if keep_center:
                layer.y += (layer.height - height) / 2
            layer.height = height


def preset_text_props(style_name: str, channel: str, palette: dict | None = None) -> dict[str, Any]:
    """TextLayer properties for a named channel style (palette sidecar values win when present)."""
    preset = get_preset(style_name, channel)
    palette = palette or {}
    tokyo = channel == "Tokyo Chill"
    return {"channel": channel, "fill": palette.get("fill_color") or preset.fill,
            "gradient": not palette.get("fill_color"), "gradient_end": preset.gradient_end,
            "outline_color": palette.get("stroke_color") or preset.outline,
            "outline_width": float(palette.get("outline_width") or preset.outline_width),
            "secondary_outline_width": 0.0,
            "shadow_color": preset.shadow, "shadow_blur": float(preset.shadow_blur), "shadow_x": 4.0, "shadow_y": 5.0,
            "shadow_opacity": round(0.75 * float(palette.get("shadow_strength") or 0.9), 2),
            "glow_color": preset.glow, "glow_blur": float(preset.glow_blur),
            "glow_opacity": round((0.55 if tokyo else 0.22) * float(palette.get("glow_strength") or 1.0), 2),
            "letter_spacing": float(preset.letter_spacing),
            "highlight_color": palette.get("highlight_color") or preset.accent}


# One-click text effect cards (applied on top of the current colours).
TEXT_EFFECTS = {
    "굵은 외곽선": {"outline_width": 16.0, "secondary_outline_width": 0.0, "glow_opacity": 0.0, "shadow_opacity": 0.6},
    "이중 외곽선": {"outline_width": 10.0, "secondary_outline_width": 6.0, "secondary_outline_color": "#FFFFFF"},
    "네온 글로우": {"glow_opacity": 0.75, "glow_blur": 18.0, "outline_width": 6.0},
    "소프트 섀도": {"shadow_opacity": 0.7, "shadow_blur": 14.0, "shadow_x": 3.0, "shadow_y": 8.0, "glow_opacity": 0.0},
    "시네마 플랫": {"outline_width": 0.0, "secondary_outline_width": 0.0, "glow_opacity": 0.0, "shadow_opacity": 0.45,
                "shadow_blur": 18.0, "gradient": False},
    "그라디언트": {"gradient": True},
}

CHANNEL_PALETTES = {
    "Tokyo Chill": (("Neon Night", "#FFFFFF", "#1A0B2E", "#FF4FD8"), ("Rain Blue", "#F4FBFF", "#0B1F33", "#5FD3FF"),
                    ("Cinema Gold", "#FFFFFF", "#141414", "#FFD34D"), ("Pink Haze", "#FFF6FB", "#3A1030", "#FF8FB8")),
    "OLD POP LOUNGE": (("Warm Cream", "#FFF4DC", "#3A2618", "#F2C46B"), ("First Snow", "#FFFFFF", "#1E354A", "#B9E8FF"),
                       ("Autumn", "#FFF4E3", "#3C271B", "#D99151"), ("Calm Navy", "#F7FBFF", "#233648", "#A7C9E6")),
}


def fit_backdrop(document: ThumbnailDocument) -> None:
    """Size the title gradient to the title: full-width when centred, else the title's side."""
    title, backdrop = document.by_role("main_title"), document.by_role("title_backdrop")
    if title is None or backdrop is None:
        return
    top_anchor = title.y + title.height / 2 < document.canvas_height / 2
    if title.alignment == "center":
        left, right = 0.0, float(document.canvas_width)
    elif title.x + title.width / 2 > document.canvas_width / 2:
        left, right = max(0.0, title.x - 220), float(document.canvas_width)
    else:
        left, right = 0.0, min(float(document.canvas_width), title.x + title.width + 220)
    if top_anchor:
        top, bottom = 0.0, min(float(document.canvas_height), title.y + title.height + 120)
    else:
        top, bottom = max(0.0, title.y - 120), float(document.canvas_height)
    backdrop.x, backdrop.y, backdrop.width, backdrop.height = left, top, right - left, bottom - top
    backdrop.direction = "top" if top_anchor else "bottom"


def default_document(slot: str, channel: str, style_name: str, texts: dict[str, str], background_key: str,
                     subject_boxes=(), safe_zones=(), palette: dict | None = None,
                     title_size: int = 108) -> ThumbnailDocument:
    """Convert the A/B/C generator's layout choice into an editable layer document."""
    code = slot_code(slot, channel)
    preset = get_preset(style_name, channel)
    subjects, hazards = _px_boxes(subject_boxes), _px_boxes(safe_zones)
    layout = choose_layout(code, channel, texts.get("story", ""), texts.get("episode", ""), title_size,
                           subject_boxes=subjects, safe_zones=hazards)
    palette = palette or {}
    tokyo = channel == "Tokyo Chill"
    document = ThumbnailDocument(channel=channel, candidate_type=code, subject_boxes=subjects, safe_zones=hazards,
                                 metadata={"style": preset.name, "style_key": preset.key, "slot": slot})
    document.add(BackgroundLayer(name="배경", role="background", source=background_key, width=1280, height=720))
    tx, ty, tw, th = layout.title_box
    title_text = (texts.get("title") or ("思い出の夜" if tokyo else "懐かしい記憶")).strip()
    title = TextLayer(name="메인 제목", role="main_title", text=title_text, x=tx, y=ty, width=tw, height=th,
                      font_size=float(layout.nominal_size), font_weight=900, line_spacing=1.1,
                      alignment=layout.align, highlight_word=choose_keyword(title_text), max_lines=layout.max_lines,
                      **preset_text_props(style_name, channel, palette))
    top_anchor = ty < 300
    sync_text_height(title, keep_center=False)
    # Lower titles sit on the layout box's bottom edge, upper titles on its top edge.
    title.y = ty if top_anchor else ty + th - title.height - 12
    # Soft separation layer behind the title, editable and never baked into the background.
    document.add(OverlayLayer(name="제목 그라디언트", role="title_backdrop", kind="gradient_black", color="#000000",
                              strength=0.66 if tokyo else 0.55, blur=70, radius=0))
    document.add(title)
    subtitle_text = (texts.get("subtitle") or "").strip()
    if subtitle_text:
        subtitle = TextLayer(name="부제", role="subtitle", text=subtitle_text, channel=channel, x=48,
                             y=652 if tokyo else 646, width=1100, height=48, font_size=30 if tokyo else 34,
                             font_weight=700, fill="#F4F7FF" if tokyo else "#FFF4E0", outline_color=preset.outline,
                             outline_width=3.0, shadow_color=preset.shadow, shadow_opacity=0.55, shadow_blur=4,
                             shadow_x=2, shadow_y=2, letter_spacing=0.6 if tokyo else 0.2, max_lines=1,
                             alignment="left")
        sync_text_height(subtitle, keep_center=False)
        subtitle.y = min(720 - subtitle.height - 14, subtitle.y)
        document.add(subtitle)
    document.add(BadgeLayer(name="채널 라벨", role="channel_label", text=channel.upper(), channel=channel,
                            shape="tag" if tokyo else "rounded", x=30, y=22, width=250, height=52,
                            fill=preset.outline, border_color=preset.accent, border_width=3, font_size=24,
                            radius=10))
    role_name = {"A": "PERSON", "B": "EMOTION" if tokyo else "MEMORY", "C": "STORY" if tokyo else "SCENERY"}[slot]
    story_value = texts.get("story") if texts.get("story") not in ("", "자동", "Auto", None) else role_name
    badge_w, badge_h = 280.0, 58.0
    if slot == "A":
        # A: the protagonist label rides just above the title block.
        bx = title.x if layout.align != "right" else title.x + title.width - badge_w
        by = max(96.0, title.y - badge_h - 10)
    else:
        bx, by = 1280 - 30 - badge_w, 92.0  # B/C: tucked under the EP badge, away from the title
    document.add(BadgeLayer(name="스토리 라벨", role="story_label", text=f"{slot} · {story_value}", channel=channel,
                            shape="sticker" if tokyo else "ribbon", x=bx, y=by, width=badge_w, height=badge_h,
                            fill=preset.outline, border_color=preset.accent, border_width=3, font_size=26))
    document.add(BadgeLayer(name="EP 배지", role="episode_badge", text=texts.get("episode") or "EP.001",
                            channel=channel, shape="pill", x=1040, y=22, width=210, height=60, fill=preset.outline,
                            border_color=preset.accent, border_width=3, font_size=28))
    # Generated defaults must not cover faces; the user can still move anything afterwards.
    relayout_to_safe(document, subject_threshold=0.12, roles=("main_title",))
    fit_backdrop(document)
    story = document.by_role("story_label")
    obstacles = [ink_box(layer) for layer in document.ordered() if layer.type == "text"] + document.subject_boxes
    if story is not None and any(overlap_ratio(aabb(story), box) > 0 for box in obstacles):
        for x, y in ((1280 - 30 - badge_w, 92.0), (30.0, 92.0), (30.0, title.y - badge_h - 10),
                     (1280 - 30 - badge_w, title.y - badge_h - 10)):
            if y > 80 and not any(overlap_ratio((x, y, badge_w, badge_h), box) > 0 for box in obstacles):
                story.x, story.y = x, y
                break
    return document


@dataclass
class ProjectState:
    channel: str = "Tokyo Chill"
    style: str = "Japanese Impact"
    texts: dict[str, str] = field(default_factory=lambda: {"title": "", "subtitle": "", "episode": "EP.001", "story": ""})
    documents: dict[str, ThumbnailDocument] = field(default_factory=dict)
    defaults: dict[str, dict] = field(default_factory=dict)
    images: dict[str, np.ndarray] = field(default_factory=dict)
    histories: dict[str, History] = field(default_factory=lambda: {slot: History() for slot in SLOTS})
    selected_slot: str = "A"
    selected_layers: dict[str, str | None] = field(default_factory=dict)
    zoom: str = "Fit"
    project_path: Path | None = None
    source_background: str = ""
    bridge: dict[str, Any] = field(default_factory=dict)
    palette: dict[str, Any] = field(default_factory=dict)
    subject_points: dict[str, Any] = field(default_factory=dict)
    shared_lock: bool = True
    reference_image: str = ""

    @property
    def document(self) -> ThumbnailDocument | None:
        return self.documents.get(self.selected_slot)

    def register_image(self, slot: str, array: np.ndarray) -> str:
        key = image_key(slot, array)
        self.images[key] = array
        return key

    def background_image(self, slot: str | None = None) -> np.ndarray | None:
        document = self.documents.get(slot or self.selected_slot)
        background = document.background() if document else None
        return self.images.get(background.source) if background else None


def generate_project(source: str | Path, channel: str, style: str, texts: dict[str, str], *,
                     focus_mode: str = "자동", protagonist=None, counterpart=None, palette: dict | None = None,
                     bridge: dict | None = None, title_size: int = 108) -> ProjectState:
    """Run the existing A/B/C framing generator (text-free) and wrap each result as a document."""
    generated = create_candidate_images(str(source), channel, TEMPLATE_MODE, focus_mode, protagonist, counterpart,
                                        texts.get("story", "자동"), texts.get("episode", "EP.001"), "", "", style,
                                        render_text=False)
    state = ProjectState(channel=channel, style=style, texts=dict(texts), source_background=str(source),
                         palette=dict(palette or {}), bridge=dict(bridge or {}),
                         subject_points={key: list(value) for key, value in (("protagonist", protagonist),
                                                                              ("counterpart", counterpart)) if value})
    for slot, candidate in zip(SLOTS, generated):
        key = state.register_image(slot, candidate.image)
        typography = candidate.typography or {}
        document = default_document(slot, channel, style, texts, key, typography.get("subject_boxes", ()),
                                    typography.get("safe_zones", ()), palette, title_size)
        document.bridge = {"crop_box": list(candidate.crop_box) if candidate.crop_box else None,
                           "composition": candidate.composition}
        state.documents[slot] = document
        state.defaults[slot] = document.to_dict()
        title = document.by_role("main_title")
        state.selected_layers[slot] = title.id if title else None
    return state


# ----- A/B/C operations -----
def _clone_layer(layer: Layer) -> Layer:
    clone = layer_from_dict(copy.deepcopy(layer.to_dict()))
    clone.id = new_id()
    return clone


def copy_layer_to(state: ProjectState, source_slot: str, layer_id: str, targets=SLOTS) -> list[str]:
    """Copy one layer to other candidates; a same-role layer is replaced in place, else added on top."""
    source = state.documents[source_slot].get(layer_id)
    if source is None or source.type == "background":
        return []
    changed = []
    for slot in targets:
        if slot == source_slot or slot not in state.documents:
            continue
        document = state.documents[slot]
        state.histories[slot].push(document.to_dict())
        clone = _clone_layer(source)
        existing = document.by_role(source.role) if source.role else None
        if existing is not None:
            clone.z_index = existing.z_index
            document.layers[document.layers.index(existing)] = clone
            document.normalize_z()
        else:
            document.add(clone)
        changed.append(slot)
    return changed


def copy_typography_layout(state: ProjectState, source_slot: str, targets=SLOTS) -> list[str]:
    """Replace every non-background layer of the targets with copies of the source candidate's layers."""
    source = state.documents[source_slot]
    changed = []
    for slot in targets:
        if slot == source_slot or slot not in state.documents:
            continue
        document = state.documents[slot]
        state.histories[slot].push(document.to_dict())
        background = document.background()
        layers = [background] if background else []
        layers += [_clone_layer(layer) for layer in source.ordered() if layer.type != "background"]
        document._reindex(layers)
        changed.append(slot)
    return changed


def reset_candidate(state: ProjectState, slot: str) -> None:
    document = state.documents[slot]
    state.histories[slot].push(document.to_dict())
    default = ThumbnailDocument.from_dict(state.defaults[slot])
    current_background = document.background()
    restored_background = default.background()
    if current_background and restored_background:
        restored_background.source = current_background.source  # keep the newest bridge background
    default.subject_boxes, default.safe_zones = document.subject_boxes, document.safe_zones
    state.documents[slot] = default


def propagate_shared(state: ProjectState, source_slot: str, layer: Layer) -> list[str]:
    """With the shared lock on, EP/channel label text follows across A/B/C."""
    if not state.shared_lock or layer.role not in SHARED_ROLES:
        return []
    changed = []
    for slot, document in state.documents.items():
        if slot == source_slot:
            continue
        other = document.by_role(layer.role)
        if other is not None and getattr(other, "text", None) != getattr(layer, "text", None):
            other.text = layer.text
            changed.append(slot)
    return changed


# ----- bridge background replacement -----
def find_collisions(document: ThumbnailDocument, subject_threshold: float = 0.08, safe_threshold: float = 0.10):
    collisions = []
    for layer in document.ordered():
        if layer.type not in ("text", "badge") or not layer.visible:
            continue
        box = ink_box(layer)
        for subject in document.subject_boxes:
            ratio = overlap_ratio(box, subject)
            if ratio > subject_threshold:
                collisions.append({"layer": layer.id, "name": layer.name, "kind": "subject", "ratio": round(ratio, 3)})
        for zone in document.safe_zones:
            ratio = overlap_ratio(box, zone)
            if ratio > safe_threshold:
                collisions.append({"layer": layer.id, "name": layer.name, "kind": "safe_zone", "ratio": round(ratio, 3)})
    return collisions


def _collision_cost(document: ThumbnailDocument, box, others=()) -> float:
    return (sum(overlap_ratio(box, subject) * 2 for subject in document.subject_boxes)
            + sum(overlap_ratio(box, zone) * 5 for zone in document.safe_zones)
            + sum(overlap_ratio(box, other) * 3 for other in others))


def relayout_to_safe(document: ThumbnailDocument, subject_threshold: float = 0.05, roles=None) -> list[str]:
    """Move colliding text/badge layers to the nearest low-collision anchor (size and style unchanged)."""
    moved = []
    width, height = document.canvas_width, document.canvas_height
    for layer in document.ordered():
        if layer.type not in ("text", "badge") or not layer.visible or layer.locked:
            continue
        if roles is not None and layer.role not in roles:
            continue
        box = ink_box(layer)
        cost = _collision_cost(document, box)
        if cost <= subject_threshold * 2:
            continue
        others = [ink_box(other) for other in document.ordered()
                  if other is not layer and other.visible and other.type in ("text", "badge")
                  and other.role not in ("story_label",)]
        bx, by, bw, bh = box
        xs = (bx, width - bx - bw, (width - bw) / 2, 48.0, width - 48.0 - bw)
        ys = (by, by - 60, by - 120, by + 60, 110.0, height - bh - 80.0)
        candidates = [(x, y) for x in xs for y in ys
                      if 0 <= x <= width - bw and 80 <= y <= height - bh - 20]
        if not candidates:
            continue
        best = min(candidates, key=lambda position: (
            round(_collision_cost(document, (position[0], position[1], bw, bh), others), 2),
            abs(position[0] - bx) + abs(position[1] - by)))
        if _collision_cost(document, (best[0], best[1], bw, bh), others) < _collision_cost(document, box, others):
            layer.x += best[0] - bx
            layer.y += best[1] - by
            moved.append(layer.id)
    return moved


def replace_backgrounds(state: ProjectState, backgrounds: dict[str, np.ndarray], subjects: dict | None = None,
                        safe_zones: dict | None = None) -> dict[str, list]:
    """Swap only background layers (bridge regenerate/edit); text/badge/shape layers are untouched."""
    collisions = {}
    for slot, array in backgrounds.items():
        document = state.documents.get(slot)
        if document is None:
            continue
        state.histories[slot].push(document.to_dict())
        key = state.register_image(slot, array)
        background = document.background()
        if background is None:
            background = BackgroundLayer(name="배경", role="background", width=1280, height=720)
            document.add(background)
            document.move(background.id, -len(document.layers))
        background.source = key
        if subjects is not None and slot in subjects:
            document.subject_boxes = _px_boxes(subjects[slot])
        if safe_zones is not None and slot in safe_zones:
            document.safe_zones = _px_boxes(safe_zones[slot])
        collisions[slot] = find_collisions(document)
    return collisions


# ----- persistence -----
def assets_dir(project_path: Path) -> Path:
    return project_path.with_name(project_path.stem + "_assets")


def save_project(state: ProjectState, path: str | Path, *, app_version: str = APP_VERSION) -> Path:
    """Write thumbnail_project.json + content-addressed background PNGs; sources are never modified."""
    path = Path(path)
    folder = assets_dir(path)
    referenced = {layer.source for document in state.documents.values() for layer in document.layers
                  if getattr(layer, "source", "").startswith("asset://")}
    referenced |= {layer["source"] for default in state.defaults.values() for layer in default.get("layers", ())
                   if str(layer.get("source", "")).startswith("asset://")}
    assets = {}
    for key in sorted(referenced):
        image = state.images.get(key)
        name = key.split("://", 1)[1]
        target = folder / name
        if image is not None and not target.is_file():
            write_image(target, image)
        if image is not None or target.is_file():
            assets[key] = f"{folder.name}/{name}"
    payload = {
        "format": PROJECT_FORMAT, "project_version": PROJECT_VERSION, "document_version": 1,
        "app_version": app_version, "project_path": str(path), "channel": state.channel, "style": state.style,
        "texts": dict(state.texts), "source_background": state.source_background, "bridge": state.bridge,
        "palette": state.palette, "subject_points": state.subject_points, "shared_lock": state.shared_lock,
        "reference_image": state.reference_image,
        "selected_candidate": state.selected_slot, "selected_layers": dict(state.selected_layers),
        "editor_zoom": state.zoom, "assets": assets,
        "candidates": {slot: document.to_dict() for slot, document in state.documents.items()},
        "defaults": state.defaults,
    }
    atomic_write_json(path, payload)
    state.project_path = path
    return path


def load_project(path: str | Path) -> ProjectState:
    path = Path(path)
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get("format") != PROJECT_FORMAT:
        raise ValueError(f"썸네일 프로젝트 파일이 아닙니다: {path}")
    if int(payload.get("project_version", 1)) > PROJECT_VERSION:
        raise ValueError("이 프로젝트는 더 새로운 버전에서 저장되었습니다.")
    state = ProjectState(channel=payload.get("channel", "Tokyo Chill"), style=payload.get("style", ""),
                         texts=dict(payload.get("texts", {})), source_background=payload.get("source_background", ""),
                         bridge=dict(payload.get("bridge", {})), palette=dict(payload.get("palette", {})),
                         subject_points=dict(payload.get("subject_points", {})),
                         shared_lock=bool(payload.get("shared_lock", True)),
                         reference_image=payload.get("reference_image", ""),
                         selected_slot=payload.get("selected_candidate", "A"),
                         selected_layers=dict(payload.get("selected_layers", {})),
                         zoom=str(payload.get("editor_zoom", "Fit")), project_path=path)
    for key, relative in payload.get("assets", {}).items():
        image = read_image(path.parent / relative)
        if image is not None:
            state.images[key] = image
    state.documents = {slot: ThumbnailDocument.from_dict(data) for slot, data in payload.get("candidates", {}).items()}
    state.defaults = dict(payload.get("defaults", {}))
    for slot in state.documents:
        state.defaults.setdefault(slot, state.documents[slot].to_dict())
    return state


def export_candidate(state: ProjectState, slot: str, path: str | Path, renderer: LayerRenderer | None = None) -> Path:
    renderer = renderer or LayerRenderer()
    return write_image(path, renderer.render(state.documents[slot], state.images))
