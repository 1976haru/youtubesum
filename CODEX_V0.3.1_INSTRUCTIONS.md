# Codex implementation brief — v0.3.1 Thumbnail Protection Build

Repository: 1976haru/youtubesum
Working branch: v0.3.1-dev
Do not work on main.

## Why this milestone exists
A real completed Tokyo Chill thumbnail was tested in v0.3.
The program cropped A/B so baked-in title text disappeared, and Haar face detection missed the side-profile male protagonist and focused the female character instead.
This is a product/design bug, not user error.

Two starter commits already exist on this branch:
- completed-thumbnail protection mode + non-crop candidate engine
- UI controls for input type and protagonist position

Read the current code before editing and preserve those changes.

## P0 — completed thumbnail protection is the default
Input type:
1. 완성 썸네일(글자 보호) [DEFAULT]
2. 텍스트 없는 원본 이미지

For completed-thumbnail mode:
- NEVER crop, pan-crop, zoom-crop, or remove any source region.
- Keep baked-in text, logo, episode number and decorative elements inside the frame.
- C candidate should be the untouched full composition (resize only when required by output dimensions).
- A/B may use only non-destructive local emphasis (clarity, sharpness, tiny tone emphasis, subject/relationship emphasis).
- Do not blur/dim the whole frame in a way that damages title readability.
- If the source is already 1280x720, C should preserve its geometry exactly.

Raw-image mode may continue using safe crops because there is no baked-in text to preserve.

## P1 — protagonist selection must not depend on face detector correctness
Current Haar detection is not reliable for side profiles.

Keep quick choices:
- 자동
- 왼쪽 인물
- 오른쪽 인물
- 두 사람

Add a direct manual selection workflow:
- Button: "주인공 직접 지정"
- Show the original/full thumbnail in a selection dialog or canvas.
- User clicks the protagonist's face/body location.
- Optional second button/click: "상대 인물 지정".
- Store click coordinates normalized to 0..1 so resizing does not break them.
- Show visible marker(s) in the selection UI.
- Provide "지정 해제".
- If a manual protagonist point exists, it overrides Haar/auto detection.
- Never infer gender. The user designates the intended protagonist.

A PERSON:
- preserve whole completed thumbnail
- locally emphasize the selected protagonist
- no crop

B EMOTION/MEMORY:
- preserve whole completed thumbnail
- if protagonist + counterpart points exist, emphasize both and their relationship area
- if only protagonist exists, use a broader emotional emphasis around that subject
- no crop

C STORY/SCENERY:
- preserve complete original composition
- no crop

## P2 — visible UX guardrails
- Change app version to v0.3.1.
- Clearly show current mode and selected protagonist state.
- When completed-thumbnail mode is selected, display:
  "글자/로고 보호 ON · 크롭 금지"
- When raw-image mode is selected, display:
  "원본 이미지 모드 · 안전 크롭 허용"
- Candidate notes must explain what changed.
- Keep A/B/C side-by-side preview and individual/all save.
- Reset manual points when a different source image is selected.

## P3 — single-click Windows use
The user should not need PowerShell or Python for normal use.

- Build dist/YouTubeDynamicThumbnailStudio.exe.
- Investigate replacing the external FFmpeg PATH dependency with a redistributable bundled solution (prefer imageio-ffmpeg or another license-compatible approach).
- Do not silently download executables at runtime.
- Document any third-party binary license obligations.
- If a bundled solution is used, Motion must work from the EXE on a clean Windows environment without ffmpeg on PATH.
- Keep Unicode Korean/Japanese/space path support.

## Tests / validation gate
Automated:
- compile/import PASS
- existing v0.3 tests remain PASS
- completed-thumbnail mode produces exactly A/B/C + manifest
- all outputs 1280x720
- source 1280x720 completed thumbnail: C geometry/full-frame is preserved
- completed-thumbnail A/B do not call crop functions
- raw-image mode still supports safe crop
- manual normalized protagonist point survives resize
- Unicode paths PASS

Real-world visual validation:
Use at least:
1. Tokyo Chill completed thumbnail with 2 people and baked-in text, side-profile intended protagonist
2. Tokyo Chill completed thumbnail with 1 person and text
3. OLD POP LOUNGE completed thumbnail with text

For case 1, report explicitly:
- all original text visible in A/B/C: PASS/FAIL
- intended manually selected protagonist emphasized in A: PASS/FAIL
- both people remain visible in B when counterpart is selected: PASS/FAIL
- C full thumbnail preserved: PASS/FAIL

Windows:
- EXE double-click launch PASS
- no PowerShell required for normal use
- Unicode candidate generation through EXE PASS
- Motion through EXE on machine without ffmpeg PATH: PASS/FAIL and reason

## Git discipline
- Work only on v0.3.1-dev.
- Do not merge or push to main.
- Small logical commits.
- Do not commit generated test images/videos, build/, dist/, logs/, or downloaded caches.
- Update README with exact build and validation evidence.
- At the end push v0.3.1-dev and report:
  - commit SHA
  - EXE path and SHA-256
  - PASS/FAIL table
  - screenshots/description of the 3 real-world validation cases
  - remaining limitations
