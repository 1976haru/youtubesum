"""One settings file for the whole app: %LOCALAPPDATA%\\YouTubeDynamicThumbnailStudio\\studio_settings.json.

Survives EXE rebuilds/updates (never inside the EXE folder). Atomic writes; a damaged file is kept aside and
defaults are used. The image-program path is shared with ``image_program`` (the Image Bridge uses it too).
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

APP_DIR = "YouTubeDynamicThumbnailStudio"

QUALITY = {"빠른 미리보기": "preview", "일반": "balanced", "최고 품질": "best"}
MEMORY = {"작업 중 PC 우선": "interactive_low_memory", "균형": "balanced_idle", "자리 비움": "night_best"}
PRODUCT_MODES = {"자연광 보정 합성 (추천)": "natural", "원본 그대로 합성": "strict", "AI 재구성 · 변형 가능": "ai"}
NATURAL_STRENGTH = {"약하게": "weak", "기본": "default", "강하게": "strong"}

DEFAULTS: dict[str, Any] = {
    "schema_version": 1,
    "models_dir": "",
    "output_dir": "",
    "quality": "balanced",
    "memory": "interactive_low_memory",
    "candidates": 2,
    "youtube_preset": "tc_solo_woman",
    "shopify_preset": "shopify_hero",
    "product_mode": "natural",
    "natural_strength": "default",
    "auto_start": True,
    "recheck_seconds": 20,
    "timeout_seconds": 1200,
    "setup_done": False,
    "last_project_dir": "",
}


def data_dir() -> Path:
    override = os.environ.get("YDTS_DATA_DIR")
    base = Path(override) if override else Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / APP_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base


def settings_file() -> Path:
    return data_dir() / "studio_settings.json"


def documents_dir() -> Path:
    if os.name == "nt":
        buffer = ctypes.create_unicode_buffer(260)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer) == 0 and buffer.value:
            return Path(buffer.value)
    return Path.home() / "Documents"


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.stem}_", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def quarantine(path: Path) -> Path:
    target = path.with_name(f"{path.stem}.corrupt-{time.strftime('%Y%m%d_%H%M%S')}{path.suffix}")
    try:
        shutil.move(str(path), str(target))
    except OSError:
        return path
    return target


def load() -> dict[str, Any]:
    path = settings_file()
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not an object")
        except (OSError, ValueError):
            quarantine(path)
            data = {}
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def save(values: dict[str, Any]) -> None:
    atomic_write_json(settings_file(), {**DEFAULTS, **{k: v for k, v in values.items() if k in DEFAULTS}})


def output_dir(values: dict[str, Any] | None = None) -> Path:
    values = values or load()
    return Path(values["output_dir"]) if values.get("output_dir") else documents_dir() / "YouTubeDynamicThumbnailStudio"


def label_for(mapping: dict[str, str], value: str) -> str:
    return next((label for label, key in mapping.items() if key == value), next(iter(mapping)))
