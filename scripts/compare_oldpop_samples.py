"""Save before/A/B/C 340px comparisons for three real Old Pop inputs."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from thumbnail_engine import TEMPLATE_MODE, _read, create_candidate_images


SAMPLES = (
    ("그 시절, 우리 노래", "EP.008", "AUTUMN MEMORY", "Warm Gold"),
    ("첫눈처럼 다시 만난 날", "EP.021", "FIRST SNOW", "First Snow"),
    ("카페에 흐르던 추억의 멜로디", "EP.034", "CAFE MEMORY", "Senior Classic"),
)


def main() -> None:
    sources = [Path(arg) for arg in sys.argv[1:]]
    if len(sources) != 3 or not all(path.is_file() for path in sources):
        raise SystemExit("Usage: compare_oldpop_samples.py sample1.png sample2.png sample3.png")
    output_dir = ROOT / "build" / "v041_oldpop_before_after"
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, (source, (title, episode, story, preset)) in enumerate(zip(sources, SAMPLES), start=1):
        candidates = create_candidate_images(source, "OLD POP LOUNGE", TEMPLATE_MODE,
            focus_mode="자동", story_type=story, episode=episode, title=title,
            subtitle="OLD POP LOUNGE · CLASSIC MEMORY", typography_style=preset,
            auto_two_line=True, emphasize_keyword=True)
        original = cv2.resize(_read(source), (1280, 720), interpolation=cv2.INTER_AREA)
        images = [original] + [candidate.image for candidate in candidates]
        labels = ["BEFORE - SOURCE", "AFTER - A PERSON", "AFTER - B EMOTION", "AFTER - C STORY"]
        sheet = np.full((216, 1360, 3), (24, 27, 34), dtype=np.uint8)
        for slot, (image, label) in enumerate(zip(images, labels)):
            x = slot * 340
            sheet[25:216, x:x + 340] = cv2.resize(image, (340, 191), interpolation=cv2.INTER_AREA)
            cv2.putText(sheet, label, (x + 9, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.44,
                        (236, 240, 246), 1, cv2.LINE_AA)
        output = output_dir / f"sample_{index:02d}_before_after.png"
        ok, encoded = cv2.imencode(".png", sheet)
        if not ok:
            raise RuntimeError(f"Could not encode {output}")
        encoded.tofile(str(output))
        print(output)


if __name__ == "__main__":
    main()
