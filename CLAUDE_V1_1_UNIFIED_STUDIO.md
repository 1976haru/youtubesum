# CLAUDE — v1.1 Unified Studio

Repository: 1976haru/youtubesum
Branch: v1.1-unified-studio-dev
Base: main
Do not modify main until final validation.

## Problem

The current product technically works, but the user experience is fragmented:
- CoverMorph Studio is a separate EXE and separate UI
- YouTube Dynamic Thumbnail Studio is another EXE and another UI
- controls, terminology, and workflow differ
- the CoverMorph RC2 screen exposes too many legacy conversion controls for everyday creation
- the user wants one simple program for:
  - YouTube thumbnail image generation
  - thumbnail text/layout editing
  - Shopify hero/collection/product images
  - queue / pause / resume
  - reference images
  - export

The user should not have to know which executable to launch.

## Product decision

YouTube Dynamic Thumbnail Studio becomes the single user-facing application.

CoverMorph remains an internal image-generation backend/service.

Normal user flow:
- launch ONE EXE
- choose purpose
- enter prompt / references
- generate
- review candidates
- edit text/layout if needed
- export

Do not require the user to open CoverMorph Studio manually in normal operation.

## Mandatory progress report

At meaningful checkpoints:

전체 진행률: NN%
현재 단계: ...
완료: ...
진행 중: ...
남은 것: ...
현재 리스크/막힘: ...

현재 단계 성공 가능성: NN%
전체 프로젝트 성공 가능성: NN%

---

# Phase 1 — New Home screen

Replace the current first impression with a simple Home screen.

Primary large cards:

1. YouTube 썸네일 만들기
2. Shopify 이미지 만들기
3. 기존 프로젝트 열기
4. 작업 대기열
5. 설정

Do not show legacy conversion/OCR controls on Home.

Existing advanced/legacy tools remain accessible under:
- 도구
- 고급 기능
or a secondary tab

Do not delete legacy functionality.

---

# Phase 2 — Unified Create workflow

Use a guided 4-step workflow.

## STEP 1 — 무엇을 만들까요?

YouTube:
- Tokyo Chill
- OLD POP
- Custom YouTube

Shopify:
- Hero Banner
- Collection Banner
- Product Lifestyle
- Promo Tile
- Mobile Banner
- Custom Shopify

## STEP 2 — 내용 입력

Show only the fields needed for the chosen purpose.

Common:
- prompt / scene description
- optional title
- optional subtitle
- optional channel/store preset

Reference images:
- drag/drop
- role selector:
  - 인물
  - 상품
  - 스타일
  - 구도
  - 배경

For Shopify product mode:
- default = 자연광 보정 합성
- toggle = 원본 그대로 합성
- advanced = AI 재구성 · 변형 가능

## STEP 3 — 생성 설정

Simple controls:
- 빠른 미리보기
- 일반
- 최고 품질

PC usage:
- 작업 중 PC 우선
- 균형
- 자리 비움

Candidate count:
- 1 / 2 / 4

Do not show model names by default.

## STEP 4 — 생성 및 선택

- generate button
- large candidate cards
- show 2–4 candidates
- 340px/180px preview for YouTube
- product crop for Shopify
- warnings
- choose candidate
- regenerate
- change seed
- edit prompt

Chosen image should move directly into the editor without exporting/importing manually.

---

# Phase 3 — One editor

The Pro Editor becomes the single editing workspace.

For YouTube:
- generated background
- title
- subtitle
- channel badge
- episode badge
- drag/resize/rotate
- safe zones
- collision warnings
- A/B/C layout suggestions
- 340px/180px previews

For Shopify:
- generated background/product composite
- optional headline
- optional subheadline
- optional CTA label
- product-safe zone
- text-safe zone
- no YouTube-specific badges unless selected

The user should not switch applications.

---

# Phase 4 — CoverMorph backend integration

Use CoverMorph main/RC2 as the backend.

Preferred runtime:
- call packaged CoverMorph backend via existing bridge
- auto-discover backend
- persisted path in youtubesum settings
- status check at startup

Normal UI should only show:
- AI 엔진: 준비됨 / 연결 필요
- GPU
- model readiness
- last generation result

Advanced settings may expose:
- CoverMorph EXE path
- models folder
- timeout
- engine details

No environment variables required.

If backend is not found:
- show 연결 설정 button
- browse for CoverMorphStudio.exe
- remember path

---

# Phase 5 — Unified settings

Create one Settings screen.

Sections:
- AI 엔진
- 모델 폴더
- 저장 폴더
- 기본 품질
- PC 사용 모드
- YouTube 기본 프리셋
- Shopify 기본 프리셋
- 고급 설정

Persist in user-local settings.

Do not require editing config files.

---

# Phase 6 — Queue in main app

Bring queue UI into youtubesum.

Show:
- status
- purpose
- prompt/title
- quality
- progress
- output
- warning

Controls:
- 시작
- 현재 작업 후 일시정지
- 재개
- 선택 취소
- 실패 재시도
- 완료 결과 열기

Queue must survive app restart.

Use CoverMorph backend queue state where practical, but present it through one UI.

---

# Phase 7 — Hide complexity

Normal mode must not show:
- OCR mask
- manual conversion pipeline
- multiple internal model names
- backend JSON
- bridge protocol
- raw environment variables
- technical sidecar filenames

Advanced tools may still expose them.

Goal:
A normal user should understand the first screen within 10 seconds.

---

# Phase 8 — Visual redesign

Current UI is too dense.

Target:
- clear spacing
- larger section headers
- fewer controls per screen
- progressive disclosure
- left navigation or top-level cards
- center preview
- right properties only when editing

Suggested navigation:

Home
Create
Editor
Queue
History
Settings

Legacy:
Tools > Advanced

Do not copy another product's branding.

---

# Phase 9 — One-click normal launch

Final user experience:
- one desktop shortcut
- one primary EXE
- no BAT file
- no separate CoverMorph launch
- backend starts only when needed
- backend closes/unloads according to memory mode

The normal executable should be:
YouTubeDynamicThumbnailStudio.exe
or rename product if justified, but avoid breaking existing project associations.

Optional future rename:
Creator Studio
Do not rename in this milestone unless all persistence/project paths are safely migrated.

---

# Phase 10 — Unified distribution

Create one distribution ZIP/folder for the user.

Preferred structure:

UnifiedStudio/
  YouTubeDynamicThumbnailStudio.exe
  _internal/
  backend/
    CoverMorphStudio/
      CoverMorphStudio.exe
      _internal/
  QUICKSTART_KO.txt

Models remain external and are selected once.

If duplication makes package impractically huge:
- keep CoverMorph installation external
- but create one launcher/UI and auto-discovery
- document exact tradeoff
- do not sacrifice reliability just to force one physical EXE

The requirement is ONE user-facing launch point, not necessarily one binary file internally.

---

# Phase 11 — First-run experience

On first launch:

1. detect CoverMorph backend
2. detect models folder
3. show GPU/model status
4. if ready -> continue
5. if not -> simple setup

Do not make the user configure environment variables.

---

# Phase 12 — Validation

Real validation must include:

A. YouTube
1. launch only youtubesum
2. Tokyo Chill woman
3. generate candidates
4. choose one
5. edit title
6. export
7. reopen project

B. YouTube couple
- verify face/text collision handling

C. OLD POP
- verify preset

D. Shopify
1. launch only youtubesum
2. choose Product Lifestyle
3. add LUMA reference
4. Natural-Light Composite
5. choose candidate
6. optional text
7. export

E. Queue
- 5 mixed jobs
- pause after current
- close app
- reopen
- resume

F. Memory
- backend only loads when needed
- returns memory after work in PC-priority mode

---

# Phase 13 — usability acceptance

Ask these questions during validation:

- Did user need to know which backend EXE to launch? -> must be NO
- Did user need PowerShell? -> must be NO
- Did user need environment variables? -> must be NO
- Did user have to manually export from one app and import to another? -> must be NO
- Is the first screen understandable without instructions? -> target YES
- Can YouTube and Shopify both start from Home? -> YES
- Can advanced tools still be reached? -> YES

---

# Phase 14 — package and report

Build:
v1.1.0-rc1

Report:
- EXE path
- ZIP path
- SHA-256
- tests
- screenshots of Home/Create/Editor/Queue/Settings
- end-to-end results
- package structure
- memory behavior
- known limitations

Do not merge main automatically.

Final recommendation:
- READY FOR MAIN
- READY WITH MINOR LIMITATIONS
- NOT READY

## Final rule

This milestone succeeds only if the user can forget that CoverMorph is a separate program.

The backend may remain separate internally, but the user-facing workflow must feel like one product.
