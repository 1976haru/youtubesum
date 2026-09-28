# YouTube Dynamic Thumbnail Studio v0.4

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

## Windows build

Use Windows x64 and Python 3.10. Install the pinned dependencies and prepare the pinned LGPL FFmpeg bundle:

```bat
py -3.10 -m pip install -r requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_ffmpeg.ps1
py -3.10 -m PyInstaller --noconfirm --clean YouTubeDynamicThumbnailStudio.spec
```

The executable is `dist\YouTubeDynamicThumbnailStudio\YouTubeDynamicThumbnailStudio.exe` (keep the adjacent `_internal` folder when distributing). This folder-based build avoids one-file extraction delays and can be launched by double-clicking the EXE. No fonts or external FFmpeg executable are bundled/required; fonts come from Windows. Review `THIRD_PARTY_NOTICES.txt` before redistributing the FFmpeg-enabled build.

## Tests and real-image comparison

```bat
py -3.10 -m compileall -q app.py thumbnail_engine.py layout_engine.py typography_engine.py typography
py -3.10 -m unittest discover -s tests -v
py -3.10 scripts\compare_tokyo_samples.py sample-1.png sample-2.png sample-3.png
```

The comparison script saves a before/A/B/C 340px contact sheet for each of three real text-free Tokyo Chill images under `build\v04_tokyo_before_after`. It does not modify or copy source images. Automated snapshots include 20 Japanese titles and mixed-script/font fallback checks. Generated preview artifacts under `build/` are local QA outputs and are ignored by Git.
