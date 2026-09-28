# Codex implementation brief — v0.3 Windows Preview Build

Repository: 1976haru/youtubesum
Working branch: v0.3-dev
Do not rewrite the project from scratch.

## Confirmed baseline
- v0.2.1 Unicode-safe Windows image paths are merged to main.
- Real Tokyo Chill input successfully produced A/B/C and manifest.
- Current A/B/C output is technically valid but visually too similar: mostly different crop/zoom.
- User requires normal Windows double-click operation, not PowerShell.

## P0 — Windows executable
1. Preserve Unicode-safe I/O.
2. Make a reproducible PyInstaller Windows build.
3. Output dist/YouTubeDynamicThumbnailStudio.exe.
4. GUI must start without console.
5. App must work when launched from an arbitrary working directory.
6. Add visible app version v0.3.
7. Add UI error handling and logs/error.log with traceback.
8. Add “결과 폴더 열기”.
9. Verify Korean/Japanese/spaces in input and output paths.
10. Do not commit build/, dist/, __pycache__, venv, or generated media.

## P1 — meaningful A/B/C
Current crop-only candidates are insufficient.
A PERSON: prioritize detected people/faces and relationship readability.
B EMOTION/MEMORY: preserve gaze/negative space/emotional relation; do not simply use a second zoom.
C STORY/SCENERY: preserve environmental context and story-setting.
Support 0, 1, 2+ people. Never cut faces at frame edges.
If automatic analysis confidence is low, fall back safely to original 16:9 framing.
Do not add generative AI in this milestone.

Use lightweight local detection first. Research an appropriate permissive library/model before adding a heavy dependency. Keep detection optional/fallback-safe.

## P2 — Preview UX
Show A/B/C thumbnails side by side before save.
Each card shows strategy name.
Allow “이 후보만 저장” and “3개 모두 저장”.
Keep original image untouched.

## P3 — Motion
Keep existing motion feature working.
Do not let packaging changes regress Unicode paths.
Detect ffmpeg and show an actionable Korean error if unavailable.

## Validation gate
- python compile/import checks PASS
- candidate generation on ASCII path PASS
- candidate generation on Korean/Japanese path PASS
- exactly 3 JPG + manifest produced
- 1280x720 for all candidates
- EXE launches by double click
- EXE creates candidates from Korean/Japanese path
- no console required
- no generated test media committed
- document exact build command and test evidence in README

Commit in small logical commits. Do not push to main. Push v0.3-dev only after validation and report commit SHA plus PASS/FAIL table.
