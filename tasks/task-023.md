# task-023 렌더 요청·재시도 A-15·A-16 + 워커 API W-05~W-09

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-022 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면(워커 토큰 API·서명 URL 발급) · 동시성(멱등·원자적 수령) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-15`·`#A-16`·`#W-05`~`#W-09`, `docs/02b_PRODUCTION_FLOW.md`(상태·오프라인), `docs/adr/0003-production-render-worker.md` |
| 쓰기 허용 | `apps/api/app/routes/production_render.py`, `apps/api/app/routes/worker_production.py`, `apps/api/app/production/runs.py`, `apps/api/app/main.py`(라우터 등록만), `apps/api/tests/production/test_render_runs.py`, `apps/api/tests/production/test_worker_production.py`, `docs/04_API.md`(W-09 `제안` 표기 정리만) |

## 할 것
- A-15 렌더 요청(멱등 키·(작업, 리비전, 언어) 1건·동시 1건), A-16 재시도(완료 파일 덮어쓰기 없음).
- W-05 수령(조건부 갱신·워커당 1건·재시작 복구), W-06 입력 서명 GET, W-07 산출물 서명 PUT(kind 허용 목록), W-08 진행·오프라인 평가, W-09 완료·실패(`hook_too_long`·`text_too_long`은 review 복귀, `worker_offline`은 서버 생성).
- 훅 공식 정본은 `docs/04_API.md#W-09` 그대로 구현.

## 하지 않을 것
- 워커 본체(024), DB 직접 접속 경로, 수집 워커 W-01~W-04 변경, P1 `source_url` 전달.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_render_runs.py tests/production/test_worker_production.py` 통과(동시 2건째 409, 멱등 재요청, 두 워커 동시 claim 중 1건만 수령, 허용 외 kind 400, 타 워크스페이스 토큰 404)
- [ ] `cd apps/api && pytest -q` 전체 회귀 통과
