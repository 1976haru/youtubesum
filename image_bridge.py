"""Project-folder bridge for image sidecars and future image-program calls."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image


CANVAS_SIZE = (1280, 720)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
ROLE_KEYS = ("channel_label", "story_label", "episode_badge", "main_title", "subtitle")


@dataclass(frozen=True)
class ImageProject:
    folder: Path
    source_image: Path | None
    clean_canvas: Path | None
    reference_image: Path | None
    subject_boxes: tuple[dict[str, Any], ...]
    safe_zones: tuple[dict[str, Any], ...]
    palette: dict[str, Any]
    composition: dict[str, Any]
    manifest: dict[str, Any]
    subject_points: dict[str, tuple[float, float]]
    status: dict[str, bool]
    warnings: tuple[str, ...] = field(default_factory=tuple)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _image_size(path: Path | None) -> tuple[int, int]:
    if path is not None:
        try:
            with Image.open(path) as image:
                return image.size
        except (OSError, ValueError):
            pass
    return CANVAS_SIZE


def _payload_records(payload: dict[str, Any], keys: tuple[str, ...]) -> tuple[list[tuple[str, Any]], tuple[int, int]]:
    dimensions = payload.get("canvas_size", payload.get("image_size", payload.get("size", CANVAS_SIZE)))
    if isinstance(dimensions, dict):
        source_size = (int(dimensions.get("width", CANVAS_SIZE[0])), int(dimensions.get("height", CANVAS_SIZE[1])))
    elif isinstance(dimensions, (list, tuple)) and len(dimensions) == 2:
        source_size = (int(dimensions[0]), int(dimensions[1]))
    else:
        source_size = CANVAS_SIZE
    value: Any = payload
    for key in keys:
        if key in payload:
            value = payload[key]
            break
    if isinstance(value, dict):
        records = [(str(key), item) for key, item in value.items()]
    elif isinstance(value, list):
        records = [(str(item.get("role", item.get("name", item.get("type", index)))) if isinstance(item, dict) else str(index), item)
                   for index, item in enumerate(value)]
    else:
        records = []
    return records, source_size


def _rect(record: Any, source_size: tuple[int, int], target_size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    if isinstance(record, dict):
        value = record.get("bbox", record.get("box", record.get("rect")))
        if value is None and all(key in record for key in ("x", "y")):
            value = (record["x"], record["y"], record.get("width", record.get("w")),
                     record.get("height", record.get("h")))
        units = str(record.get("units", record.get("coordinate_space", ""))).casefold()
    else:
        value, units = record, ""
    if isinstance(value, dict):
        if all(key in value for key in ("x1", "y1", "x2", "y2")):
            value = (value["x1"], value["y1"], float(value["x2"]) - float(value["x1"]),
                     float(value["y2"]) - float(value["y1"]))
        else:
            value = (value.get("x"), value.get("y"), value.get("width", value.get("w")),
                     value.get("height", value.get("h")))
    if not isinstance(value, (list, tuple)) or len(value) != 4 or any(item is None for item in value):
        return None
    try:
        x, y, width, height = map(float, value)
    except (TypeError, ValueError):
        return None
    if units in ("normalized", "normalised", "relative", "ratio", "fraction") or max(abs(x), abs(y), abs(width), abs(height)) <= 1:
        x, width = x * target_size[0], width * target_size[0]
        y, height = y * target_size[1], height * target_size[1]
    else:
        x *= target_size[0] / max(1, source_size[0]); width *= target_size[0] / max(1, source_size[0])
        y *= target_size[1] / max(1, source_size[1]); height *= target_size[1] / max(1, source_size[1])
    x, y = round(x), round(y)
    width, height = round(width), round(height)
    if width <= 0 or height <= 0:
        return None
    x = max(0, min(target_size[0] - 1, x)); y = max(0, min(target_size[1] - 1, y))
    width = min(width, target_size[0] - x); height = min(height, target_size[1] - y)
    return x, y, width, height


def _parse_regions(payload: dict[str, Any], keys: tuple[str, ...], image_size: tuple[int, int],
                   target_size: tuple[int, int]) -> tuple[dict[str, Any], ...]:
    records, source_size = _payload_records(payload, keys)
    result = []
    for name, item in records:
        role = name
        if isinstance(item, dict):
            role = str(item.get("role", item.get("name", item.get("type", name))))
        bbox = _rect(item, source_size, image_size)
        if bbox:
            # Subject boxes use image coordinates; text safe zones/layout use canvas coordinates.
            if image_size != target_size and source_size == target_size:
                x, y, width, height = bbox
                bbox = (round(x * target_size[0] / image_size[0]), round(y * target_size[1] / image_size[1]),
                        round(width * target_size[0] / image_size[0]), round(height * target_size[1] / image_size[1]))
            result.append({"role": role, "bbox": bbox})
    return tuple(result)


def _first(mapping: dict[str, Any], *keys: str, default=None):
    for key in keys:
        value = mapping.get(key)
        if value is not None and value != "":
            return value
    return default


def _manifest_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for key in ("project", "metadata", "defaults", "thumbnail", "content"):
        if isinstance(raw.get(key), dict):
            values.update(raw[key])
    values.update(raw)
    return {
        "channel": _first(values, "channel", "channel_name", "channelName", default=""),
        "title": _first(values, "title", "main_title", "mainTitle", default=""),
        "subtitle": _first(values, "subtitle", "sub_title", "description", default=""),
        "episode": _first(values, "episode", "episode_number", "episodeNumber", "ep", default=""),
        "story_type": _first(values, "story_type", "storyType", "story_label", default=""),
        "preferred_typography": _first(values, "preferred_typography", "preferredTypography", "typography_style", "style", default=""),
    }


def _palette_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    colors = raw.get("colors", {}) if isinstance(raw.get("colors"), dict) else {}
    effects = raw.get("effects", {}) if isinstance(raw.get("effects"), dict) else {}
    result = {
        "fill_color": _first(raw, "fill_color", "fill", "text_color", default=_first(colors, "fill", "text", "primary", default="")),
        "stroke_color": _first(raw, "stroke_color", "stroke", "outline", default=_first(colors, "stroke", "outline", default="")),
        "highlight_color": _first(raw, "highlight_color", "highlight", "accent", default=_first(colors, "highlight", "accent", default="")),
        "glow_strength": _first(raw, "glow_strength", "glow", default=_first(effects, "glow_strength", "glow", default=None)),
        "shadow_strength": _first(raw, "shadow_strength", "shadow", default=_first(effects, "shadow_strength", "shadow", default=None)),
        "outline_width": _first(raw, "outline_width", "stroke_width", default=_first(effects, "outline_width", "stroke_width", default=None)),
    }
    return {key: value for key, value in result.items() if value not in (None, "")}


def _parse_composition(raw: dict[str, Any]) -> dict[str, Any]:
    positions = raw.get("positions", raw.get("roles", raw.get("blocks", {})))
    if not isinstance(positions, dict):
        return {}
    source_size = raw.get("canvas_size", CANVAS_SIZE)
    if isinstance(source_size, dict):
        source_size = (int(source_size.get("width", 1280)), int(source_size.get("height", 720)))
    converted = {}
    for role, value in positions.items():
        if role not in ROLE_KEYS:
            continue
        box = _rect(value, tuple(source_size), CANVAS_SIZE)
        if box:
            converted[role] = box
    return {"positions": converted}


def load_image_project(folder: str | Path, canvas_size: tuple[int, int] = CANVAS_SIZE) -> ImageProject:
    """Read known sidecars, normalize supported schemas and select a safe image fallback."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    clean_options = (root / "canvas_clean.png", root / "cleaned_canvas.png")
    reference_options = (root / "preview_reference.png", root / "reference_thumb.png")
    safe_options = (root / "safe_zones.json", root / "safe_zone.json")
    paths = {
        "clean_canvas": next((path for path in clean_options if path.is_file()), clean_options[0]),
        "reference": next((path for path in reference_options if path.is_file()), reference_options[0]),
        "subjects": root / "subject_boxes.json",
        "safe_zones": next((path for path in safe_options if path.is_file()), safe_options[0]),
        "palette": root / "palette.json",
        "composition": root / "composition.json",
        "manifest": root / "project_manifest.json",
    }
    clean = paths["clean_canvas"] if paths["clean_canvas"].is_file() else None
    reference = paths["reference"] if paths["reference"].is_file() else None
    manifest_raw = _read_json(paths["manifest"])
    palette_raw = _read_json(paths["palette"])
    subject_raw = _read_json(paths["subjects"])
    safe_raw = _read_json(paths["safe_zones"])
    composition_raw = _read_json(paths["composition"])
    source = clean
    if source is None:
        source = next((item for item in sorted(root.iterdir(), key=lambda p: p.name.casefold())
                       if item.is_file() and item.suffix.casefold() in IMAGE_EXTENSIONS
                       and item.name.casefold() not in ("preview_reference.png", "reference_thumb.png",
                                                         "canvas_clean.png", "cleaned_canvas.png")), None)
    image_size = _image_size(clean or source)
    subjects = _parse_regions(subject_raw, ("subject_boxes", "subjectBoxes", "subjects", "boxes"), image_size, image_size)
    safe = _parse_regions(safe_raw, ("safe_zones", "safeZones", "zones", "avoid"), canvas_size, canvas_size)
    points: dict[str, tuple[float, float]] = {}
    for record in subjects:
        role = record["role"].casefold().replace("-", "_").replace(" ", "_")
        key = "protagonist" if role in ("protagonist", "main", "primary", "lead", "hero", "main_character") else (
            "counterpart" if role in ("counterpart", "partner", "secondary", "other", "supporting", "other_character") else "")
        if key and key not in points:
            x, y, width, height = record["bbox"]
            points[key] = ((x + width / 2) / image_size[0], (y + height / 2) / image_size[1])
    # Many early sidecars store only an ordered list; use its first two subjects as safe defaults.
    for key, record in zip(("protagonist", "counterpart"), subjects):
        if key not in points:
            x, y, width, height = record["bbox"]
            points[key] = ((x + width / 2) / image_size[0], (y + height / 2) / image_size[1])
    valid_json = {key: bool(value) and paths[key].is_file() for key, value in (
        ("subjects", subject_raw), ("safe_zones", safe_raw), ("palette", palette_raw),
        ("composition", composition_raw), ("manifest", manifest_raw))}
    status = {"clean_canvas": clean is not None, "reference": reference is not None, **valid_json}
    warnings = tuple(f"{key} exists but is empty or invalid" for key, value in valid_json.items()
                     if paths[key].is_file() and not value)
    return ImageProject(root, source, clean, reference, subjects, safe, _palette_defaults(palette_raw),
                        _parse_composition(composition_raw), _manifest_defaults(manifest_raw), points, status, warnings)


@dataclass(frozen=True)
class LaunchResult:
    launched: bool
    message: str
    process: subprocess.Popen | None = None


def _launch(action: str, project_folder: str | Path, executable: str | Path | None = None) -> LaunchResult:
    command = executable or os.environ.get("IMAGE_PROGRAM_EXE", "")
    if not command:
        return LaunchResult(False, "No image-program executable is configured; integration is reserved for a future version.")
    program = Path(command).expanduser()
    if not program.is_file():
        return LaunchResult(False, f"Configured image program was not found: {program}")
    try:
        process = subprocess.Popen([str(program), f"--{action}", "--project", str(Path(project_folder).resolve())],
                                   cwd=str(Path(project_folder).resolve()), shell=False)
        return LaunchResult(True, f"Started image program ({action}).", process)
    except OSError as exc:
        return LaunchResult(False, f"Could not start image program: {exc}")


def launch_generate(project_folder: str | Path, executable: str | Path | None = None) -> LaunchResult:
    return _launch("generate", project_folder, executable)


def launch_edit(project_folder: str | Path, executable: str | Path | None = None) -> LaunchResult:
    return _launch("edit", project_folder, executable)
