"""Non-destructive thumbnail document: ordered, typed layers with JSON round-tripping."""
from __future__ import annotations

import copy
import uuid
from dataclasses import asdict, dataclass, field, fields
from typing import Any

CANVAS_SIZE = (1280, 720)
DOCUMENT_VERSION = 1
LAYER_TYPES = ("background", "image", "text", "badge", "shape", "overlay")
OVERLAY_KINDS = ("gradient_black", "gradient_white", "plate", "label_strip", "vignette", "blur_plate")
BADGE_SHAPES = ("pill", "rounded", "ribbon", "sticker", "tag")
SHAPE_KINDS = ("rect", "rounded", "ellipse")


def new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass
class Layer:
    id: str = field(default_factory=new_id)
    type: str = "shape"
    name: str = ""
    role: str = ""
    visible: bool = True
    locked: bool = False
    z_index: int = 0
    x: float = 0.0
    y: float = 0.0
    width: float = 100.0
    height: float = 100.0
    rotation: float = 0.0
    opacity: float = 1.0

    @property
    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2

    def bounds(self) -> tuple[float, float, float, float]:
        return self.x, self.y, self.width, self.height

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BackgroundLayer(Layer):
    type: str = "background"
    source: str = ""
    fit: str = "cover"
    locked: bool = True


@dataclass
class ImageLayer(Layer):
    type: str = "image"
    source: str = ""
    fit: str = "contain"


@dataclass
class TextLayer(Layer):
    type: str = "text"
    text: str = ""
    channel: str = "Tokyo Chill"
    font_family: str = ""
    font_weight: int = 900
    font_size: float = 96.0
    fill: str = "#FFFFFF"
    gradient: bool = False
    gradient_end: str = "#FFFFFF"
    outline_color: str = "#111111"
    outline_width: float = 8.0
    secondary_outline_color: str = "#000000"
    secondary_outline_width: float = 0.0
    shadow_color: str = "#000000"
    shadow_x: float = 4.0
    shadow_y: float = 5.0
    shadow_blur: float = 6.0
    shadow_opacity: float = 0.6
    glow_color: str = "#FFFFFF"
    glow_blur: float = 0.0
    glow_opacity: float = 0.0
    letter_spacing: float = 0.0
    line_spacing: float = 1.12
    alignment: str = "left"
    highlight_word: str = ""
    highlight_color: str = "#FFE23A"
    highlight_scale: float = 1.08
    max_lines: int = 3
    manual_line_breaks: bool = True
    auto_height: bool = True


@dataclass
class BadgeLayer(Layer):
    type: str = "badge"
    text: str = ""
    channel: str = "Tokyo Chill"
    shape: str = "pill"
    fill: str = "#111827"
    text_color: str = "#FFFFFF"
    border_color: str = "#62E8FF"
    border_width: float = 3.0
    radius: float = 14.0
    padding: float = 14.0
    font_family: str = ""
    font_weight: int = 800
    font_size: float = 26.0


@dataclass
class ShapeLayer(Layer):
    type: str = "shape"
    shape: str = "rounded"
    fill: str = "#000000"
    border_color: str = "#FFFFFF"
    border_width: float = 0.0
    radius: float = 18.0


@dataclass
class OverlayLayer(Layer):
    type: str = "overlay"
    kind: str = "gradient_black"
    color: str = "#000000"
    direction: str = "up"
    blur: float = 18.0
    radius: float = 24.0
    strength: float = 0.65


LAYER_CLASSES = {"background": BackgroundLayer, "image": ImageLayer, "text": TextLayer,
                 "badge": BadgeLayer, "shape": ShapeLayer, "overlay": OverlayLayer}


def layer_from_dict(data: dict[str, Any]) -> Layer:
    cls = LAYER_CLASSES.get(str(data.get("type", "")), None)
    if cls is None:
        raise ValueError(f"Unknown layer type: {data.get('type')!r}")
    known = {item.name for item in fields(cls)}
    values = {key: value for key, value in data.items() if key in known}
    layer = cls(**values)
    # JSON stores tuples as lists and numbers loosely; normalize the transform.
    for key in ("x", "y", "width", "height", "rotation", "opacity"):
        setattr(layer, key, float(getattr(layer, key)))
    return layer


@dataclass
class ThumbnailDocument:
    canvas_width: int = CANVAS_SIZE[0]
    canvas_height: int = CANVAS_SIZE[1]
    channel: str = "Tokyo Chill"
    candidate_type: str = "A_PERSON"
    layers: list[Layer] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    bridge: dict[str, Any] = field(default_factory=dict)
    subject_boxes: list[list[float]] = field(default_factory=list)
    safe_zones: list[list[float]] = field(default_factory=list)

    # ----- ordering -----
    def ordered(self) -> list[Layer]:
        return sorted(self.layers, key=lambda layer: layer.z_index)

    def normalize_z(self) -> None:
        self._reindex(self.ordered())

    def _reindex(self, ordered: list[Layer]) -> None:
        for index, layer in enumerate(ordered):
            layer.z_index = index
        self.layers = list(ordered)

    def get(self, layer_id: str | None) -> Layer | None:
        return next((layer for layer in self.layers if layer.id == layer_id), None)

    def by_role(self, role: str) -> Layer | None:
        return next((layer for layer in self.ordered() if layer.role == role), None)

    def background(self) -> BackgroundLayer | None:
        return next((layer for layer in self.ordered() if isinstance(layer, BackgroundLayer)), None)

    def add(self, layer: Layer, *, above: str | None = None, below: str | None = None) -> Layer:
        ordered = self.ordered()
        anchor = self.get(above or below)
        if anchor is None:
            position = len(ordered)
        else:
            position = ordered.index(anchor) + (1 if above else 0)
        ordered.insert(position, layer)
        self._reindex(ordered)
        return layer

    def remove(self, layer_id: str) -> Layer | None:
        layer = self.get(layer_id)
        if layer is not None:
            self.layers.remove(layer)
            self.normalize_z()
        return layer

    def duplicate(self, layer_id: str, offset: float = 24.0) -> Layer | None:
        source = self.get(layer_id)
        if source is None:
            return None
        clone = layer_from_dict(copy.deepcopy(source.to_dict()))
        clone.id = new_id()
        clone.name = (source.name or source.type) + " copy"
        clone.role = ""
        clone.locked = False
        clone.x += offset; clone.y += offset
        return self.add(clone, above=source.id)

    def move(self, layer_id: str, steps: int) -> bool:
        ordered = self.ordered()
        layer = self.get(layer_id)
        if layer is None:
            return False
        index = ordered.index(layer)
        target = max(0, min(len(ordered) - 1, index + steps))
        if target == index:
            return False
        ordered.insert(target, ordered.pop(index))
        self._reindex(ordered)
        return True

    # ----- serialization -----
    def to_dict(self) -> dict[str, Any]:
        return {"document_version": DOCUMENT_VERSION, "canvas_width": self.canvas_width,
                "canvas_height": self.canvas_height, "channel": self.channel,
                "candidate_type": self.candidate_type,
                "layers": [layer.to_dict() for layer in self.ordered()],
                "metadata": copy.deepcopy(self.metadata), "bridge": copy.deepcopy(self.bridge),
                "subject_boxes": [list(box) for box in self.subject_boxes],
                "safe_zones": [list(box) for box in self.safe_zones]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThumbnailDocument":
        version = int(data.get("document_version", DOCUMENT_VERSION))
        if version > DOCUMENT_VERSION:
            raise ValueError(f"Document version {version} is newer than supported {DOCUMENT_VERSION}")
        document = cls(int(data.get("canvas_width", CANVAS_SIZE[0])), int(data.get("canvas_height", CANVAS_SIZE[1])),
                       str(data.get("channel", "Tokyo Chill")), str(data.get("candidate_type", "A_PERSON")),
                       [layer_from_dict(item) for item in data.get("layers", ())],
                       dict(data.get("metadata", {})), dict(data.get("bridge", {})),
                       [list(map(float, box)) for box in data.get("subject_boxes", ())],
                       [list(map(float, box)) for box in data.get("safe_zones", ())])
        document.normalize_z()
        return document

    def clone(self) -> "ThumbnailDocument":
        return ThumbnailDocument.from_dict(self.to_dict())


class History:
    """Snapshot undo/redo stack for one document."""

    def __init__(self, limit: int = 100):
        self.limit = limit
        self.undo_stack: list[dict[str, Any]] = []
        self.redo_stack: list[dict[str, Any]] = []

    def push(self, snapshot: dict[str, Any]) -> None:
        if self.undo_stack and self.undo_stack[-1] == snapshot:
            return
        self.undo_stack.append(snapshot)
        del self.undo_stack[:-self.limit]
        self.redo_stack.clear()

    def undo(self, current: dict[str, Any]) -> dict[str, Any] | None:
        if not self.undo_stack:
            return None
        self.redo_stack.append(current)
        return self.undo_stack.pop()

    def redo(self, current: dict[str, Any]) -> dict[str, Any] | None:
        if not self.redo_stack:
            return None
        self.undo_stack.append(current)
        return self.redo_stack.pop()

    @property
    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self.redo_stack)
