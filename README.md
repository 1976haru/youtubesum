# YouTube Dynamic Thumbnail Studio v0.5-dev

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

Candidate layout searches alternate anchors to avoid supplied subject and safe-zone boxes. If an input image's directory contains `cleaned_canvas.png`, it takes precedence as the clean base; `safe_zone.json` and `subject_boxes.json` provide normalized or pixel regions. `reference_thumb.png` is discovered for comparison only and is never composited into the new thumbnail. Missing or invalid sidecars fall back to the existing local image workflow.

The recommended original-image/template workflow remains uncropped at candidate C and keeps the completed-thumbnail protection mode. Motion Intro remains bundled with the LGPL FFmpeg runtime and does not require system FFmpeg on PATH.

## Live Composer (v0.4.1)

Live Composer adds a 1280×720 editing canvas with draggable, independently selectable role boxes (channel label, story label, EP badge, title, subtitle), live debounced typography controls, per-candidate A/B/C state, and Undo/Redo. Two simultaneous downscaled previews show 340px and 180px readability. Style cards are grouped in Tokyo Chill and Old Pop Lounge tabs and apply immediately to the active candidate. Controls include title size, outline, shadow, glow, line/letter spacing, alignment/anchor, colors, soft plate, gradient, and safe-zone overlay.

The Background Fit Engine analyzes title-area luminance/texture, dominant/accent colors, and subject-box overlap, then reports a readability score and can add a soft plate or gradient for contrast. The Image Bridge section below documents project-folder loading, sidecar refresh, and future image-program launcher hooks.

## Image Bridge (v0.5)

In Live Composer, choose **프로젝트 폴더 열기** and select the image program's project directory. The bridge prefers `canvas_clean.png`, discovers the preview and all JSON sidecars, fills channel/title/subtitle/episode/story/style from `project_manifest.json`, applies palette effects, seeds protagonist/counterpart points and safe zones, and displays each asset's loaded/fallback state. If there is no clean canvas it picks a local image in that folder; existing legacy clean/reference/safe-zone filenames are still accepted. Without project files the ordinary image picker workflow is unchanged.

Supported JSON can be minimal or nested. Regions accept arrays `[x,y,width,height]`, objects with `bbox`/`box`/`rect`, or named `x,y,width,height`; values in 0–1 are normalized and mapped to source-image pixels for subjects or 1280×720 canvas pixels for text-safe zones and composition. Optional `canvas_size` / `image_size` lets pixel-coordinate schemas declare their source dimensions. Region roles `protagonist`/`main`/`lead` and `counterpart`/`partner` seed the manual subject selections. The manifest accepts `channel`, `title`, `subtitle`, `episode`, `story_type`, and `preferred_typography` (common snake/camel-case aliases also work). Palette accepts fill/stroke/highlight colors plus glow, shadow, and outline width, flat or nested under `colors`/`effects`.

**image에서 새로고침** re-reads the currently open folder and rebuilds the background/sidecar analysis. Imported palette values update only while their controls still match the prior imported values; user-edited colors, typography and text stay in place. Composition sidecar positions update blocks that have not been moved by the user. **배경 생성** and **배경 편집** route through `image_bridge.launch_generate()` / `launch_edit()`; set `IMAGE_PROGRAM_EXE` to an image-program executable to enable its future `--generate` / `--edit --project <folder>` command contract. With no configured executable, the UI explains that the integration is not active yet.

Ready-to-open text-free sample projects with all seven assets are in `examples/tokyo_chill_project/` and `examples/old_pop_lounge_project/`. Regenerate their deterministic canvases with `py -3.10 scripts\create_sample_projects.py`. Each folder contains `canvas_clean.png`, `preview_reference.png`, five JSON sidecars, and is directly selectable in the project-folder dialog.

## Windows build

Use Windows x64 and Python 3.10. Install the pinned dependencies and prepare the pinned LGPL FFmpeg bundle:

```bat
py -3.10 -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_ffmpeg.ps1
py -3.10 -m PyInstaller --noconfirm --clean --workpath build\pyinstaller_v05 --distpath dist YouTubeDynamicThumbnailStudio.spec
```

The executable is `dist\YouTubeDynamicThumbnailStudio\YouTubeDynamicThumbnailStudio.exe` (keep the adjacent `_internal` folder when distributing). This folder-based build avoids one-file extraction delays and can be launched by double-clicking the EXE. No fonts or external FFmpeg executable are bundled/required; fonts come from Windows. Review `THIRD_PARTY_NOTICES.txt` before redistributing the FFmpeg-enabled build.

## Tests and real-image comparison

```bat
py -3.10 -m compileall -q app.py image_bridge.py thumbnail_engine.py layout_engine.py typography_engine.py typography
py -3.10 -m unittest discover -s tests -v
py -3.10 scripts\compare_tokyo_samples.py sample-1.png sample-2.png sample-3.png
dist\YouTubeDynamicThumbnailStudio\YouTubeDynamicThumbnailStudio.exe --self-test-project examples\tokyo_chill_project
```

The Tokyo comparison script saves before/A/B/C 340px contact sheets for three real images under `build\v04_tokyo_before_after`; the Old Pop comparison saves three under `build\v041_oldpop_before_after`. Both leave source images untouched. Automated tests cover Japanese line-break snapshots, mixed-script font fallback, background-fit scoring, project sidecars, Live Composer controls/drag/history/independent candidates, candidate distinction, and Motion rendering. Generated preview artifacts under `build/` are local QA outputs and are ignored by Git.
