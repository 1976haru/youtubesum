# Codex implementation brief — v0.3.2 Meaningful Candidate Build

Repository: 1976haru/youtubesum
Working branch: v0.3.2-dev
Do not change main.

## Why this milestone exists
Real v0.3.1 screenshot testing showed that A/B/C are visually almost identical even though the protection logic works.
This is expected because a completed thumbnail is one flattened image: text/logo/people/background are baked into the same pixels. If we forbid crop and text damage, only subtle tone/local emphasis remains, which is not sufficient for a meaningful YouTube thumbnail test.

Therefore v0.3.2 must distinguish two workflows.

## Workflow 1 — Finished thumbnail protection
Name: 완성 썸네일 보호형

Purpose:
- Preserve an already-finished thumbnail.
- A/B/C may differ only by safe visual emphasis.
- This mode is NOT the preferred mode for strong A/B/C differentiation.

Requirements:
- Keep all text/logo/EP pixels.
- No crop.
- C = exact original composition.
- A/B use stronger but tasteful subject/relation emphasis.
- Add a visible warning if candidate similarity is too high.
- Add a quantitative candidate difference indicator for A↔B, A↔C, B↔C using SSIM or perceptual-hash-like local metric.
- If similarity is above threshold, UI must show:
  "후보 차이가 작습니다. 원본 이미지 + 템플릿 모드를 권장합니다."

## Workflow 2 — Original image + thumbnail template (PRIMARY)
Name: 원본 이미지 + 템플릿

This is the main workflow for real YouTube 3-candidate testing.

Inputs:
1. 원본 이미지(텍스트 없음) — required
2. 참고 완성 썸네일 — optional, used only as visual/reference preview, never as the image layer to crop
3. Channel preset — Tokyo Chill / OLD POP LOUNGE
4. Story type — 남자 이야기 / 여자 이야기 / 두 사람 이야기 / 자동
5. Episode text — e.g. EP.001
6. Main title text
7. Subtitle/channel line
8. protagonist/counterpart manual click remains available

Generate 3 genuinely different candidates from the RAW image while drawing text as separate layers:

A PERSON:
- crop/reframe raw image around intended protagonist
- large subject presence
- all text redrawn by the program in safe zones
- never rely on baked-in text

B EMOTION / MEMORY:
- preserve protagonist + counterpart relation, gaze/negative space
- medium framing
- alternate text layout, not only alternate color

C STORY / SCENERY:
- wide/environmental framing
- larger story context
- alternate text position/layout

For OLD POP:
A PERSON / B MEMORY / C SCENERY should follow the same principle but calmer framing and typography.

## Text/template engine
Do NOT OCR and attempt to surgically erase baked text from the completed thumbnail.
Do NOT use generative inpainting in this milestone.

Instead:
- render new text from user-entered fields
- use channel template presets
- support Japanese/Korean/English Unicode text
- package at least one redistributable/OS-available font strategy without violating font redistribution rules
- prefer Windows installed fonts; implement safe fallback
- never embed/share proprietary font files in the repository
- allow font family selection from installed fonts later; for v0.3.2 basic preset is enough

Tokyo Chill default template should roughly support:
top-left channel name
top-center/right story label
top-right episode
large Japanese main line lower-left/mid
small English subtitle near bottom

OLD POP default should use calmer, simpler typography and larger readability for older viewers.

## Candidate diversity gate
Before enabling save-all:
- calculate pairwise visual difference score
- if all three are nearly identical, show warning
- allow save but clearly mark "A/B/C 차이 부족"
- template mode should normally exceed the minimum diversity threshold

## UX
Tabs/controls should make the distinction obvious:
- 완성 썸네일 보호형
- 원본 이미지 + 템플릿 [권장]

Do not call the existing completed-thumbnail mode "dynamic" if the visual change is tiny.
Explain in the UI:
"완성 썸네일은 한 장으로 합쳐진 이미지라 큰 재구성이 어렵습니다."

For template mode, show A/B/C preview side by side.

## Real validation
Use the provided real Tokyo Chill screenshot context as acceptance criteria:
- male-story thumbnail must not end up female-centered when the male protagonist is selected.
- A/B/C must be visibly different at 340px preview size, not only at pixel level.
- text remains readable in every candidate.
- no face cuts.
- C remains the widest environmental/story option.
- A visibly emphasizes the selected protagonist.
- B visibly emphasizes the relation/emotion.

Also validate OLD POP with a representative calm image.

## Tests
- compile/import PASS
- all v0.3.1 tests remain PASS
- completed-thumbnail protection still works
- template mode outputs exact 1280x720 A/B/C
- Unicode text rendering path PASS
- male-story manual protagonist selection PASS
- pairwise diversity metric produces a warning for near-identical synthetic inputs
- template mode produces visibly different crop boxes in unit tests
- EXE double-click launch PASS
- bundled Motion remains PASS

## Git discipline
- Work only on v0.3.2-dev
- Do not merge main
- do not commit build/dist/vendor/logs/generated media
- update README
- push only after validation
- final report: commit SHA, EXE path/hash, PASS/FAIL table, remaining limitations
