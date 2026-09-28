"""Optional image-repository sidecar reader with safe local-mode fallback."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImageStorageAssets:
    source_image: Path
    cleaned_canvas: Path | None
    safe_zones: tuple
    subject_boxes: tuple
    reference_thumbnail: Path | None
    source_kind: str


def _load_json(path: Path):
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _records(payload, keys: tuple[str, ...]) -> tuple:
    value = payload
    if isinstance(payload, dict):
        for key in keys:
            if key in payload:
                value = payload[key]
                break
    if isinstance(value, dict):
        return tuple({"role": key, "bbox": item} if not isinstance(item, dict) else {"role": key, **item}
                     for key, item in value.items())
    if isinstance(value, list):
        return tuple(value)
    return ()


def load_image_storage_assets(source: str | Path) -> ImageStorageAssets:
    source = Path(source)
    folder = source if source.is_dir() else source.parent
    cleaned = folder / "cleaned_canvas.png"
    safe_path = folder / "safe_zone.json"
    subject_path = folder / "subject_boxes.json"
    reference = folder / "reference_thumb.png"
    safe_payload = _load_json(safe_path)
    subject_payload = _load_json(subject_path)
    chosen = cleaned if cleaned.is_file() and cleaned.resolve() != source.resolve() else source
    return ImageStorageAssets(
        chosen, cleaned if cleaned.is_file() else None,
        _records(safe_payload, ("safe_zones", "safeZones", "avoid", "zones")),
        _records(subject_payload, ("subject_boxes", "subjectBoxes", "subjects", "boxes")),
        reference if reference.is_file() else None,
        "image-storage" if any(path.is_file() for path in (cleaned, safe_path, subject_path, reference)) else "local-fallback",
    )
