# YouTube Dynamic Thumbnail Studio v0.6.0-dev

## v0.6 Pro Editor (default tab)

v0.6 turns the A/B/C generator into a layer-based, WYSIWYG thumbnail editor. The **★ Pro Editor** tab opens first; the previous tabs (3후보 미리보기, Live Composer, Motion Intro, 테스트 기록) are unchanged.

**Three panes**
- **Left — templates/styles/assets:** channel presets (Tokyo Chill · cinematic/urban, OLD POP LOUNGE · calm/large), the 12 typography presets as cards that preview the *current title* (Tokyo Chill and OLD POP grouped separately; right-click = ★ favorite, plus a Recent/Favorites row), one-click text effect cards, colour palettes (channel palettes, `palette.json`, colours extracted from a reference image), background tools, Image Bridge actions and the reference-thumbnail panel.
- **Centre — canvas:** dark editor background, 16:9 canvas at 25/50/75/100%/Fit (Ctrl+wheel zoom, middle-drag pan), direct click-select, drag, 8 resize handles (corners scale proportionally and scale the type; sides re-wrap), a rotation handle (Shift = 15° steps), snapping guides (canvas centre, safe margins, other layers' edges/centres; Alt disables), and overlays for safe area + YouTube timestamp, rule of thirds, centre lines, text-avoid zones and subject/face boxes. Below the canvas: true 340 px and 180 px previews and a GOOD/WARNING/POOR readability meter.
- **Right — layers + inspector:** layer list with visibility, lock, rename (double-click), reorder, duplicate, delete; a context inspector for text, badge, shape, overlay and image layers; a **font browser** tab; and a **배경 맞춤** tab.

**Layer model.** `editor/document.py` defines `ThumbnailDocument` with background, image, text, badge, shape and overlay layers (common transform fields plus full typography: family/weight/size, fill + gradient, outline and second outline, shadow x/y/blur/opacity, glow, letter/line spacing, alignment, highlight word/colour/scale, max lines, manual breaks). The existing A/B/C generator output is converted into these documents, so every candidate starts from the generated layout and stays fully editable.

**Live editing.** Every inspector control updates the selected layer immediately — no Generate button and no AI call. Glyphs are shaped by HarfBuzz and rasterized by Skia into cached patches, then composited with OpenCV; the editor canvas, the 340/180 previews and PNG export all call the same `LayerRenderer.render`, so the preview is the export. Measured on the validation machine (i9-12900, real Tk events, edit → frame on screen): font-size slider median 29–53 ms (max 105 ms), canvas drag median 26–30 ms. Fonts are scanned once on a background thread and cached; HarfBuzz shaping is cached per text run and scaled per size.

**Font browser.** Lists installed families (no fonts are bundled or downloaded) with Japanese/Korean/Latin/All filters, search, Display/Bold-first ordering, ★ favorites and recent fonts, and renders the current title in each family. The text inspector warns when the chosen family lacks glyphs and a fallback font will be used.

**배경 맞춤.** Analyses the area under the selected text (luminance, local contrast, 5-colour palette, edge density, face vs. torso overlap) and offers **배경에 맞춤 / 더 강하게 / 더 부드럽게 / 대비만 보정**. Suggestions keep channel identity (Tokyo Chill: white ink, tinted deep outline, restrained neon glow, cinematic gradient; OLD POP: warm cream ink, thicker outline, almost no glow, soft plate), prefer the project `palette.json`, and add a separate editable plate/gradient layer only when the background needs it.

**Plates and overlays** are independent layers: soft black/white gradient, rounded translucent plate, coloured label strip, vignette and local blur plate, each with opacity, size, direction, blur/feather and corner radius.

**A/B/C documents.** Each candidate keeps its own document and undo history. Copy the selected layer or the whole typography layout to the other candidates, reset a candidate to its generated default, and lock shared EP/channel labels across candidates.

**Image Bridge in the editor.** 배경 생성 / 배경 편집 / image에서 새로고침 run off the GUI thread, re-read `subject_boxes.json`, `safe_zones.json`, `palette.json` and `composition.json`, and replace **only** the background layers. If the new background collides with the title/labels you choose **현재 배치 유지** or **새 안전영역에 맞춰 재배치**.

**Reference thumbnail.** Shows your own reference next to the editor, can extract colours only, or overlay it as an editor-only ghost guide (never exported, never auto-copied).

**Project files.** Ctrl+S writes `thumbnail_project.json` (document version, A/B/C layer documents and generated defaults, source background, bridge metadata, palette, protagonist/counterpart points, selected candidate/layers, zoom, app version) plus content-addressed background PNGs in `thumbnail_project_assets/`. Writes are atomic, source images are never modified, and Korean/Japanese/space-containing paths work. Optional autosave (every 60 s) uses the same atomic writer.

**Shortcuts:** arrows = 1 px, Shift+arrows = 10 px, Delete, Ctrl+D duplicate, Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z) undo/redo, Ctrl+S save, double-click a text layer to edit its text.

**Line breaking.** Korean titles now wrap only at spaces (keep-all), Japanese breaks keep okurigana with the kanji stem (終電を逃した / 夜、僕は), and the editor offers one-line layouts for short titles. The v0.4 20-title Japanese snapshot is unchanged.

**Validation.** `py -3.10 scripts\v06_validation.py` runs four scenarios (Tokyo two-person relationship, Tokyo one-person male story, OLD POP couple, OLD POP scenery) through the real GUI and writes window captures, 1280×720/340/180 exports, before (v0.5.1 renderer) / after sheets, readability and latency to `build\v06_validation\`. `YouTubeDynamicThumbnailStudio.exe --self-test-editor <project folder> [--capture out.png] [--report report.json]` drives the packaged GUI with real mouse/keyboard events (select, drag, resize, rotate, nudge, undo/redo, live typography, font browser, background fit, A/B/C independence, save/reopen on a Korean/Japanese path, export, bridge refresh) and exits non-zero on failure.

---

v0.4 replaces Pillow text painting with a vector typography pipeline: Skia raster/vector drawing, HarfBuzz glyph shaping, fontTools installed-font inspection, and uniseg Unicode line-breaking. Pillow remains only for Tk preview conversion and non-text image compatibility; thumbnail titles and badges are rendered as vector glyphs/SVG.

## Professional Typography Engine

The new `typography/` package separates font inventory, Unicode line breaking, shaping, style presets, Skia rendering, SVG badge rendering, and A/B/C thumbnail layouts. The UI exposes 12 channel presets, adjustable title size/outline/glow/shadow, highlight word, automatic 1-3 line wrapping, manual `|` line breaks, a line-break preview, 340px preview, and a safe-zone overlay.

Tokyo Chill presets: Japanese Impact, Romantic Neon, Urban Story, Soft Memory, Night Drive, Heartbeat Clean.

Old Pop Lounge presets: Senior Classic, Warm Gold, First Snow, Autumn Lounge, Christmas Glow, Calm Blue Memory.

The registry scans installed system fonts and extracts family, subfamily, weight, style, Unicode coverage, and variable axes. No commercial fonts are copied into the repository or EXE. Japanese and Korean fallback families are channel-weighted. Text shaping supports kerning, ligatures, and tracking across mixed Latin/Japanese/Korean runs. Japanese line breaking uses Unicode break opportunities plus kinsoku and scores up to three lines.

## A/B/C and optional image storage

- A PERSON emphasizes one protagonist and offers a strong lower-left/lower title with a compact subject badge.
- B EMOTION/MEMORY uses a centered relationship headline, EP badge, and a less aggressive type scale.
- C STORY/SCENERY moves to an upper-left/right anchor and preserves scenery.

Candidate layout searches alternate anchors to avoid supplied subject and safe-zone boxes. `canvas_clean.png` (or legacy `cleaned_canvas.png`) takes precedence as the clean base; `safe_zones.json`/`safe_zone.json` and `subject_boxes.json` provide regions. `preview_reference.png`/`reference_thumb.png` is discovered for comparison only and is never composited into the new thumbnail. Missing sidecars fall back to the existing local image workflow.

The recommended original-image/template workflow remains uncropped at candidate C and keeps the completed-thumbnail protection mode. Motion Intro remains bundled with the LGPL FFmpeg runtime and does not require system FFmpeg on PATH.

## Live Composer (v0.4.1)

Live Composer adds a 1280×720 editing canvas with draggable, independently selectable role boxes (channel label, story label, EP badge, title, subtitle), live debounced typography controls, per-candidate A/B/C state, and Undo/Redo. Two simultaneous downscaled previews show 340px and 180px readability. Style cards are grouped in Tokyo Chill and Old Pop Lounge tabs and apply immediately to the active candidate. Controls include title size, outline, shadow, glow, line/letter spacing, alignment/anchor, colors, soft plate, gradient, and safe-zone overlay.

The Background Fit Engine analyzes title-area luminance/texture, dominant/accent colors, and subject-box overlap, then reports a readability score and can add a soft plate or gradient for contrast. The Image Bridge section below documents project-folder loading, subprocess integration, and result refresh.

## Image Bridge (v0.5.1)

In Live Composer, choose **프로젝트 폴더 열기** and select the image program's project directory. The bridge prefers `canvas_clean.png`, discovers the preview and all JSON sidecars, fills channel/title/subtitle/episode/story/style from `project_manifest.json`, applies palette effects, seeds protagonist/counterpart points and safe zones, and displays each asset's loaded/fallback state. If there is no clean canvas it picks a local image in that folder; existing legacy clean/reference/safe-zone filenames are still accepted. Without project files the ordinary image picker workflow is unchanged.

Supported JSON can be minimal or nested. Regions accept arrays `[x,y,width,height]`, objects with `bbox`/`box`/`rect`, or named `x,y,width,height`; values in 0–1 are normalized and mapped to source-image pixels for subjects or 1280×720 canvas pixels for text-safe zones and composition. Optional `canvas_size` / `image_size` lets pixel-coordinate schemas declare their source dimensions. Region roles `protagonist`/`main`/`lead` and `counterpart`/`partner` seed the manual subject selections. The manifest accepts `channel`, `title`, `subtitle`, `episode`, `story_type`, and `preferred_typography` (common snake/camel-case aliases also work). Palette accepts fill/stroke/highlight colors plus glow, shadow, and outline width, flat or nested under `colors`/`effects`.

The UI runs generation/edit in a worker thread, captures stdout/stderr and exit code, validates the returned canvas, and reloads the selected project after success. It keeps user-edited text/style/color/position settings wherever possible. A nonzero exit, timeout, invalid/missing canvas, or launch error restores the previous output files; missing optional sidecars produce warnings and retain prior metadata or local defaults. The default timeout is 600 seconds.

Configure the image application on Windows before launching YouTube Dynamic Thumbnail Studio:

```bat
set IMAGE_PROGRAM_EXE=C:\path\to\ImageProgram.exe
set IMAGE_PROJECT_ROOT=D:\image-projects
set IMAGE_BRIDGE_MODE=cli
set IMAGE_BRIDGE_TIMEOUT=600
```

`IMAGE_PROGRAM_EXE` is required for generate/edit. `IMAGE_PROJECT_ROOT` is the base used to resolve relative project paths (the GUI's folder picker normally supplies an absolute path). `IMAGE_BRIDGE_MODE` supports `cli` (default) and `json-stdin`. In CLI mode the program receives `--action generate|edit --project-dir <folder>`, the channel/story/title/subtitle arguments, optional `--prompt` or `--edit-instruction`, and `--options-json <JSON>`. In `json-stdin` mode it receives `--image-bridge` and a UTF-8 JSON request on stdin. Both modes must exit with code 0 and write a new valid `canvas_clean.png` in the project folder. The JSON request has protocol `youtubesum-image-bridge/1` and lists the expected output files.

The image program should return `canvas_clean.png`, `subject_boxes.json`, `safe_zones.json`, `palette.json`, `composition.json`, and `project_manifest.json` in that folder. The clean canvas is required; missing/invalid metadata sidecars are non-fatal and reported in the UI. Existing files are backed up during the call and restored on failure. Image program binaries are not bundled with YouTube Dynamic Thumbnail Studio.

Example workflow: open `examples/tokyo_chill_project`, set a prompt such as `rainy Tokyo station at night`, click **배경 생성**, review the captured result/log, then tweak the title in Live Composer. To edit the generated background, enter an edit instruction and click **배경 편집**. A successful image-program run automatically invokes the equivalent of **image에서 새로고침**.

Ready-to-open text-free sample projects with all seven assets are in `examples/tokyo_chill_project/` and `examples/old_pop_lounge_project/`. Regenerate their deterministic canvases with `py -3.10 scripts\create_sample_projects.py`. Each folder contains `canvas_clean.png`, `preview_reference.png`, five JSON sidecars, and is directly selectable in the project-folder dialog.

## Windows build

Use Windows x64 and Python 3.10. Install the pinned dependencies and prepare the pinned LGPL FFmpeg bundle:

```bat
py -3.10 -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_ffmpeg.ps1
py -3.10 -m PyInstaller --noconfirm --clean --workpath build\pyinstaller_v06 --distpath dist YouTubeDynamicThumbnailStudio.spec
```

The executable is `dist\YouTubeDynamicThumbnailStudio\YouTubeDynamicThumbnailStudio.exe` (keep the adjacent `_internal` folder when distributing). This folder-based build avoids one-file extraction delays and can be launched by double-clicking the EXE. No fonts or external FFmpeg executable are bundled/required; fonts come from Windows. Review `THIRD_PARTY_NOTICES.txt` before redistributing the FFmpeg-enabled build.

## Tests and real-image comparison

```bat
py -3.10 -m compileall -q app.py image_bridge.py thumbnail_engine.py layout_engine.py typography_engine.py typography editor
py -3.10 -m unittest discover -s tests -v
py -3.10 scripts\compare_tokyo_samples.py sample-1.png sample-2.png sample-3.png
dist\YouTubeDynamicThumbnailStudio\YouTubeDynamicThumbnailStudio.exe --self-test-project examples\tokyo_chill_project
dist\YouTubeDynamicThumbnailStudio\YouTubeDynamicThumbnailStudio.exe --self-test-editor examples\old_pop_lounge_project --report build\editor_report.json
py -3.10 scripts\v06_validation.py
```

The Tokyo comparison script saves before/A/B/C 340px contact sheets for three real images under `build\v04_tokyo_before_after`; the Old Pop comparison saves three under `build\v041_oldpop_before_after`. Both leave source images untouched. Automated tests cover Japanese line-break snapshots, mixed-script font fallback, background-fit scoring, project sidecars, Live Composer controls/drag/history/independent candidates, CLI and JSON-stdin bridge requests, output rollback/timeout/partial-sidecar handling, GUI auto-refresh, candidate distinction, and Motion rendering. For packaged project-folder smoke tests, run `YouTubeDynamicThumbnailStudio.exe --self-test-project examples\tokyo_chill_project` (or `old_pop_lounge_project`). Generated preview artifacts under `build/` are local QA outputs and are ignored by Git.
