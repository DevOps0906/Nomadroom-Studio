# task-022 제작 작업 API A-09~A-13·A-17·A-18

| 항목 | 내용 |
|---|---|
| 웨이브 | W4 |
| 선행 | task-020, task-021 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면(업로드·서명 URL 발급 · 인증 후 POST/PATCH/PUT) · 경로 보안 |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-09`~`#A-13`·`#A-17`·`#A-18`, `docs/05_DATA_MODEL.md#storage`, `docs/01_PRD.md#8` |
| 쓰기 허용 | `apps/api/app/routes/production_jobs.py`, `apps/api/app/production/storage.py`, `apps/api/app/main.py`(라우터 등록만), `apps/api/tests/production/test_jobs_api.py`, `apps/web/src/server/api/production.ts`(호출 함수만) |

## 할 것
- A-09 POST·PATCH·GET(멱등 키·권리 확인·구간 검증), A-10 업로드 서명 PUT·완료(15분·크기 확인), A-11 prepare, A-12 리비전 GET·PUT(낙관적 잠금·오류 있어도 저장), A-13 승인(서버 재검증), A-17 검수 승인, A-18 다운로드 서명 GET(10분).
- 웹·API는 작업 ID·자산 ID만 주고받는다. 타 워크스페이스 404.

## 하지 않을 것
- 렌더 요청·재시도·워커 API(023), AI 초안·URL 다운로드(P1), 서명 URL 로그 출력, 화면.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/production/test_jobs_api.py` 통과(멱등 재요청 200, 409 상태 불가, 타 워크스페이스 404, 오류 있는 spec 승인 400, 경로 필드 거부)
- [ ] `cd apps/api && pytest -q` 전체 회귀 통과 · 로그 캡처에 서명 URL 토큰 0건
