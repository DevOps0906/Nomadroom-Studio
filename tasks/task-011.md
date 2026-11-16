# task-011 조회 API A-02 · A-04 · A-06

| 항목 | 내용 |
|---|---|
| 웨이브 | W2 |
| 선행 | task-005, task-010 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 (인증 후 조회 API, 워크스페이스 격리) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-02·A-04·A-06`, `docs/05_DATA_MODEL.md#candidates·candidate_verdicts·observations`, `docs/01_PRD.md#3·#9` |
| 쓰기 허용 | `apps/api/app/routes/dashboard.py`, `apps/api/app/routes/candidates.py`, `apps/api/tests/read_api/**` |

## 할 것
- `GET /v1/dashboard/summary`(미연동 3칸은 null), `GET /v1/candidates`(상태·카테고리·형식·프로필·라이선스·검색·정렬·페이지, counts 포함), `GET /v1/candidates/{id}/evidence`.
- 표시 상태는 `used`가 판정보다 우선. 모든 쿼리 `workspace_id` 조건.

## 하지 않을 것
- A-08(task-017), 저장된 보기, 쓰기 로직.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/read_api` 통과: 필터·정렬·페이지(size 61 → 400 또는 60 제한), counts 합계, 타 워크스페이스 404, 이전 관측 없음 `needs_prev`
