# task-017 A-08 사용한 소재 수동 표시

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-011, task-013 |
| 위험도 | 높음 |
| 보안 영향 | 노출 면 (인증 후 PATCH, CSRF) |
| 담당 | builder + tester |
| 근거 | `docs/04_API.md#A-08`, `docs/01_PRD.md#3·#7(Q4)·#9 순서4`, `spec MON-01` |
| 쓰기 허용 | `apps/api/app/routes/candidates_used.py`, `apps/api/app/main.py`(라우터 등록만), `apps/api/tests/used/**`, `apps/web/src/components/monitoring/UsedToggle.tsx`, `apps/web/src/components/monitoring/monitor-view.tsx`(토글 배치만), `apps/web/src/app/api/candidates/**`, `apps/web/src/server/api/monitor.ts`(setUsed 추가), `docs/04_API.md`(A-08 행만) |

## 할 것
- `PATCH /v1/candidates/{id}/used`(`used`·`used_at`, 타 워크스페이스 404) + MON-01 후보 카드 토글. 표시 상태는 판정보다 우선, 대표 판정·counts 반영.
- Q4 수동 표시로 확정(사용자 결정 2026-11-16, `docs/01_PRD.md#7`).

## 하지 않을 것
- 운영 사이트 자동 연동, 사용 이력 테이블 추가.

## 완료 조건 (실행 가능한 확인)
- [x] `cd apps/api && pytest -q tests/used` 통과(토글·되돌리기·타 워크스페이스 404·counts 변화)
- [x] `pnpm typecheck && pnpm test` 통과, 타 Origin PATCH 403 테스트 통과

## 착수 결정 (팀장, 2026-11-18 challenger 반영)
- CSRF: Route Handler 첫 줄 `assertSameOrigin`(server/auth/same-origin.ts) 재사용. Origin 없음·타 Origin 모두 403(테스트 고정).
- used_at 정의(제작 전환 지표): used=true 재요청은 멱등(used_at 유지). 해제(false)는 used_at null, 다시 표시하면 새 시각. 구현: true는 `used=is.false` 조건부 update, 0행이면 id+workspace 재조회로 "이미 true(200·현재값)"와 404 구분. false는 id+workspace update.
- PostgREST update는 `Prefer: return=representation`(profiles.py 패턴). 없는 id·타 워크스페이스 모두 404 고정 문구.
- 본문: API는 StrictBool·extra 금지(공통 처리기로 400 VALIDATION). 웹은 `typeof used === "boolean"` 아니면 400, JSON 파싱 실패 400.
- 웹 오류 매핑: 400/422→400, 401→401, 403→403·404→404(고정 문구), 그 외 502. no-store.
- 필터 목록에서 표시하면 카드가 빠지는 것은 의도. 해제는 "사용한 소재" 필터(stat)에서.
- docs/04_API.md A-08 행: "제안" 제거, 멱등·해제 규칙 반영.

## 리뷰 반영 결정
- reviewer code+contract·security ACCEPT(🔴 없음). 역할 제한 없음(PRD#8에 역할 구분 없음, 소속만 인가 — 기존 패턴).
- 동시 true/false 경쟁: last-writer-wins. true 요청이 0행 재조회 사이에 false가 커밋되면 현재값(false)을 200으로 돌려준다. 웹은 refresh로 실제 상태를 다시 읽으므로 수용.
- 403은 UI에서 일반 오류 문구로 표시(단순화, 수용).
- 검증: api pytest tests/used 14 + 전체 454, 통합(used 수 +1/복귀·멱등·재표시·타 워크스페이스 404), web 266.
