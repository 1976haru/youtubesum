"""Unicode line breaking with Japanese kinsoku and balanced 1-3 line choices."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import unicodedata

from uniseg.linebreak import line_break_boundaries


NO_LINE_START = set("、。，．・：；？！゛゜´’”）〕］｝〉》」』】〙〗〟’\"'!?)]}%％‰℃〆°ー〜～…‥")
NO_LINE_END = set("（〔［｛〈《「『【〘〖〝‘“([{\"$")
PUNCTUATION = set("、。，．・：；？！!?.,:;…‥")
PARTICLES = ("から", "まで", "より", "には", "では", "とは", "けれど", "けど", "ので", "のに", "そして", "だけ", "さえ")


@dataclass(frozen=True)
class LineBreakCandidate:
    lines: tuple[str, ...]
    score: float
    width_ratio: float


def legal_breaks(text: str) -> tuple[int, ...]:
    """Return Unicode line-break opportunities after applying Japanese kinsoku."""
    normalized = " ".join((text or "").split())
    if not normalized:
        return ()
    points = set(line_break_boundaries(normalized))
    points.add(len(normalized))
    legal = []
    for point in sorted(points):
        if point <= 0 or point >= len(normalized):
            continue
        before, after = normalized[point - 1], normalized[point]
        if before in NO_LINE_END or after in NO_LINE_START:
            continue
        legal.append(point)
    legal.append(len(normalized))
    return tuple(dict.fromkeys(legal))


def _break_penalty(text: str, point: int) -> float:
    left, right = text[:point], text[point:]
    previous = left[-1]
    following = right[0] if right else ""
    penalty = 0.0
    if previous in PUNCTUATION:
        penalty -= 1.4
    elif previous.isspace():
        penalty -= 0.6
    elif any(left.endswith(particle) for particle in PARTICLES):
        penalty -= 0.9
    if previous in "のがをにでともはへやねよからまで":
        penalty -= 1.0
    if following in "のがをにでともはへやねよ" and previous not in PUNCTUATION:
        penalty += 1.5
    previous_name = unicodedata.name(previous, "")
    following_name = unicodedata.name(following, "")
    if previous not in PUNCTUATION and previous_name and following_name:
        if ("HIRAGANA" in previous_name and "HIRAGANA" in following_name) or (
            "KATAKANA" in previous_name and "KATAKANA" in following_name) or (
            "CJK" in previous_name and "CJK" in following_name):
            penalty += 2.1
    if right and right[0] in PUNCTUATION:
        penalty += 20
    return penalty


def _partitions(text: str, line_count: int):
    points = legal_breaks(text)
    if line_count == 1:
        return [(text,)]

    def walk(start: int, remaining: int, lines: tuple[str, ...]):
        if remaining == 1:
            tail = text[start:].strip()
            if tail:
                yield lines + (tail,)
            return
        for point in points:
            if point <= start or point >= len(text):
                continue
            segment = text[start:point].strip()
            if not segment:
                continue
            yield from walk(point, remaining - 1, lines + (segment,))
    yield from walk(0, line_count, ())


def score_line_breaks(text: str, width_fn, max_width: float, max_lines: int = 3,
                      manual_lines: tuple[str, ...] | None = None) -> tuple[LineBreakCandidate, ...]:
    normalized = " ".join((text or "").split())
    if manual_lines:
        manual = tuple(" ".join(line.split()) for line in manual_lines if line.strip())
        if manual:
            widths = [width_fn(line) for line in manual]
            return (LineBreakCandidate(manual, -10.0, max(widths, default=0) / max_width),)
    if not normalized:
        return (LineBreakCandidate(("",), 0, 0),)
    candidates: dict[tuple[str, ...], LineBreakCandidate] = {}
    for count in range(1, max_lines + 1):
        for lines in _partitions(normalized, count):
            widths = [width_fn(line) for line in lines]
            ratio = max(widths, default=0) / max_width
            if ratio > 1.08:
                continue
            mean = sum(widths) / max(1, len(widths))
            balance = sum((width - mean) ** 2 for width in widths) / (max_width * max_width)
            # Prefer one line for short titles; add lines only when the block reads better.
            line_cost = (count - 1) * (0.65 if len(normalized) < 12 else 0.55)
            semantic = sum(_break_penalty(normalized, normalized.find(line) + len(line))
                           for line in lines[:-1] if line)
            score = ratio * ratio * 0.8 + balance * 0.7 + line_cost + semantic * 0.22
            candidate = LineBreakCandidate(lines, score, ratio)
            current = candidates.get(lines)
            if current is None or candidate.score < current.score:
                candidates[lines] = candidate
    if not candidates:
        # A single unbreakable token still gets a deterministic, nonempty layout.
        return (LineBreakCandidate((normalized,), 100.0, width_fn(normalized) / max_width),)
    return tuple(sorted(candidates.values(), key=lambda item: (item.score, len(item.lines), item.lines)))


def choose_line_break(text: str, width_fn, max_width: float, max_lines: int = 3,
                      manual_text: str = "") -> LineBreakCandidate:
    manual = tuple(line for line in (manual_text or "").splitlines() if line.strip())
    return score_line_breaks(text, width_fn, max_width, max_lines, manual or None)[0]
