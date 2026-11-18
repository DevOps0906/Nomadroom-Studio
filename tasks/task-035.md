# task-035 예능형 API 연결

| 항목 | 내용 |
|---|---|
| 웨이브 | W6 |
| 선행 | task-034 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면(A-09 입력 확장) · 워커 계약(W-05 task.format) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-09`·`#A-12`·W-05, `docs/02b_PRODUCTION_FLOW.md`, `docs/05_DATA_MODEL.md#예능형-spec` |
| 쓰기 허용 | `apps/api/app/routes/production_jobs.py`, `apps/api/app/production/adapter*.py`, `apps/api/app/routes/worker_production.py`(W-05 task.format만), `apps/api/tests/production/**` |

## 할 것
- A-09 `format=variety` 허용(형식 고정, 이후 변경 불가)·preset_version 형식별. A-10 훅 음성 업로드는 variety에서 400. A-09 목록에 `format` 필터·`items[].format` 추가.
- A-12 저장·A-13 승인 검증을 format으로 분기. 렌더 어댑터가 승인 리비전을 `variety_project.json`으로 변환, W-05 `task.format`에 format을 싣는다(W-06은 inputs만).

## 하지 않을 것
- 렌더러(036), 화면(037), 받아쓰기·AI 초안(P1), 카테고리형 응답 형태 변경.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production` 통과(variety 생성·저장·승인·어댑터 산출 JSON 스냅샷, 형식 변경 PATCH 거부, variety 훅 업로드 400)
- [ ] `cd apps/api && pytest -q` 전체 회귀 · 경로 필드 거부 테스트 유지
