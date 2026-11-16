# task-017 A-08 사용한 소재 수동 표시

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-011, task-013 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 (인증 후 PATCH, CSRF) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-08`, `docs/01_PRD.md#3·#7(Q4)·#9 순서4`, `spec MON-01` |
| 쓰기 허용 | `apps/api/app/routes/candidates_used.py`, `apps/api/tests/used/**`, `apps/web/src/components/monitoring/UsedToggle.tsx`, `apps/web/src/app/api/candidates/**` |

## 할 것
- `PATCH /v1/candidates/{id}/used`(`used`·`used_at`, 타 워크스페이스 404) + MON-01 후보 카드 토글. 표시 상태는 판정보다 우선, 대표 판정·counts 반영.
- Q4 수동 표시로 확정(사용자 결정 2026-11-16, `docs/01_PRD.md#7`).

## 하지 않을 것
- 운영 사이트 자동 연동, 사용 이력 테이블 추가.

## 완료 조건 (실행 가능한 확인)
- [ ] `cd apps/api && pytest -q tests/used` 통과(토글·되돌리기·타 워크스페이스 404·counts 변화)
- [ ] `pnpm typecheck && pnpm test` 통과, 타 Origin PATCH 403 테스트 통과
