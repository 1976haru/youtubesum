"""Save before/A/B/C 340px comparisons for three real Tokyo Chill inputs."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from thumbnail_engine import TEMPLATE_MODE, _read, create_candidate_images


SAMPLES = (
    ("\u3075\u305f\u308a\u304c\u59cb\u307e\u308b\u3002", "EP.001", "\u4e8c\u4eba\u306e\u7269\u8a9e", (0.55, 0.51), (0.67, 0.36)),
    ("\u5098\u3072\u3068\u3064\u3001\u8ddd\u96e2\u306f\u30bc\u30ed\u3002", "EP.003", "\u4e8c\u4eba\u306e\u7269\u8a9e", (0.62, 0.29), (0.76, 0.39)),
    ("\u79cb\u306e\u99c5\u3067\u3001\u307e\u305f\u4f1a\u3046\u3002", "EP.012", "\u4e8c\u4eba\u306e\u7269\u8a9e", (0.34, 0.31), (0.72, 0.37)),
)


def before_after_sheet(source: Path, title: str, episode: str, story: str,
                       protagonist: tuple[float, float], counterpart: tuple[float, float],
                       output: Path) -> Path:
    candidates = create_candidate_images(source, "Tokyo Chill", TEMPLATE_MODE,
        focus_mode="수동 지정", protagonist=protagonist, counterpart=counterpart,
        story_type=story, episode=episode, title=title,
        subtitle="TOKYO CHILL LOVE STORY", typography_style="Japanese Impact",
        auto_two_line=True, emphasize_keyword=True)
    original = _read(source)
    original = cv2.resize(original, (1280, 720), interpolation=cv2.INTER_AREA)
    images = [original] + [candidate.image for candidate in candidates]
    labels = ["BEFORE - SOURCE", "AFTER - A PERSON", "AFTER - B EMOTION", "AFTER - C STORY"]
    sheet = np.full((216, 340 * 4, 3), (24, 27, 34), dtype=np.uint8)
    for index, (image, label) in enumerate(zip(images, labels)):
        thumb = cv2.resize(image, (340, 191), interpolation=cv2.INTER_AREA)
        x = index * 340
        sheet[25:216, x:x + 340] = thumb
        cv2.putText(sheet, label, (x + 9, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.44,
                    (236, 240, 246), 1, cv2.LINE_AA)
    output.parent.mkdir(parents=True, exist_ok=True)
    ok, encoded = cv2.imencode(".png", sheet)
    if not ok:
        raise RuntimeError("Could not encode before/after comparison")
    encoded.tofile(str(output))
    return output


def main() -> None:
    sources = [Path(arg) for arg in sys.argv[1:]]
    if len(sources) != 3 or not all(path.is_file() for path in sources):
        raise SystemExit("Usage: compare_tokyo_samples.py sample1.png sample2.png sample3.png")
    output_dir = ROOT / "build" / "v04_tokyo_before_after"
    for index, (source, sample) in enumerate(zip(sources, SAMPLES), start=1):
        path = before_after_sheet(source, *sample, output_dir / f"sample_{index:02d}_before_after.png")
        print(path)


if __name__ == "__main__":
    main()
