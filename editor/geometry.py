"""Pure geometry for direct manipulation: view transforms, hit tests, handles, resize, snapping."""
from __future__ import annotations

import math
from dataclasses import dataclass

HANDLE_SIGNS = {"nw": (-1, -1), "n": (0, -1), "ne": (1, -1), "e": (1, 0),
                "se": (1, 1), "s": (0, 1), "sw": (-1, 1), "w": (-1, 0)}
CORNER_HANDLES = ("nw", "ne", "se", "sw")
ZOOM_LEVELS = (0.25, 0.5, 0.75, 1.0)
SAFE_MARGIN_X = 48
SAFE_MARGIN_Y = 36
# YouTube draws the duration stamp over the lower-right corner of every thumbnail.
TIMESTAMP_BOX = (1280 - 176, 720 - 72, 176, 72)
MIN_SIZE = 8.0


@dataclass(frozen=True)
class ViewTransform:
    """Maps document pixels to canvas-widget pixels: view = origin + doc * zoom."""
    zoom: float = 1.0
    origin_x: float = 0.0
    origin_y: float = 0.0

    def to_view(self, x: float, y: float) -> tuple[float, float]:
        return self.origin_x + x * self.zoom, self.origin_y + y * self.zoom

    def to_doc(self, vx: float, vy: float) -> tuple[float, float]:
        return (vx - self.origin_x) / self.zoom, (vy - self.origin_y) / self.zoom

    def delta_to_doc(self, dx: float, dy: float) -> tuple[float, float]:
        return dx / self.zoom, dy / self.zoom


def fit_zoom(view_width: int, view_height: int, doc_width: int = 1280, doc_height: int = 720,
             margin: int = 24) -> float:
    return max(0.05, min((view_width - 2 * margin) / doc_width, (view_height - 2 * margin) / doc_height))


def centered_view(zoom: float, view_width: int, view_height: int, doc_width: int = 1280,
                  doc_height: int = 720, margin: int = 24) -> ViewTransform:
    """Centre the document when it is smaller than the viewport, else leave a margin for panning."""
    scaled_w, scaled_h = doc_width * zoom, doc_height * zoom
    ox = (view_width - scaled_w) / 2 if scaled_w + 2 * margin <= view_width else margin
    oy = (view_height - scaled_h) / 2 if scaled_h + 2 * margin <= view_height else margin
    return ViewTransform(zoom, ox, oy)


def _rotate(x: float, y: float, degrees: float) -> tuple[float, float]:
    angle = math.radians(degrees)
    cos, sin = math.cos(angle), math.sin(angle)
    return x * cos - y * sin, x * sin + y * cos


def corners(layer) -> list[tuple[float, float]]:
    cx, cy = layer.x + layer.width / 2, layer.y + layer.height / 2
    hw, hh = layer.width / 2, layer.height / 2
    result = []
    for lx, ly in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        rx, ry = _rotate(lx, ly, layer.rotation)
        result.append((cx + rx, cy + ry))
    return result


def aabb(layer) -> tuple[float, float, float, float]:
    points = corners(layer)
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def to_local(layer, x: float, y: float) -> tuple[float, float]:
    """Document point -> layer-local coordinates (origin at the layer centre, unrotated)."""
    cx, cy = layer.x + layer.width / 2, layer.y + layer.height / 2
    return _rotate(x - cx, y - cy, -layer.rotation)


def contains(layer, x: float, y: float, tolerance: float = 0.0) -> bool:
    lx, ly = to_local(layer, x, y)
    return abs(lx) <= layer.width / 2 + tolerance and abs(ly) <= layer.height / 2 + tolerance


def hit_test(document, x: float, y: float, tolerance: float = 0.0, *, include_locked: bool = False):
    """Topmost visible (unlocked) layer under a document point; locked/background layers are skipped."""
    for layer in reversed(document.ordered()):
        if not layer.visible or (layer.locked and not include_locked):
            continue
        if contains(layer, x, y, tolerance):
            return layer
    return None


def handle_points(layer, view: ViewTransform, rotate_offset: float = 28.0) -> dict[str, tuple[float, float]]:
    """Handle positions in view coordinates; 'rot' sits above the top edge."""
    cx, cy = layer.x + layer.width / 2, layer.y + layer.height / 2
    points = {}
    for name, (sx, sy) in HANDLE_SIGNS.items():
        rx, ry = _rotate(sx * layer.width / 2, sy * layer.height / 2, layer.rotation)
        points[name] = view.to_view(cx + rx, cy + ry)
    rx, ry = _rotate(0, -layer.height / 2 - rotate_offset / view.zoom, layer.rotation)
    points["rot"] = view.to_view(cx + rx, cy + ry)
    return points


def handle_at(layer, view: ViewTransform, vx: float, vy: float, radius: float = 7.0,
              allowed: tuple[str, ...] | None = None) -> str | None:
    best = None
    for name, (hx, hy) in handle_points(layer, view).items():
        if allowed is not None and name not in allowed:
            continue
        distance = math.hypot(vx - hx, vy - hy)
        if distance <= radius + (2 if name == "rot" else 0) and (best is None or distance < best[0]):
            best = (distance, name)
    return best[1] if best else None


@dataclass(frozen=True)
class Geometry:
    x: float
    y: float
    width: float
    height: float
    rotation: float

    @classmethod
    def of(cls, layer) -> "Geometry":
        return cls(layer.x, layer.y, layer.width, layer.height, layer.rotation)


def resize(start: Geometry, handle: str, dx: float, dy: float, *, proportional: bool | None = None,
           from_center: bool = False) -> tuple[Geometry, float]:
    """Resize from a handle drag (document delta). Returns new geometry and the uniform scale factor.

    The opposite edge/corner stays fixed in the rotated frame. Corner handles resize
    proportionally by default (``proportional``); the factor lets callers scale font sizes.
    """
    sx, sy = HANDLE_SIGNS[handle]
    lx, ly = _rotate(dx, dy, -start.rotation)
    w, h = start.width, start.height
    if proportional is None:
        proportional = handle in CORNER_HANDLES
    span = 2 if from_center else 1
    if proportional and sx and sy:
        factor = 1 + (sx * lx * w + sy * ly * h) * span / max(1e-6, w * w + h * h)
        factor = max(MIN_SIZE / max(1e-6, min(w, h)), factor)
        new_w, new_h = w * factor, h * factor
    else:
        new_w = max(MIN_SIZE, w + sx * lx * span) if sx else w
        new_h = max(MIN_SIZE, h + sy * ly * span) if sy else h
        factor = 1.0
    if from_center:
        shift_x = shift_y = 0.0
    else:
        shift_x, shift_y = sx * (new_w - w) / 2, sy * (new_h - h) / 2
    rx, ry = _rotate(shift_x, shift_y, start.rotation)
    cx, cy = start.x + w / 2 + rx, start.y + h / 2 + ry
    return Geometry(cx - new_w / 2, cy - new_h / 2, new_w, new_h, start.rotation), factor


def rotation_from_pointer(start: Geometry, start_point: tuple[float, float], point: tuple[float, float],
                          snap: bool = False) -> float:
    cx, cy = start.x + start.width / 2, start.y + start.height / 2
    begin = math.degrees(math.atan2(start_point[1] - cy, start_point[0] - cx))
    now = math.degrees(math.atan2(point[1] - cy, point[0] - cx))
    angle = start.rotation + (now - begin)
    angle = (angle + 180) % 360 - 180
    if snap:
        angle = round(angle / 15) * 15
    elif min(abs(angle - target) for target in (-180, -90, 0, 90, 180)) < 2:
        angle = min((-180, -90, 0, 90, 180), key=lambda target: abs(angle - target))
    return 0.0 if abs(angle) < 1e-9 else angle


def snap_targets(document, moving_ids=(), canvas=(1280, 720)) -> tuple[list[float], list[float]]:
    """Canvas centre/edges, safe margins and other layers' edges/centres (subject boxes excluded)."""
    width, height = canvas
    xs = [0.0, width / 2, float(width), float(SAFE_MARGIN_X), float(width - SAFE_MARGIN_X)]
    ys = [0.0, height / 2, float(height), float(SAFE_MARGIN_Y), float(height - SAFE_MARGIN_Y)]
    for layer in document.ordered():
        if layer.id in moving_ids or not layer.visible or layer.type == "background":
            continue
        x, y, w, h = aabb(layer)
        xs += [x, x + w / 2, x + w]
        ys += [y, y + h / 2, y + h]
    return xs, ys


def snap_move(box: tuple[float, float, float, float], targets: tuple[list[float], list[float]],
              threshold: float) -> tuple[float, float, list[tuple[str, float]]]:
    """Return (dx, dy, guides) that snap the box's edges/centre to the nearest targets."""
    x, y, w, h = box
    guides: list[tuple[str, float]] = []
    offsets = []
    for axis, edges, candidates in (("x", (x, x + w / 2, x + w), targets[0]),
                                    ("y", (y, y + h / 2, y + h), targets[1])):
        best = None
        for edge in edges:
            for target in candidates:
                delta = target - edge
                if abs(delta) <= threshold and (best is None or abs(delta) < abs(best[0])):
                    best = (delta, target)
        offsets.append(best[0] if best else 0.0)
        if best:
            guides.append((axis, best[1]))
    return offsets[0], offsets[1], guides


def overlap_ratio(box_a, box_b) -> float:
    ax, ay, aw, ah = box_a; bx, by, bw, bh = box_b
    area = max(0.0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0.0, min(ay + ah, by + bh) - max(ay, by))
    return area / max(1.0, aw * ah)
