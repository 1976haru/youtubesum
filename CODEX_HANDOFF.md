# CODEX HANDOFF — YouTube Dynamic Thumbnail Studio v0.2

## 절대 원칙
- 기존 `1976haru/wave` 수정 금지. 독립 앱으로 검증한다.
- 사용자 승인 없이 생성형 얼굴 재생성 기능을 기본값으로 넣지 않는다.
- 상업적 YouTube 사용을 전제로 라이선스를 확인한다.
- 기능 추가보다 실제 칠리랩 3장 + 시니어 3장 품질 검증을 우선한다.

## 현재 완료
- A/B/C 1280x720 후보 생성
- 채널별 후보 의미 분리
- 테스트 CSV 저장/누적 요약
- v0.1 Motion Intro 유지

## 다음 작업 순서
1. Windows에서 `python app.py` 실실행 검증
2. 6개 실제 레퍼런스로 A/B/C 및 Motion 렌더
3. contact sheet 생성 후 사람 검수. 자동 PASS 금지
4. 인물 위치가 다른 이미지에서 단순 중앙 crop의 한계를 기록
5. 그 다음에만 subject-aware crop을 추가. 우선 OpenCV face/person detector 또는 허용 라이선스 모델 검토
6. Depth Anything V2 Small(Apache-2.0) 기반 2.5D는 별도 feature flag로 추가
7. SAM2는 설치/VRAM/패키징 비용을 측정한 뒤 선택 기능으로 추가
8. RIFE도 실제 이득이 확인될 때만 옵션화
9. PyInstaller Windows EXE는 기능/품질 검증 후 마지막에 수행

## 테스트 기준
- 원본 인물 얼굴/의상/텍스트가 재생성되거나 왜곡되지 않을 것
- A/B/C가 육안으로 구별될 것
- 후보 파일 1280×720 JPG
- Motion 1920×1080 30fps, H.264/yuv420p when FFmpeg exists
- 앱 실패 시 traceback을 숨기지 말고 로그 파일을 남길 것
- 기존 v0.2 기능 회귀 금지

## 금지
- 테스트 없이 '완료' 보고
- Base/Large/Giant Depth Anything V2 모델을 상업용 기본 모델로 채택
- YouTube API가 자동으로 Dynamic Thumbnail을 업로드/지정한다고 가정
