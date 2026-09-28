# YouTube Dynamic Thumbnail Studio v0.3

칠리랩(Tokyo Chill)과 OLD POP LOUNGE용 Windows 데스크톱 도구입니다. 원본 이미지를 수정하지 않고 A/B/C 후보를 미리 본 뒤 개별 또는 전체 저장할 수 있으며, 기존 Motion Intro 기능도 유지합니다.

## v0.3 기능

- A PERSON: 로컬 얼굴 검출이 충분히 확실할 때 모든 얼굴과 안전 여백을 보존한 인물 중심 구도
- B EMOTION/MEMORY: 얼굴 관계와 시선이 놓일 여백을 넓게 남긴 구도
- C STORY/SCENERY: 원본 전체와 환경 맥락을 보존한 구도
- 얼굴이 없거나 검출 신뢰가 낮으면 원본 전체를 보존하는 안전 구도로 폴백
- A/B/C 3개를 나란히 미리보기, `이 후보만 저장`, `3개 모두 저장`, `결과 폴더 열기`
- 한글/일본어/공백 이미지 경로 지원, traceback을 `logs/error.log`에 기록
- Motion은 FFmpeg H.264 인코딩을 사용하며, FFmpeg가 없으면 설치와 PATH 설정을 안내

얼굴 검출은 추가 모델 다운로드 없이 OpenCV 내장 Haar cascade를 사용합니다. OpenCV 4.5 이상은 Apache-2.0 라이선스입니다. 검출은 선택적이며 실패해도 전체 원본 안전 구도로 동작합니다.

## Windows EXE 실행

`dist\YouTubeDynamicThumbnailStudio.exe`를 더블클릭합니다. PowerShell이나 Python은 필요하지 않습니다. EXE는 실행 시 현재 작업 폴더에 의존하지 않습니다. 오류 로그는 EXE 옆 `logs\error.log`에 생성되며, 해당 위치에 쓸 수 없으면 `%USERPROFILE%\YouTubeDynamicThumbnailStudio\logs\error.log`를 사용합니다.

Motion을 만들려면 FFmpeg를 설치하고 `ffmpeg`가 PATH에서 검색되게 해야 합니다.

## 재현 가능한 Windows 빌드

Windows x64, Python 3.10에서 저장소 루트를 연 뒤 다음을 실행합니다.

```bat
py -3.10 -m pip install -r requirements-build.txt
py -3.10 -m PyInstaller --noconfirm --clean YouTubeDynamicThumbnailStudio.spec
```

또는 `build_windows.bat`를 더블클릭합니다. 산출물은 `dist\YouTubeDynamicThumbnailStudio.exe`입니다. `build/`, `dist/`, 로그와 생성 미디어는 Git에서 제외됩니다.

## 검증 명령과 2026-09-28 결과

```bat
py -m compileall -q app.py thumbnail_engine.py motion_engine.py tests
py -c "import app, thumbnail_engine, motion_engine"
py -m unittest discover -s tests -v
py -3.10 -m PyInstaller --noconfirm --clean YouTubeDynamicThumbnailStudio.spec
```

검증 결과:

- compile/import: PASS
- ASCII 입력/출력 경로 후보 생성: PASS
- `한글 입력 東京 space` → `결과 保存 폴더`: PASS
- JPG 정확히 3개 + manifest 1개, 모든 JPG 1280×720: PASS
- 0명, 1명, 2명 얼굴 경로와 저신뢰 폴백: PASS
- 한글/일본어/공백 경로 Motion 출력: PASS
- EXE를 `C:\Windows` 작업 디렉터리에서 실행, v0.3 GUI 표시: PASS
- EXE 자체 Unicode 경로 후보 생성: PASS
- 콘솔 없는 windowed EXE: PASS (`console=False`, `runw.exe`)

검증 빌드 SHA-256: `8150386CB67E4B91C1321E35065C37F506983F206B976366695FB18F53CFBB1A`

## Python 개발 실행

```bat
py -m pip install -r requirements.txt
py app.py
```

생성형 AI는 사용하지 않으며 얼굴, 의상, 텍스트를 다시 그리지 않습니다.
