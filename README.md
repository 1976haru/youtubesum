# YouTube Dynamic Thumbnail Studio v0.3.2

## v0.3.2: 권장 원본 이미지 + 템플릿 작업 흐름

기본 작업 모드는 `원본 이미지 + 템플릿 (권장)`입니다. 텍스트가 없는 원본 사진에서 후보를 만들고, 채널명·스토리 유형·EP·제목·부제를 새 텍스트 레이어로 각각 렌더링합니다. 참고용 완성 썸네일은 비교 창으로만 열리며 출력 이미지 레이어나 크롭 입력으로 사용하지 않습니다. 완성 썸네일을 선택하면 기존 `완성 썸네일(글자 보호)` 동작(글자/로고 보존, 크롭 금지, C는 원본 구도)이 유지됩니다.

- A PERSON은 클릭 지정한 주인공에 더 타이트한 구도와 하단 제목 배치를 사용합니다. 남자 이야기에서 남자 얼굴을 직접 선택하면 얼굴 감지 순서/성별 추정에 의존하지 않고 그 좌표를 우선합니다.
- B EMOTION/MEMORY는 주인공과 상대 인물 또는 감지된 인물의 관계를 함께 담는 중간 구도와 대안 텍스트 배치를 사용합니다.
- C STORY/SCENERY는 장면 전체를 크롭하지 않고 유지하며 스토리 텍스트를 상단에 배치합니다.
- 크롭 경계가 감지된 얼굴을 가로지르면 전체 원본 구도로 안전하게 되돌립니다. 사람 감지가 빗나간 경우에는 원본에서 주인공/상대를 직접 클릭해 지정할 수 있습니다.
- Tokyo Chill은 고대비 일본어/한국어/영어 타이포그래피, OLD POP LOUNGE는 더 차분한 색과 큰 글자를 사용합니다. Windows 설치 글꼴을 우선 사용하고 시스템 대체 글꼴을 지원합니다. 글꼴 파일은 앱에 재배포하지 않습니다.
- A/B/C는 나란히 340×191 미리보기로 표시합니다. 다운샘플 RGB 지표로 A-B/A-C/B-C 차이를 표시하고 세 쌍이 모두 94% 이상 유사하면 차이 부족 경고를 표시합니다. 경고 후에도 저장할 수 있습니다.

인증 테스트는 `py -m unittest discover -s tests -v`입니다. 템플릿·크롭·수동 주인공·다양성 계산은 합성 fixture로 검증합니다. 저장소에는 실제 채널 썸네일이 없어 최종 실사 가독성과 채널별 미감은 배포 전에 실제 이미지로 확인해야 합니다.

Windows 데스크톱 도구입니다. 텍스트 없는 원본에 템플릿 글자를 새로 렌더링해 서로 다른 A/B/C 후보를 만들고, 완성 썸네일 보호 모드와 기존 Motion Intro도 제공합니다.

## 썸네일 입력과 A/B/C

- 기본 `원본 이미지 + 템플릿 (권장)`: 텍스트 없는 사진만 프레임으로 사용하고, 제목 등 텍스트는 새 별도 레이어로 렌더링합니다. 선택적인 참고 완성 썸네일은 보기만 하며 출력 레이어/크롭 입력으로 사용하지 않습니다.
- `완성 썸네일(글자 보호)`: 기존 v0.3.1 보호 동작입니다. 원본의 글자/로고를 보존하고 크롭하지 않으며, C는 원본 구도 그대로, A/B는 안전한 국소 강조만 합니다. 세 후보가 비슷하면 유사도와 차이 부족 경고를 표시합니다.
- `텍스트 없는 원본 이미지`: 편집 텍스트 템플릿 없이 이전 얼굴 검출 기반 크롭을 사용할 수 있습니다.
- `주인공 직접 지정` 및 `상대 인물 지정`: 원본 전체가 보이는 선택창에서 얼굴/몸 위치를 클릭합니다. 선택 좌표를 0..1 정규화 값으로 저장하며, 원본이 바뀌면 자동 해제합니다. 수동 지정 주인공은 얼굴 자동 감지 결과보다 우선합니다. 빠른 선택 `자동 / 왼쪽 인물 / 오른쪽 인물 / 두 사람`도 유지됩니다.
- 화면에서 현재 입력 모드와 지정 상태를 보여주고, 완성 썸네일 모드에는 `글자/로고 보호 ON · 크롭 금지`를 표시합니다.
- 템플릿 모드 A PERSON은 클릭 지정 주인공 중심 타이트 프레임, B EMOTION/MEMORY는 주인공+상대 관계의 중간 프레임, C STORY/SCENERY는 환경 전체 프레임입니다. A/B/C는 서로 다른 글자 배치까지 사용합니다. 감지된 얼굴을 자르는 크롭은 전체 원본 프레임으로 되돌립니다.
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

자동 검증은 14건 PASS입니다:

- ASCII 및 한글/일본어/공백 경로: 정확히 JPG 3개와 manifest 1개, 후보 모두 1280×720
- 완성 모드: 크롭 함수 호출 금지, 1280×720 C의 입력 픽셀 완전 동일, A/B 국소 강조
- 원본 모드: 안전 크롭 경로, 0/1/2인물 감지 시나리오
- 정규화 수동 위치가 리사이즈 후에도 적용되고 얼굴 감지 결과를 덮어씀
- 비16:9 원본을 레터박스 배치할 때 클릭 지점을 원본 전체 비율에 맞게 변환
- Tk 클릭 이벤트, 마커 표시, 상대 지정, 새 입력 경로 선택 시 수동 점 해제
- 한글/일본어 경로 Motion MP4 생성 및 LGPL 내장 FFmpeg로 출력 재생성/디코드
- FFmpeg가 시스템 PATH에서 검색되지 않는 상태에서도 Motion 생성 성공
- 템플릿 모드 Tokyo Chill/OLD POP의 1280×720 세 후보, A/B/C 구도 폭 및 340×191 시각 차이, 한국어·일본어 혼합 텍스트 렌더링
- 남자 주인공 직접 지정 시 A가 선택 좌측 인물로 프레이밍되고 B가 양쪽 얼굴을 포함하는지 확인
- 거의 동일한 합성 후보 세트에서 다양성 경고 지표 검증

요청된 실제 이미지 3건(도쿄칠 2인 측면 주인공, 도쿄칠 1인, OLD POP LOUNGE)은 저장소/작업 폴더에서 원본을 찾지 못했습니다. 그래서 실제 이미지의 모든 글자 가시성, 주인공 강조, 상대와의 관계는 자동 합성 검증으로 대체하지 않았으며 실제 시각 검증 상태는 미수행입니다. 현재 자동 fixture의 화면은 색상 격자와 타이틀/로고 위치를 모사한 테스트 이미지입니다.

## 개발 실행

```bat
py -m pip install -r requirements.txt
py app.py
```

생성형 AI는 사용하지 않습니다.
