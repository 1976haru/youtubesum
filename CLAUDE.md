# CLAUDE.md — YouTube Dynamic Thumbnail Studio

## Working branch
Work only on `v0.6-pro-editor-dev`.
Do not modify, merge, or push to `main`.

## Primary implementation brief
Read `CLAUDE_V0.6_PRO_EDITOR_INSTRUCTIONS.md` before making changes.
Treat that file as the current product/acceptance specification.

## Current architecture to preserve
- Skia/HarfBuzz professional typography rendering.
- Japanese line-breaking and CJK font fallback.
- A/B/C candidate workflow.
- Live Composer / Background Fit work from v0.4.1.
- Image Bridge work from v0.5/v0.5.1.
- Motion Intro and bundled FFmpeg behavior.
- Korean/Japanese/space-containing Windows path support.

## Development rules
- Inspect the existing implementation before changing architecture.
- Reuse existing modules rather than duplicating logic.
- Make small, logical commits.
- Keep generated media, build/, dist/, logs/, caches, and model weights out of git.
- Do not bundle proprietary font files.
- Run `git diff --check` before committing.
- Keep the working tree clean at handoff.
- Push only `v0.6-pro-editor-dev`.

## Validation requirements
At minimum:
- full Python test suite PASS
- compile/import PASS
- Japanese/Korean/English mixed text PASS
- direct canvas drag/resize/rotate PASS
- undo/redo PASS
- live typography update PASS
- 340px and 180px previews PASS
- project save/reopen PASS
- Image Bridge regression PASS
- Motion regression PASS
- Windows packaged GUI smoke test PASS

## Handoff report
Report:
- final commit SHA
- package/EXE path
- SHA-256
- PASS/FAIL table
- actual Tokyo Chill and OLD POP screenshots
- live-editor timing measurements
- remaining limitations

Do not claim a real AI generation/edit PASS unless it was actually run with the real image backend.
