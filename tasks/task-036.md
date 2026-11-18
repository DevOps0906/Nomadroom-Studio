# task-036 예능형 렌더러 (로컬 워커)

| 항목 | 내용 |
|---|---|
| 웨이브 | W6 |
| 선행 | task-035 |
| 위험도 | 높음 |
| 보안 영향 | 새 자산 의존성(글꼴 라이선스 Q9) · 워커 파일 경로 보안 |
| 담당 | builder + tester |
| 근거 | `docs/research/variety-shorts-zip-analysis.md#2`~`#4`, `docs/05_DATA_MODEL.md#예능형-spec`, `docs/adr/0003-production-render-worker.md`, `docs/01_PRD.md#7` Q9 |
| 쓰기 허용 | `apps/worker/production/variety/**`, `apps/worker/production/fonts/**`·`licenses/**`(라이선스 통과 글꼴만), `apps/worker/tests/production/test_variety_render.py` |

## 할 것
- 착수 전 Q9 확인: Cafe24 Ohsquare·여기어때 잘난체 상업 이용·동봉 조건. 불가면 Pretendard Black 대체(D-V3), 리포트에 대체 여부 기록.
- 컷별 trim → 띠(y 560~1376) 크롭·배율·x/y → 흰 캔버스 합성 → 제목·자막(line/punch)·반응 PNG 오버레이 → concat → 원본 소리 정규화 → MP4(1080×1920·30fps·H.264/AAC)·리포트(컷 표). 폭 초과는 `text_too_long`.

## 하지 않을 것
- CapCut 형식 읽기·쓰기, 속도·J/L 컷·색 효과, 작업 폴더 밖 경로, 라이선스 미확인 글꼴 동봉.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/worker && pytest -q tests/production/test_variety_render.py` 통과(합성 원본으로 컷 순서·길이 ±1프레임, 띠 밖 흰색 픽셀 검사)
- [ ] 산출물 `ffprobe`가 1080×1920·30fps·h264/aac · 글꼴 라이선스 파일이 licenses/에 존재
