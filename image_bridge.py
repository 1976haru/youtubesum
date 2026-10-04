"""Project-folder sidecar bridge and subprocess client for an image application."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
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
    try:
        if isinstance(dimensions, dict):
            source_size = (int(dimensions.get("width", CANVAS_SIZE[0])), int(dimensions.get("height", CANVAS_SIZE[1])))
        elif isinstance(dimensions, (list, tuple)) and len(dimensions) == 2:
            source_size = (int(dimensions[0]), int(dimensions[1]))
        else:
            source_size = CANVAS_SIZE
        if min(source_size) <= 0:
            source_size = CANVAS_SIZE
    except (TypeError, ValueError):
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
        try:
            if all(key in value for key in ("x1", "y1", "x2", "y2")):
                value = (value["x1"], value["y1"], float(value["x2"]) - float(value["x1"]),
                         float(value["y2"]) - float(value["y1"]))
            else:
                value = (value.get("x"), value.get("y"), value.get("width", value.get("w")),
                         value.get("height", value.get("h")))
        except (TypeError, ValueError):
            return None
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
    try:
        if isinstance(source_size, dict):
            source_size = (int(source_size.get("width", 1280)), int(source_size.get("height", 720)))
        else:
            source_size = tuple(map(int, source_size))
        if len(source_size) != 2 or min(source_size) <= 0:
            source_size = CANVAS_SIZE
    except (TypeError, ValueError):
        source_size = CANVAS_SIZE
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
    parsed_palette = _palette_defaults(palette_raw)
    parsed_composition = _parse_composition(composition_raw)
    parsed_manifest = _manifest_defaults(manifest_raw)
    valid_json = {
        "subjects": bool(subjects) and paths["subjects"].is_file(),
        "safe_zones": bool(safe) and paths["safe_zones"].is_file(),
        "palette": bool(parsed_palette) and paths["palette"].is_file(),
        "composition": bool(parsed_composition.get("positions")) and paths["composition"].is_file(),
        "manifest": any(parsed_manifest.values()) and paths["manifest"].is_file(),
    }
    status = {"clean_canvas": clean is not None, "reference": reference is not None, **valid_json}
    warnings = tuple(f"{key} exists but is empty or invalid" for key, value in valid_json.items()
                     if paths[key].is_file() and not value)
    return ImageProject(root, source, clean, reference, subjects, safe, parsed_palette,
                        parsed_composition, parsed_manifest, points, status, warnings)


@dataclass(frozen=True)
class LaunchResult:
    launched: bool
    message: str
    action: str = ""
    project_dir: Path | None = None
    return_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    warnings: tuple[str, ...] = ()
    project: ImageProject | None = None
    timed_out: bool = False


OUTPUT_FILES = ("canvas_clean.png", "subject_boxes.json", "safe_zones.json", "palette.json",
                "composition.json", "project_manifest.json")
SIDECAR_FILES = OUTPUT_FILES[1:]
DEFAULT_TIMEOUT_SECONDS = 600
MAX_LOG_CHARS = 12000


def refresh_project(project_dir: str | Path) -> ImageProject:
    """Re-read bridge outputs after generation/edit, including all refreshed sidecars."""
    return load_image_project(project_dir)


def _resolve_project_dir(project_dir: str | Path | None) -> Path:
    root = Path(os.environ.get("IMAGE_PROJECT_ROOT", "") or Path.cwd()).expanduser()
    if project_dir in (None, ""):
        candidate = root
    else:
        candidate = Path(project_dir).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise NotADirectoryError(f"Image project directory does not exist: {candidate}")
    return candidate


def _request(action: str, project_dir: Path, prompt: str, edit_request: str,
             options: dict[str, Any] | None) -> dict[str, Any]:
    opts = dict(options or {})
    opts.pop("timeout", None)
    project = load_image_project(project_dir)
    manifest = project.manifest
    request = {
        "protocol": "youtubesum-image-bridge/1",
        "action": action,
        "project_dir": str(project_dir),
        "channel": opts.pop("channel", manifest.get("channel", "")),
        "story_type": opts.pop("story_type", manifest.get("story_type", "")),
        "title": opts.pop("title", manifest.get("title", "")),
        "subtitle": opts.pop("subtitle", manifest.get("subtitle", "")),
        "prompt": prompt or opts.pop("prompt", ""),
        "edit_instruction": edit_request or opts.pop("edit_instruction", ""),
        "options": opts,
        "outputs": list(OUTPUT_FILES),
    }
    return request


def _command(program: Path, mode: str, request: dict[str, Any]) -> tuple[list[str], str | None]:
    if mode in ("json-stdin", "stdin-json"):
        return [str(program), "--image-bridge"], json.dumps(request, ensure_ascii=False)
    if mode not in ("cli", "argv"):
        raise ValueError(f"Unsupported IMAGE_BRIDGE_MODE: {mode!r}; use cli or json-stdin")
    args = [str(program), "--action", request["action"], "--project-dir", request["project_dir"]]
    for key, flag in (("channel", "--channel"), ("story_type", "--story-type"),
                      ("title", "--title"), ("subtitle", "--subtitle")):
        value = request.get(key)
        if value:
            args.extend((flag, str(value)))
    for key, flag in (("prompt", "--prompt"), ("edit_instruction", "--edit-instruction")):
        if request.get(key):
            args.extend((flag, str(request[key])))
    args.extend(("--options-json", json.dumps(request["options"], ensure_ascii=False)))
    return args, None


def _file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _restore_backup(project_dir: Path, backup_dir: Path, prior: set[str], *, remove_new: bool) -> None:
    for name in OUTPUT_FILES:
        target, backup = project_dir / name, backup_dir / name
        if name in prior and backup.is_file():
            restore = project_dir / f".{name}.ydts-restore"
            shutil.copy2(backup, restore)
            os.replace(restore, target)
        elif remove_new and name not in prior and target.exists():
            target.unlink()


def _validate_result(project_dir: Path, backup_dir: Path, prior: set[str], old_digest: str | None):
    warnings: list[str] = []
    canvas = project_dir / "canvas_clean.png"
    valid = False
    if canvas.is_file():
        try:
            with Image.open(canvas) as image:
                image.verify()
            valid = True
        except (OSError, ValueError):
            valid = False
    if not valid or (old_digest is not None and _file_digest(canvas) == old_digest):
        _restore_backup(project_dir, backup_dir, prior, remove_new=True)
        reason = "canvas_clean.png is missing/invalid" if not valid else "canvas_clean.png was not updated"
        return False, (reason,), None

    for name in SIDECAR_FILES:
        target = project_dir / name
        sidecar_valid = False
        if target.is_file():
            sidecar_valid = bool(_read_json(target))
        if not sidecar_valid:
            if name in prior and (backup_dir / name).is_file():
                shutil.copy2(backup_dir / name, target)
                warnings.append(f"{name} missing/invalid; kept the previous sidecar")
            else:
                warnings.append(f"{name} missing/invalid; local/default fallback will be used")
        elif name in prior and _file_digest(target) == _file_digest(backup_dir / name):
            warnings.append(f"{name} was unchanged; its existing metadata was retained")
    project = refresh_project(project_dir)
    status_keys = {"subject_boxes.json": "subjects", "safe_zones.json": "safe_zones",
                   "palette.json": "palette", "composition.json": "composition",
                   "project_manifest.json": "manifest"}
    restored_any = False
    for name, key in status_keys.items():
        if project.status.get(key):
            continue
        if name in prior and (backup_dir / name).is_file():
            shutil.copy2(backup_dir / name, project_dir / name)
            warnings.append(f"{name} was not understood; kept the previous sidecar")
            restored_any = True
        else:
            warnings.append(f"{name} was not understood; defaults will be used")
    if restored_any:
        project = refresh_project(project_dir)
    return True, tuple(dict.fromkeys(warnings)), project


def _launch(action: str, project_dir: str | Path | None, *, prompt: str = "", edit_request: str = "",
            options: dict[str, Any] | None = None, executable: str | Path | None = None,
            timeout: float | None = None) -> LaunchResult:
    try:
        root = _resolve_project_dir(project_dir)
    except (OSError, ValueError) as exc:
        return LaunchResult(False, str(exc), action=action)
    from image_program import resolve_mode, resolve_program
    configured = executable or resolve_program()[0]
    if not configured:
        return LaunchResult(False, "Image program is not configured. Choose it in 설정 → AI 엔진 → '연결 설정…' "
                            "(or set IMAGE_PROGRAM_EXE).", action=action, project_dir=root)
    program = Path(configured).expanduser()
    if not program.is_absolute():
        program = (Path.cwd() / program).resolve()
    if not program.is_file():
        return LaunchResult(False, f"Image program executable was not found: {program}", action=action, project_dir=root)
    try:
        request = _request(action, root, prompt, edit_request, options)
        mode = resolve_mode()
        args, input_text = _command(program, mode, request)
    except (OSError, TypeError, ValueError) as exc:
        return LaunchResult(False, str(exc), action=action, project_dir=root)

    timeout_value = timeout if timeout is not None else (options or {}).get("timeout", os.environ.get("IMAGE_BRIDGE_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    try:
        timeout_value = max(1.0, float(timeout_value))
    except (TypeError, ValueError):
        timeout_value = float(DEFAULT_TIMEOUT_SECONDS)

    try:
        with tempfile.TemporaryDirectory(prefix=".ydts_image_bridge_", dir=root) as backup_name:
            backup_dir = Path(backup_name)
            prior = set()
            for name in OUTPUT_FILES:
                source = root / name
                if source.is_file():
                    shutil.copy2(source, backup_dir / name)
                    prior.add(name)
            old_digest = _file_digest(root / "canvas_clean.png")
            try:
                completed = subprocess.run(args, cwd=str(root), input=input_text, text=True,
                    encoding="utf-8", errors="replace", capture_output=True, timeout=timeout_value,
                    check=False, shell=False)
            except subprocess.TimeoutExpired as exc:
                _restore_backup(root, backup_dir, prior, remove_new=True)
                stdout = (exc.stdout or "")
                stderr = (exc.stderr or "")
                return LaunchResult(False, f"Image program timed out after {timeout_value:g}s; project outputs were restored.",
                    action, root, None, str(stdout)[-MAX_LOG_CHARS:], str(stderr)[-MAX_LOG_CHARS:], timed_out=True)
            except OSError as exc:
                _restore_backup(root, backup_dir, prior, remove_new=True)
                return LaunchResult(False, f"Could not start image program: {exc}; project outputs were restored.", action, root)
            stdout = completed.stdout[-MAX_LOG_CHARS:]
            stderr = completed.stderr[-MAX_LOG_CHARS:]
            if completed.returncode != 0:
                _restore_backup(root, backup_dir, prior, remove_new=True)
                detail = stderr.strip() or stdout.strip() or "no diagnostic output"
                return LaunchResult(False, f"Image program exited with code {completed.returncode}: {detail[-700:]}; project outputs were restored.",
                    action, root, completed.returncode, stdout, stderr)
            ok, warnings, project = _validate_result(root, backup_dir, prior, old_digest)
            if not ok:
                return LaunchResult(False, "Image program reported success but did not return a fresh valid canvas_clean.png; project outputs were restored.",
                    action, root, completed.returncode, stdout, stderr, warnings)
            summary = f"Image program {action} completed."
            if warnings:
                summary += " Some sidecars were missing; previous values or local defaults were retained."
            return LaunchResult(True, summary, action, root, completed.returncode, stdout, stderr, warnings, project)
    except OSError as exc:
        return LaunchResult(False, f"Image Bridge could not prepare safe output recovery: {exc}", action=action, project_dir=root)


def launch_generate(project_dir: str | Path | None, prompt: str = "", options: dict[str, Any] | None = None,
                    *, executable: str | Path | None = None, timeout: float | None = None) -> LaunchResult:
    return _launch("generate", project_dir, prompt=prompt, options=options, executable=executable, timeout=timeout)


def launch_edit(project_dir: str | Path | None, edit_request: str = "", options: dict[str, Any] | None = None,
                *, executable: str | Path | None = None, timeout: float | None = None) -> LaunchResult:
    return _launch("edit", project_dir, edit_request=edit_request, options=options, executable=executable, timeout=timeout)
