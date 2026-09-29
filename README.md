# YouTube Dynamic Thumbnail Studio v0.5.1-dev

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
py -3.10 -m PyInstaller --noconfirm --clean --workpath build\pyinstaller_v051 --distpath dist YouTubeDynamicThumbnailStudio.spec
```

The executable is `dist\YouTubeDynamicThumbnailStudio\YouTubeDynamicThumbnailStudio.exe` (keep the adjacent `_internal` folder when distributing). This folder-based build avoids one-file extraction delays and can be launched by double-clicking the EXE. No fonts or external FFmpeg executable are bundled/required; fonts come from Windows. Review `THIRD_PARTY_NOTICES.txt` before redistributing the FFmpeg-enabled build.

## Tests and real-image comparison

```bat
py -3.10 -m compileall -q app.py image_bridge.py thumbnail_engine.py layout_engine.py typography_engine.py typography
py -3.10 -m unittest discover -s tests -v
py -3.10 scripts\compare_tokyo_samples.py sample-1.png sample-2.png sample-3.png
dist\YouTubeDynamicThumbnailStudio\YouTubeDynamicThumbnailStudio.exe --self-test-project examples\tokyo_chill_project
```

The Tokyo comparison script saves before/A/B/C 340px contact sheets for three real images under `build\v04_tokyo_before_after`; the Old Pop comparison saves three under `build\v041_oldpop_before_after`. Both leave source images untouched. Automated tests cover Japanese line-break snapshots, mixed-script font fallback, background-fit scoring, project sidecars, Live Composer controls/drag/history/independent candidates, CLI and JSON-stdin bridge requests, output rollback/timeout/partial-sidecar handling, GUI auto-refresh, candidate distinction, and Motion rendering. For packaged project-folder smoke tests, run `YouTubeDynamicThumbnailStudio.exe --self-test-project examples\tokyo_chill_project` (or `old_pop_lounge_project`). Generated preview artifacts under `build/` are local QA outputs and are ignored by Git.
