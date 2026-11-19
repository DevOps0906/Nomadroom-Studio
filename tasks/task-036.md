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

## 착수 결정 (2026-11-19, challenger 검토 반영 · 팀장 결정)
- 쓰기 허용(최종): `apps/worker/production/variety/**` · `apps/worker/production/adapter_variety.py` · `apps/worker/production/runner.py`(format 분기만) · `apps/worker/tests/production/**`(acceptance 제외) · `apps/worker/licenses/THIRD_PARTY.md`(글꼴 대체 기록만) · `apps/api/app/routes/production_render.py`(A-15·A-16 variety 409 해제만) · `apps/api/tests/production/test_render_runs.py`(V2 반전) · `docs/04_API.md#A-15·A-16` · `docs/05_DATA_MODEL.md#예능형-spec`(preset 상수 기록만). 글꼴 경로는 `apps/worker/fonts`.
- W1 runner: `_render` 맨 앞에서 format 분기 → `_render_variety`. preset·lang 확인은 형식별 상수로 각 함수 안에서.
- W2 A/V 동기: 컷 경계는 누적 출력시각×30 반올림 프레임 격자, 소리 atrim도 같은 경계(1프레임=1600샘플@48k). 짧은 컷 여러 개에서 마지막 컷 A/V 오차 ≤1프레임 테스트.
- W3 띠 덮임: 원본 사각형 크기 ceil·위치 floor, 워커가 probe한 실제 크기로 덮임 재검증(위반 render_failed). 경계 배율 픽셀 테스트.
- W4 성능: 띠에 보이는 원본 영역만 잘라 축소 후 합성, 컷별 decoder는 -ss/-frames:v. 180초·배율 3 소요 시간을 report에 기록.
- W5 합성 방식: 카테고리형처럼 PIL 합성 → rawvideo pipe 인코딩. drawtext·concat demuxer·-safe 0 금지, 모든 입력 file_input().
- W6 비신뢰 spec: adapter_variety에서 컷 1~60·총 180초·문구 길이·제어문자(task-035 확장 목록 동일)·반응 좌표 재검증. has_audio=false면 anullsrc AAC 트랙 + 테스트.
- W7 검증: `pytest -rs` skip 0건. 단색(초록) 합성 원본으로 "띠 밖 초록 0, 띠 안 흰색 0(경계 2px 여유)".
- W8 Q9 결과: 실습 zip에 글꼴·라이선스 없음(파일 목록 확인) → 기본값대로 Pretendard-Black(OFL) 사용, report `font_substituted: true`, THIRD_PARTY.md 기록. 글꼴 다운로드 금지.
- W9 글리프 없는 문자: Pretendard → NotoSansCJKkr-Bold 순서로 대체, 둘 다 없으면 render_failed(detail glyph_missing). 이모지 미지원.
- W10 배포: 워커와 API는 같은 커밋으로 배포하고 워커 재시작(구 워커가 예능형을 받으면 render_failed) — 운영 메모로 기록.
- W11 크기 상수(자막 알약·제목·반응 px, 자막 y 등)는 `docs/research/variety-shorts-zip-analysis.md` 실측값을 우선, 없으면 preset 상수로 정하고 05 예능형 장에 기록.
- 순서: task-035 리뷰 반영 커밋(같은 production_render.py) 뒤 착수.
