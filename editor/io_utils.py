"""Unicode-path-safe atomic file helpers (Korean/Japanese/space-containing Windows paths)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import cv2
import numpy as np


def atomic_write_bytes(path: str | Path, data: bytes) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path


def atomic_write_json(path: str | Path, payload: Any) -> Path:
    return atomic_write_bytes(path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))


def read_json(path: str | Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def write_image(path: str | Path, image: np.ndarray, jpeg_quality: int = 95) -> Path:
    path = Path(path)
    suffix = path.suffix.casefold() or ".png"
    params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality] if suffix in (".jpg", ".jpeg") else []
    ok, buffer = cv2.imencode(".jpg" if suffix in (".jpg", ".jpeg") else suffix, image, params)
    if not ok:
        raise ValueError(f"이미지 인코딩 실패: {path}")
    return atomic_write_bytes(path, buffer.tobytes())


def read_image(path: str | Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray | None:
    try:
        return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), flags)
    except (OSError, ValueError):
        return None
