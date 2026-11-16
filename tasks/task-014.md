# task-014 MON-D1 프로필 조건 설정

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-010, task-012 |
| 위험도 | 보통 |
| 보안 영향 | 없음 (기존 인증 면의 PUT 중계, 서버 검증은 task-010) |
| 담당 | builder |
| 근거 | `spec MON-D1`, `docs/04_API.md#A-03`, `design/wireframes/MON-D1.html` |
| 쓰기 허용 | `apps/web/src/app/(dashboard)/monitoring/profiles/**`, `apps/web/src/components/profiles/**`, `apps/web/src/app/api/profiles/**` |

## 할 것
- `spec MON-D1`의 구성 블록·상태·다음 화면대로 조건 폼(시장 KR·JP, 형식, 카테고리, 최소 조회수, 허용 증가율, 키워드 ≤5, C.C만, 방송사 포함) 저장·검증 대상 선택(최대 3).
- 필드별 오류(400)·동시 수정(409) 표시, 입력 유지.

## 하지 않을 것
- 프로필 생성·삭제·무제한 프로필, 후보 목록(MON-01).

## 완료 조건 (실행 가능한 확인)
- [ ] `pnpm typecheck && pnpm lint && pnpm test` 통과(범위 초과·4개 선택·409 상태)
- [ ] `shot`으로 3구간 캡처 확인
