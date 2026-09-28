# YouTube Dynamic Thumbnail Studio v0.2

칠리랩(Tokyo Chill)과 OLD POP LOUNGE용 **3후보 썸네일 + Motion Intro** 실험 도구입니다.

## v0.2 핵심
- 같은 원본에서 역할이 다른 A/B/C 3후보 JPG 생성 (1280×720)
- Tokyo Chill: A 인물 / B 감정 / C 스토리
- OLD POP LOUNGE: A 인물 / B 추억 / C 풍경
- YouTube 테스트 결과를 CSV로 누적 기록
- 기존 v0.1 Motion Intro 유지: Rain / Neon / First Snow / Cafe / Autumn
- 생성형 AI로 얼굴을 다시 그리지 않음

## 실행
1. Python 3.11+ 설치
2. `pip install -r requirements.txt`
3. H.264 최종 인코딩을 위해 FFmpeg 권장
4. `python app.py`

## 중요
v0.2의 A/B/C는 '색만 다른 3장'이 아니라 프레이밍과 역할을 다르게 만드는 비생성형 기준선입니다. 인물 자동 검출/재배치와 Depth 기반 2.5D는 다음 단계에서 실제 이미지 6장 검증 후 추가합니다.
