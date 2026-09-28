from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

APP_VERSION = "0.3"
OUTPUT_SIZE = (1280, 720)
STRATEGIES = {
    "Tokyo Chill": [("A_PERSON", "A · PERSON / 인물 중심"), ("B_EMOTION", "B · EMOTION / 감정·여백"), ("C_STORY", "C · STORY / 공간·이야기")],
    "OLD POP LOUNGE": [("A_PERSON", "A · PERSON / 인물 중심"), ("B_MEMORY", "B · MEMORY / 추억·여백"), ("C_SCENERY", "C · SCENERY / 풍경·계절")],
}


@dataclass
class Candidate:
    code: str
    label: str
    image: np.ndarray
    composition: str
    file: str | None = None


def _read(path):
    path = Path(path)
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    except Exception as exc:
        raise ValueError(f"이미지를 읽을 수 없습니다: {path}\n{exc}") from exc
    if image is None:
        raise ValueError(f"이미지를 읽을 수 없습니다: {path}")
    return image


def _write_image(path, image, jpeg_quality=95):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality])
    if not ok:
        raise ValueError(f"이미지 인코딩 실패: {path}")
    buffer.tofile(str(path))
    if not path.exists() or path.stat().st_size == 0:
        raise IOError(f"이미지 저장 검증 실패: {path}")
    return path


def _detect_faces(image):
    """Conservative local face detection. Any failure falls back safely."""
    try:
        cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(str(cascade_path))
        if cascade.empty():
            return []
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        scale = min(1.0, 1200 / max(gray.shape))
        small = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
        boxes = cascade.detectMultiScale(small, scaleFactor=1.1, minNeighbors=6, minSize=(36, 36))
        result = []
        for x, y, w, h in boxes:
            box = tuple(int(round(value / scale)) for value in (x, y, w, h))
            if box[2] * box[3] >= image.shape[0] * image.shape[1] * 0.001:
                result.append(box)
        return sorted(result, key=lambda box: box[2] * box[3], reverse=True)
    except Exception:
        return []


def _crop_resize(image, crop):
    x0, y0, x1, y1 = crop
    return cv2.resize(image[y0:y1, x0:x1], OUTPUT_SIZE, interpolation=cv2.INTER_LANCZOS4)


def _safe_crop(image, focus, padding, target_ratio=16 / 9):
    """Return a 16:9 crop containing every face plus margin, or None."""
    ih, iw = image.shape[:2]
    fx0, fy0, fx1, fy1 = focus
    fw, fh = fx1 - fx0, fy1 - fy0
    wanted_w = max(fw * (1 + padding * 2), fh * (1 + padding * 2) * target_ratio)
    wanted_h = wanted_w / target_ratio
    if wanted_h < fh * (1 + padding * 2):
        wanted_h = fh * (1 + padding * 2)
        wanted_w = wanted_h * target_ratio
    if wanted_w > iw or wanted_h > ih:
        return None
    cx, cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2
    x0 = int(max(0, min(iw - wanted_w, cx - wanted_w / 2)))
    y0 = int(max(0, min(ih - wanted_h, cy - wanted_h * 0.44)))
    crop = (x0, y0, int(x0 + wanted_w), int(y0 + wanted_h))
    margin = max(3, int(min(fw, fh) * 0.18))
    if min(fx0 - crop[0], fy0 - crop[1], crop[2] - fx1, crop[3] - fy1) < margin:
        return None
    return crop


def _fit_on_canvas(image, background="blur", inset=1.0):
    """Preserve the entire source and fill a 16:9 canvas without generated content."""
    out_w, out_h = OUTPUT_SIZE
    ih, iw = image.shape[:2]
    if background == "matte":
        canvas = np.full((out_h, out_w, 3), 22, dtype=np.uint8)
    else:
        scale = max(out_w / iw, out_h / ih)
        bg = cv2.resize(image, (max(out_w, int(iw * scale)), max(out_h, int(ih * scale))))
        bx, by = (bg.shape[1] - out_w) // 2, (bg.shape[0] - out_h) // 2
        canvas = cv2.GaussianBlur(bg[by:by + out_h, bx:bx + out_w], (0, 0), 30)
        canvas = (canvas.astype(np.float32) * 0.58).astype(np.uint8)
    scale = min(out_w / iw, out_h / ih) * inset
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    fitted = cv2.resize(image, (nw, nh), interpolation=cv2.INTER_LANCZOS4)
    x, y = (out_w - nw) // 2, (out_h - nh) // 2
    canvas[y:y + nh, x:x + nw] = fitted
    return canvas


def _grade(image, mode):
    f = image.astype(np.float32)
    if mode == "person":
        f = (f - 127.5) * 1.045 + 127.5
    elif mode == "emotion":
        f[:, :, 2] *= 1.025
        f[:, :, 0] *= 0.985
    else:
        f = (f - 127.5) * 0.97 + 127.5
    return np.clip(f, 0, 255).astype(np.uint8)


def create_candidate_images(src, channel):
    image = _read(src)
    faces = _detect_faces(image)
    specs = STRATEGIES.get(channel)
    if specs is None:
        raise ValueError(f"지원하지 않는 채널입니다: {channel}")
    person_crop = emotion_crop = None
    if faces:
        focus = (min(b[0] for b in faces), min(b[1] for b in faces),
                 max(b[0] + b[2] for b in faces), max(b[1] + b[3] for b in faces))
        person_crop = _safe_crop(image, focus, padding=0.85)
        emotion_crop = _safe_crop(image, focus, padding=1.55)

    if person_crop:
        a_image, a_note = _crop_resize(image, person_crop), f"얼굴 {len(faces)}명 보호 · 인물 근접 구도"
    else:
        a_image, a_note = _fit_on_canvas(image, "matte"), "검출 신뢰 낮음 · 전체 원본 안전 구도"
    if emotion_crop:
        b_image, b_note = _crop_resize(image, emotion_crop), f"얼굴 {len(faces)}명 보호 · 시선/여백 확장 구도"
    else:
        b_image, b_note = _fit_on_canvas(image, "blur", inset=0.90), "검출 신뢰 낮음 · 전체 원본 감정/여백 구도"
    c_image, c_note = _fit_on_canvas(image, "blur"), "전체 원본 보존 · 배경/스토리 구도"
    images = [_grade(a_image, "person"), _grade(b_image, "emotion"), _grade(c_image, "story")]
    return [Candidate(code, label, output, note) for (code, label), output, note in zip(specs, images, (a_note, b_note, c_note))]


def save_candidates(src, out_dir, candidates, selected_code=None):
    src, out = Path(src), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    saved = []
    for candidate in candidates:
        candidate.file = None
    for candidate in candidates:
        if selected_code and candidate.code != selected_code:
            continue
        path = out / f"{src.stem}_{candidate.code}.jpg"
        _write_image(path, candidate.image)
        candidate.file = str(path)
        saved.append((candidate.code, candidate.label, str(path)))
    manifest = {
        "version": APP_VERSION, "source": str(src), "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "candidates": [{"code": c.code, "strategy": c.label, "composition": c.composition, "file": c.file} for c in candidates if c.file],
        "note": "비생성형 로컬 분석만 사용하며 원본 파일은 수정하지 않는다.",
    }
    (out / f"{src.stem}_dynamic_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return saved


def generate_candidates(src, out_dir, channel):
    return save_candidates(src, out_dir, create_candidate_images(src, channel))


def record_test(db_path, episode, channel, a, b, c, winner, notes=""):
    db = Path(db_path); db.parent.mkdir(parents=True, exist_ok=True); exists = db.exists()
    with db.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        if not exists:
            writer.writerow(["timestamp", "episode", "channel", "A", "B", "C", "winner", "notes"])
        writer.writerow([time.strftime("%Y-%m-%d %H:%M:%S"), episode, channel, a, b, c, winner, notes])


def summarize(db_path, channel=None):
    path = Path(db_path)
    if not path.exists(): return "아직 기록된 테스트가 없습니다."
    with path.open(encoding="utf-8-sig") as file: rows = list(csv.DictReader(file))
    if channel: rows = [row for row in rows if row["channel"] == channel]
    if not rows: return "해당 채널 기록이 없습니다."
    wins, sums, count = {}, {"A": 0.0, "B": 0.0, "C": 0.0}, 0
    for row in rows:
        wins[row["winner"]] = wins.get(row["winner"], 0) + 1
        try:
            for key in sums: sums[key] += float(row[key] or 0)
            count += 1
        except ValueError: pass
    averages = {key: value / count if count else 0 for key, value in sums.items()}
    return f"기록 {len(rows)}회 | 승자 A/B/C: {wins.get('A', 0)}/{wins.get('B', 0)}/{wins.get('C', 0)} | 평균 입력값 A/B/C: {averages['A']:.1f}/{averages['B']:.1f}/{averages['C']:.1f}"
