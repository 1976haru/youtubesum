"""Where the Image Bridge finds the image program, without shell environment variables.

Resolution order:
1. ``IMAGE_PROGRAM_EXE`` / ``IMAGE_BRIDGE_MODE`` environment variables (developer override, unchanged behaviour)
2. the program chosen in the app ("이미지 프로그램 설정…"), saved per user in
   ``%LOCALAPPDATA%\\YouTubeDynamicThumbnailStudio\\image_bridge.json`` — survives EXE rebuilds/updates
3. CoverMorph Studio auto-discovery: CoverMorph v1.0+ records its EXE path in
   ``%LOCALAPPDATA%\\CoverMorphStudio\\settings.json`` (``state.exe_path``) whenever it is opened
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

APP_DIR = "YouTubeDynamicThumbnailStudio"
VALID_MODES = ("cli", "json-stdin")


def _local_appdata() -> Path:
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def settings_path() -> Path:
    override = os.environ.get("YDTS_DATA_DIR")
    return (Path(override) if override else _local_appdata() / APP_DIR) / "image_bridge.json"


def load_saved() -> dict:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_program(path: str | Path, mode: str = "cli") -> Path:
    """Persist the chosen image program (atomic write)."""
    target = settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {**load_saved(), "image_program_exe": str(Path(path)), "bridge_mode": mode if mode in VALID_MODES else "cli"}
    fd, tmp = tempfile.mkstemp(prefix=".image_bridge_", suffix=".json", dir=target.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, target)
    return target


def discover_covermorph() -> str:
    """CoverMorph Studio's own record of where its EXE lives (written each time it is opened)."""
    data_dir = os.environ.get("COVERMORPH_DATA_DIR")
    path = (Path(data_dir) if data_dir else _local_appdata() / "CoverMorphStudio") / "settings.json"
    try:
        exe = (json.loads(path.read_text(encoding="utf-8")).get("state") or {}).get("exe_path") or ""
    except (OSError, ValueError, AttributeError):
        return ""
    return exe if exe and Path(exe).is_file() else ""


def resolve_program() -> tuple[str, str]:
    """(path, source) with source in bundled | env | saved | covermorph | none."""
    import sys
    app = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    for bundled in (app / "backend" / "CoverMorphStudio" / "CoverMorphStudio.exe",
                    app.parent / "backend" / "CoverMorphStudio" / "CoverMorphStudio.exe"):
        if bundled.is_file():
            return str(bundled), "bundled"
    env = os.environ.get("IMAGE_PROGRAM_EXE", "")
    if env:
        return env, "env"
    saved = str(load_saved().get("image_program_exe") or "")
    if saved:
        return saved, "saved"
    found = discover_covermorph()
    if found:
        return found, "covermorph"
    return "", "none"


def resolve_mode() -> str:
    env = os.environ.get("IMAGE_BRIDGE_MODE", "").strip().casefold()
    if env:
        return env
    saved = str(load_saved().get("bridge_mode") or "cli").strip().casefold()
    return saved if saved in VALID_MODES else "cli"


def summary() -> str:
    """Short Korean status for the UI."""
    path, source = resolve_program()
    if not path:
        return "이미지 프로그램 미설정 ('이미지 프로그램 설정…'에서 선택)"
    ready = Path(path).is_file()
    origin = {"bundled": "내장 엔진", "env": "환경변수", "saved": "저장된 설정", "covermorph": "자동 연결"}[source]
    return f"{'연결됨' if ready else '파일 없음'} · {Path(path).name} ({origin})"
