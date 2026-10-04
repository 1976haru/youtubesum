"""Render four synthetic 340px A/B/C typography contact sheets for visual QA."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from PIL import Image, ImageDraw

from layout_engine import render_candidate_text


OUTPUT = ROOT / "build" / "typography_previews"


def fixture(channel: str) -> np.ndarray:
    height, width = 720, 1280
    y, x = np.indices((height, width))
    if channel == "Tokyo Chill":
        red = 12 + (x * 13 // width)
        green = 19 + (y * 21 // height)
        blue = 45 + (x * 24 // width)
    else:
        red = 60 + (y * 32 // height)
        green = 48 + (x * 19 // width)
        blue = 38 + (x * 10 // width)
    image = np.dstack((red, green, blue)).clip(0, 255).astype(np.uint8)
    canvas = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(canvas)
    # A simple silhouette and environmental light establish focal and scenery regions.
    cx = 900 if channel == "Tokyo Chill" else 875
    draw.ellipse((cx - 92, 165, cx + 92, 350), fill=(24, 28, 37))
    draw.rounded_rectangle((cx - 145, 320, cx + 145, 720), radius=105, fill=(22, 27, 36))
    if channel == "Tokyo Chill":
        for bx, by, color in ((180, 130, (33, 127, 183)), (320, 235, (198, 53, 101)),
                              (1080, 105, (38, 141, 167)), (1090, 390, (206, 70, 119))):
            draw.rounded_rectangle((bx, by, bx + 30, by + 150), radius=12, fill=color)
    else:
        draw.ellipse((1000, 90, 1160, 250), fill=(224, 175, 93))
        for bx, by in ((180, 390), (320, 300), (1060, 330)):
            draw.ellipse((bx, by, bx + 90, by + 90), fill=(139, 78, 39))
    return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    samples = (
        ("Tokyo Chill", "japanese_impact", "あの日の約束과 서울의 밤", "彼女と見た夜景", "TOKYO / LOVE", "EP.014"),
        ("Tokyo Chill", "romantic_neon", "비 오는 밤, 君を思う", "둘만의 작은 이야기", "TOKYO / MEMORY", "EP.021"),
        ("OLD POP LOUNGE", "senior_classic", "첫눈에 담긴 그 시절", "그때 우리 이야기", "OLD POP / CLASSIC", "EP.008"),
        ("OLD POP LOUNGE", "christmas_glow", "크리스마스의 추억", "あの冬のカフェ", "OLD POP / WINTER", "EP.012"),
    )
    for channel, style, title, subtitle, story, episode in samples:
        base = fixture(channel)
        panels = []
        for code in ("A_PERSON", "B_EMOTION", "C_STORY"):
            rendered, _ = render_candidate_text(base.copy(), channel, code, story, episode, title,
                subtitle, style, True, True, "", "Auto")
            small = cv2.resize(rendered, (340, 191), interpolation=cv2.INTER_AREA)
            preview = Image.fromarray(cv2.cvtColor(small, cv2.COLOR_BGR2RGB))
            panel = Image.new("RGB", (340, 216), (18, 18, 18))
            ImageDraw.Draw(panel).text((12, 5), code.replace("_", " "), fill=(238, 238, 238))
            panel.paste(preview, (0, 25))
            panels.append(panel)
        sheet = Image.new("RGB", (340 * 3, 216), (18, 18, 18))
        for index, panel in enumerate(panels):
            sheet.paste(panel, (index * 340, 0))
        filename = f"{channel.lower().replace(' ', '_')}_{style}.png"
        sheet.save(OUTPUT / filename)
        print(OUTPUT / filename)


if __name__ == "__main__":
    main()
