"""Stand-in image program for Image Bridge regression tests (NOT a real AI backend).

Speaks the json-stdin protocol: reads the youtubesum-image-bridge/1 request from stdin,
writes a deterministic new canvas_clean.png and subject_boxes.json into project_dir,
and exits 0. Use via a .cmd wrapper as IMAGE_PROGRAM_EXE with IMAGE_BRIDGE_MODE=json-stdin.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
    folder = Path(request["project_dir"])
    height, width = 720, 1280
    y, x = np.mgrid[0:height, 0:width]
    image = np.dstack((60 + x * 120 // width, 40 + y * 90 // height, np.full_like(x, 150))).astype(np.uint8)
    if request.get("action") == "edit":
        image = cv2.GaussianBlur(image, (0, 0), 3)
    cv2.circle(image, (980, 300), 130, (180, 190, 230), -1, cv2.LINE_AA)
    ok, data = cv2.imencode(".png", image)
    data.tofile(str(folder / "canvas_clean.png"))
    (folder / "subject_boxes.json").write_text(json.dumps({"subjects": [
        {"role": "protagonist", "bbox": [0.66, 0.2, 0.2, 0.42]}]}), encoding="utf-8")
    print(f"stand-in {request.get('action')} ok: {request.get('prompt') or request.get('edit_instruction')}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
