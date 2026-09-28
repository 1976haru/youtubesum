# YouTube Dynamic Thumbnail Studio v0.3.3

## Typography Engine

v0.3.3 separates title styling from candidate composition. The `layout_engine.py` module places title and supporting information for A/B/C; `typography_engine.py` owns type presets, system-font selection, contrast, line breaking, emphasis, outline, shadow, and glow.

The Tokyo Chill channel offers CINEMATIC CHILL, JAPANESE IMPACT, ROMANTIC NEON, EMOTIONAL MONO, STORY CARD, and NIGHT DRIVE. OLD POP LOUNGE offers SENIOR CLASSIC, SENIOR EMOTIONAL, FIRST SNOW, AUTUMN MEMORY, CAFE WARM, and CHRISTMAS GLOW.

Titles can be auto-wrapped to two lines, can emphasize one supplied or automatically selected keyword, and support Auto/Small/Medium/Large sizing. Contrast-aware light/dark ink is selected from the title area. Channel, story, and episode metadata stay in a small top rail. A puts the largest impact near the bottom/left, B uses a centered relationship treatment, and C uses a quieter upper-left treatment that preserves scenery. Tokyo styles use stronger color and glow; OLD POP styles are sized for comfortable reading.

Typography uses installed system fonts only. No font files are included in the repository or executable. On Windows, Japanese candidates include Yu Gothic UI, Yu Gothic, Meiryo, Noto Sans JP, and BIZ UDPGothic; Korean candidates include Malgun Gothic and Noto Sans KR; English candidates include Segoe UI, Arial, and Noto Sans. The exact available fallback depends on the installed OS fonts.

## Thumbnail modes and Motion

The recommended `Original image + template` mode keeps the source image uncropped and creates three deliberately different A/B/C compositions. Existing completed-thumbnail protection and manual protagonist/counterpart selection remain available. The completed-thumbnail mode preserves baked-in text/logo and does not crop. Motion Intro continues to use the bundled FFmpeg build rather than requiring FFmpeg on PATH.

## Windows build and tests

Use Windows x64 and Python 3.10. Prepare the pinned LGPL FFmpeg bundle once, then build:

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_ffmpeg.ps1
py -3.10 -m pip install -r requirements-build.txt
py -3.10 -m PyInstaller --noconfirm --clean YouTubeDynamicThumbnailStudio.spec
```

The standalone executable is `dist\YouTubeDynamicThumbnailStudio.exe`. Double-click it to launch; Python, PowerShell, and a system FFmpeg installation are not required at runtime. The bundled FFmpeg notices and replacement instructions are in `THIRD_PARTY_NOTICES.txt`.

Run the automated suite with:

```bat
py -3.10 -m compileall -q app.py thumbnail_engine.py layout_engine.py typography_engine.py motion_engine.py tests
py -3.10 -m unittest discover -s tests -v
```

Visual preview samples are synthetic fixtures for typography/layout QA, not channel photography. Final color and placement review on representative production images is still recommended.
