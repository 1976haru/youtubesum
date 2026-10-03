# Claude Code implementation brief — v0.6 Pro Thumbnail Editor

Repository: 1976haru/youtubesum
Working branch: v0.6-pro-editor-dev
Base: v0.5.1-dev
Do not modify or merge main.

## Why this milestone exists

The current app has a good rendering foundation (Skia/HarfBuzz typography, A/B/C candidates, Live Composer, Background Fit, Image Bridge), but the editing experience is still too close to a parameter form.

The new reference UI shows the target interaction model:
- left panel = templates/presets/assets
- center = large WYSIWYG canvas
- right panel = layer list + selected-object property inspector
- direct drag/resize/rotate on canvas
- immediate visual feedback while changing font/size/stroke/shadow/etc.

Do NOT copy the reference application's branding or visual design pixel-for-pixel. Use it only as a workflow/interaction reference.

The target is a real thumbnail editor, not a form that happens to render thumbnails.

---

# Product goal

A user should be able to:

1. Generate/open a clean background.
2. Pick A/B/C candidate.
3. Click a text object directly on canvas.
4. Drag it, resize it, rotate it.
5. Change font, size, stroke, shadow, glow, spacing and instantly see the result.
6. Compare the result at 1280x720, 340px, and 180px.
7. Generate/edit the background through the Image Bridge without losing text layers.
8. Save/reopen the project with all layers and edits intact.

---

# P0 — Three-pane editor layout

Replace the current form-heavy composition with a professional 3-pane editor.

## Left panel: Templates / Styles / Assets

Sections:
- Channel presets
- Typography presets
- Text style cards
- Color palettes
- Background tools
- Image Bridge actions

Requirements:
- scrollable
- preview cards, not plain dropdown-only UX
- clicking a style card immediately applies it to the selected text layer
- Tokyo Chill and OLD POP LOUNGE grouped separately
- include "Recent" and "Favorites" sections for fonts/styles if practical

Typography style cards should preview the current actual title text, not dummy text when possible.

## Center panel: Main canvas

- dark editor background
- 16:9 canvas centered
- zoom controls: 25 / 50 / 75 / 100 / Fit
- pan canvas when zoomed
- direct object selection
- bounding box
- resize handles
- rotation handle
- drag movement
- snapping guides
- safe-zone overlay toggle
- optional rule-of-thirds / center guides
- subject/face avoid-area overlay toggle

Canvas changes must be WYSIWYG with final export.

## Right panel: Layers + Properties

Top:
- layer list
- visibility toggle
- lock toggle
- rename
- reorder up/down
- duplicate
- delete

Layer types:
- background
- image
- text
- badge/label
- shape
- overlay/gradient

Below layer list:
context-sensitive inspector for selected layer.

---

# P1 — True layer model

Introduce a non-destructive document model.

Suggested model:

ThumbnailDocument
- canvas_width
- canvas_height
- channel
- candidate_type
- layers[]
- project metadata
- bridge metadata
- undo state

Common layer fields:
- id
- type
- name
- visible
- locked
- z_index
- x
- y
- width
- height
- rotation
- opacity

TextLayer:
- text
- font_family
- font_weight
- font_size
- fill
- gradient
- outline_color
- outline_width
- secondary_outline_color (optional)
- secondary_outline_width (optional)
- shadow_color
- shadow_x
- shadow_y
- shadow_blur
- shadow_opacity
- glow_color
- glow_blur
- glow_opacity
- letter_spacing
- line_spacing
- alignment
- highlight_ranges / highlight_word
- max_lines
- manual_line_breaks

BadgeLayer:
- text
- shape preset
- fill
- border
- radius
- padding

Keep old A/B/C generator compatibility by converting generated layouts into this document/layer representation.

---

# P2 — Direct manipulation

Required interactions:
- click layer on canvas -> select
- drag -> move
- corner handle -> proportional resize
- side handle -> horizontal/vertical resize where applicable
- rotation handle -> rotate
- arrow keys -> nudge 1px
- Shift+arrow -> nudge 10px
- Delete -> delete selected layer
- Ctrl+D -> duplicate
- Ctrl+Z / Ctrl+Y -> undo/redo
- Ctrl+S -> save project

Snapping:
- canvas center
- left/right/upper/lower safe margins
- other layer edges/centers
- protagonist/face avoid boxes should not be snapping targets but can trigger warning

Show temporary alignment guides while dragging.

---

# P3 — Real-time property editing

This is the most important UX requirement.

All these controls must update the selected layer in near-real-time:
- font family
- font weight
- font size
- fill
- outline color
- outline width
- second outline
- shadow
- glow
- opacity
- letter spacing
- line spacing
- alignment
- rotation
- x/y
- width/height
- highlight color

Target:
- debounce <= 120 ms for sliders/text controls
- no "Generate" button required for normal text-property adjustments
- no AI call during ordinary typography edits
- Skia/HarfBuzz remains the rendering path
- final export and preview must share the same renderer

---

# P4 — Font browser, not only a dropdown

The current user needs to decide visually which font and size works.

Implement a font browser:
- scan installed fonts through the existing font registry
- filter by CJK coverage
- display actual title text in each font row/card
- search field
- show family + weight
- favorites star
- recent fonts
- fallback warning if current font does not cover all glyphs

Tabs/filters:
- Japanese
- Korean
- Latin
- All
- Display / Bold preference

Do not bundle proprietary fonts.

If an open-source font is not installed, do not silently download it.
A future installer workflow can be added later.

---

# P5 — Background-aware typography

The biggest remaining quality gap is that text often looks independent from the background.

Add a "배경 맞춤" system.

## Analysis

For the selected text region compute:
- average luminance
- local contrast
- local color palette
- visual busyness/edge density
- overlap with subject/face boxes

## One-click actions

Add:
- [배경에 맞춤]
- [더 강하게]
- [더 부드럽게]
- [대비만 보정]

"배경에 맞춤" should suggest/apply:
- fill color
- outline color
- outline width
- shadow strength
- glow strength
- optional soft plate / gradient
- highlight color

Use extracted project palette sidecar when available.

Do not blindly recolor all styles.
Preserve channel identity:
- Tokyo Chill = cinematic, urban, youthful
- OLD POP LOUNGE = calmer, larger, high readability

## Readability meter

Show:
- GOOD / WARNING / POOR
- 340px readability
- 180px readability
- background contrast warning
- face overlap warning

---

# P6 — Background plates and gradient overlays

The reference workflow makes heavy use of text/background separation.

Support as proper layers:
- soft black gradient
- soft white gradient
- rounded translucent plate
- colored label strip
- vignette behind title
- local blur plate

Each should be editable:
- opacity
- width/height
- gradient direction
- blur
- corner radius

They must be independent layers, not baked permanently into the background.

---

# P7 — A/B/C as editable documents

A/B/C should no longer only be static generated images.

Each candidate has its own document state.

Candidate tabs:
- A PERSON
- B EMOTION / MEMORY
- C STORY / SCENERY

Required:
- switch A/B/C without losing edits
- copy selected layer A -> B/C
- copy full typography layout A -> B/C
- reset candidate to generated default
- lock shared metadata (EP/channel title) across candidates if desired

Candidate differentiation should remain meaningful:
- A = protagonist emphasis
- B = relationship/emotion
- C = context/scenery

But after generation, the user has full manual control.

---

# P8 — Reference-thumbnail helper

Add optional "참고 썸네일" panel.

Purpose:
- show a user-made Canva thumbnail next to the editor
- do NOT OCR-copy the design automatically by default
- allow visual comparison of:
  - title scale
  - title position
  - top labels
  - palette
  - whitespace

Optional helper:
- "참고 이미지에서 색상만 추출"
- "참고 이미지에서 레이아웃 가이드 만들기"

Do not reproduce copyrighted third-party artwork automatically.
This is for the user's own/reference work.

---

# P9 — Image Bridge integration in the editor

Keep v0.5.1 bridge behavior.

Top toolbar buttons:
- [배경 생성]
- [배경 편집]
- [image에서 새로고침]

When background is regenerated/edited:
- replace/update background layer only
- preserve all text/badge/shape layers
- re-read:
  - subject_boxes.json
  - safe_zones.json
  - palette.json
  - composition.json
- show warning if new background causes title/face collision

Do not destroy manual text placement automatically.
Offer:
- [현재 배치 유지]
- [새 안전영역에 맞춰 재배치]

---

# P10 — Project save format

Add a project file such as:

thumbnail_project.json

It must contain:
- document version
- project path
- A/B/C layer documents
- source background path
- bridge metadata
- text values
- typography properties
- layer transforms
- palette
- manual protagonist/counterpart points
- last selected candidate/layer
- editor zoom
- app version

Saving should never modify source images.

Autosave:
- optional
- write atomically

---

# P11 — Visual quality standards

Use the provided reference editor only for workflow inspiration.

Acceptance criteria for typography:
- title must feel designed, not like subtitles
- font hierarchy is obvious
- title/background harmony is coherent
- no face obstruction
- 340px preview readable without squinting
- 180px preview still preserves main title hierarchy
- Tokyo Chill should feel contemporary and cinematic
- OLD POP should feel clear, mature, and calm

Avoid:
- oversized text that dominates the subject without intent
- random neon glow
- excessive thick outlines on every preset
- one-size-fits-all text colors
- centered text over faces
- tiny top labels that become illegible

---

# P12 — Tests

Keep all current tests passing.

Add tests for:
- document serialization/deserialization
- layer ordering
- undo/redo
- drag coordinate transforms
- zoom-to-canvas transforms
- text property updates
- font fallback
- background-fit suggestion
- layer persistence across A/B/C
- bridge background replacement preserves text layers
- project save/load with Korean/Japanese paths
- export uses same renderer as editor preview

Manual validation:
1. Tokyo Chill two-person relationship thumbnail
2. Tokyo Chill one-person male-story thumbnail
3. OLD POP couple thumbnail
4. OLD POP scenery thumbnail

For each:
- 1280x720 editor screenshot
- 340px preview
- 180px preview
- readability result
- before/after comparison

---

# P13 — Performance

Target:
- ordinary text slider updates <= 120 ms perceived latency
- canvas pan/drag feels interactive
- do not rescan all Windows fonts on every property change
- cache font metadata
- cache shaped text when possible
- AI bridge calls always run off the GUI thread

---

# P14 — Windows packaging

Rebuild packaged Windows version.

Verify:
- double-click GUI PASS
- layer editor PASS
- live font preview PASS
- drag/resize/rotate PASS
- project save/reopen PASS
- Japanese/Korean paths PASS
- Motion still PASS
- Image Bridge still PASS

Report EXE/package path and SHA-256.

---

# Git discipline

- work only on v0.6-pro-editor-dev
- do not modify main
- do not commit build/dist/logs/generated media
- small logical commits
- update README

Final report:
- final commit SHA
- package path + SHA-256
- PASS/FAIL table
- actual screenshots for Tokyo Chill and OLD POP
- known limitations
- performance timings for live slider and drag updates
