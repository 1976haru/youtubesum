# YouTube Dynamic Thumbnail Studio v0.3.1

Windows 데스크톱 도구입니다. 완성 썸네일의 글자·로고·장식 요소를 보호하는 모드가 기본이며, A/B/C를 미리 본 뒤 선택 저장할 수 있습니다. 기존 Motion Intro도 앱에 포함된 인코더로 만듭니다.

## 썸네일 입력과 A/B/C

- 기본 `완성 썸네일(글자 보호)`: 원본 픽셀의 어느 영역도 잘라내거나 이동시키지 않습니다. A/B는 클릭한 인물 위치를 중심으로 국소 선명도·톤을 강조하고, C는 전체 구성을 그대로 유지합니다. 입력이 이미 1280×720이면 C 픽셀 배열도 동일합니다.
- `텍스트 없는 원본 이미지`: 이전의 얼굴 검출 기반 안전 크롭을 사용할 수 있습니다.
- `주인공 직접 지정` 및 `상대 인물 지정`: 원본 전체가 보이는 선택창에서 얼굴/몸 위치를 클릭합니다. 선택 좌표를 0..1 정규화 값으로 저장하며, 원본이 바뀌면 자동 해제합니다. 수동 지정 주인공은 얼굴 자동 감지 결과보다 우선합니다. 빠른 선택 `자동 / 왼쪽 인물 / 오른쪽 인물 / 두 사람`도 유지됩니다.
- 화면에서 현재 입력 모드와 지정 상태를 보여주고, 완성 썸네일 모드에는 `글자/로고 보호 ON · 크롭 금지`를 표시합니다.
- A PERSON은 주인공에 좁게 초점을 맞춥니다. B EMOTION/MEMORY는 지정한 두 인물 또는 한 주인공 주변을 더 넓게 강조합니다. C STORY/SCENERY는 전체 원본 기준입니다.
- A/B/C 미리보기, 개별 저장, 전체 저장, 결과 폴더 열기를 지원합니다. 원본 파일은 수정하지 않습니다.

완성 썸네일에는 Gaussian blur/dim을 적용하지 않습니다. 얼굴 검출이 옆얼굴을 놓쳐도 사용자가 위치를 지정할 수 있고, 성별은 추정하지 않습니다.

## Windows 실행

`dist\YouTubeDynamicThumbnailStudio.exe`를 더블클릭합니다. Python, PowerShell, 외부 `ffmpeg` PATH는 일반 실행에 필요하지 않습니다. EXE는 FFmpeg LGPL 공유 빌드와 필요한 DLL을 함께 포함합니다. Motion H.264 인코더는 Windows Media Foundation(`h264_mf`)입니다.

앱의 `오픈소스 라이선스` 버튼에서 고지와 LGPLv3/GPLv3 문서를 확인할 수 있습니다. FFmpeg 대응 소스와 빌드 구성 링크는 [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)에 있습니다. LGPL 조건에 따라 호환 FFmpeg 실행 파일과 DLL을 `ydts_ffmpeg` 이름의 폴더에 EXE 옆에 두면 내장본보다 우선 사용합니다. EXE를 공개/재배포할 때는 고지·라이선스·소스 링크를 함께 제공하세요. 번들 바이너리의 버전, URL, SHA-256은 `scripts/prepare_ffmpeg.ps1`에 고정되어 있습니다. 앱은 실행 중 바이너리를 다운로드하지 않습니다.

FFmpeg LGPL 빌드 구성은 GPL 전용 x264/x265를 포함하지 않습니다. 이 빌드는 LGPLv3로 표시되며 permissive/LGPL 계열의 여러 추가 코덱 라이브러리를 포함합니다. 정확한 configure 결과는 `ffmpeg -version`에 표시됩니다. Windows H.264 인코더는 OS Media Foundation에 의존하므로 Windows 10/11에서 검증합니다.

## 재현 가능한 빌드

Windows x64와 Python 3.10에서 저장소 루트를 열고 다음을 실행합니다. 첫 단계는 빌드 시점에만 고정 URL의 LGPL FFmpeg 패키지를 받고 SHA-256을 확인합니다. 앱 실행 중에는 네트워크를 사용하지 않습니다.

```bat
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_ffmpeg.ps1
py -3.10 -m pip install -r requirements-build.txt
py -3.10 -m PyInstaller --noconfirm --clean YouTubeDynamicThumbnailStudio.spec
```

또는 `build_windows.bat`를 더블클릭합니다. 산출물은 `dist\YouTubeDynamicThumbnailStudio.exe`입니다. `build/`, `dist/`, `vendor/`, 로그, 테스트 미디어는 Git에서 제외됩니다.

번들 FFmpeg: `n9.0.2-3-ga5923073bf`, LGPLv3 shared, Windows x64. 아카이브 SHA-256: `1DB36DC94E379E3A7E974E995E278DA05D46C14EBB6DEB7DA11BC8AD1A4A3E3E`.

## 검증 결과 (2026-09-28)

명령:

```bat
py -m compileall -q app.py thumbnail_engine.py motion_engine.py tests
py -c "import app, thumbnail_engine, motion_engine"
py -m unittest discover -s tests -v
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\prepare_ffmpeg.ps1
py -3.10 -m PyInstaller --noconfirm --clean YouTubeDynamicThumbnailStudio.spec
```

자동 검증은 11건 PASS입니다:

- ASCII 및 한글/일본어/공백 경로: 정확히 JPG 3개와 manifest 1개, 후보 모두 1280×720
- 완성 모드: 크롭 함수 호출 금지, 1280×720 C의 입력 픽셀 완전 동일, A/B 국소 강조
- 원본 모드: 안전 크롭 경로, 0/1/2인물 감지 시나리오
- 정규화 수동 위치가 리사이즈 후에도 적용되고 얼굴 감지 결과를 덮어씀
- 비16:9 원본을 레터박스 배치할 때 클릭 지점을 원본 전체 비율에 맞게 변환
- Tk 클릭 이벤트, 마커 표시, 상대 지정, 새 입력 경로 선택 시 수동 점 해제
- 한글/일본어 경로 Motion MP4 생성 및 LGPL 내장 FFmpeg로 출력 재생성/디코드
- FFmpeg가 시스템 PATH에서 검색되지 않는 상태에서도 Motion 생성 성공

요청된 실제 이미지 3건(도쿄칠 2인 측면 주인공, 도쿄칠 1인, OLD POP LOUNGE)은 저장소/작업 폴더에서 원본을 찾지 못했습니다. 그래서 실제 이미지의 모든 글자 가시성, 주인공 강조, 상대와의 관계는 자동 합성 검증으로 대체하지 않았으며 실제 시각 검증 상태는 미수행입니다. 현재 자동 fixture의 화면은 색상 격자와 타이틀/로고 위치를 모사한 테스트 이미지입니다.

## 개발 실행

```bat
py -m pip install -r requirements.txt
py app.py
```

생성형 AI는 사용하지 않습니다.
