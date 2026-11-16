# task-016 DASH-01 대시보드

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-011, task-012 |
| 위험도 | 보통 |
| 보안 영향 | 없음 |
| 담당 | builder (+ codex-reviewer design) |
| 근거 | `spec DASH-01`, `docs/04_API.md#A-02`, `docs/01_PRD.md#3`, `docs/design/Nomadroom_Dashboard_Design.html`, `design/wireframes/DASH-01.html` |
| 쓰기 허용 | `apps/web/src/app/(dashboard)/page.tsx`, `apps/web/src/components/dashboard/**`, `apps/web/src/app/api/dashboard/**` |

## 할 것
- `spec DASH-01` 구성 블록·상태·다음 화면대로 인사·요약 4칸(미연동 3칸은 "—"+"운영 사이트 연동 전", 전주 대비 없음)·소재수집 요약 패널·최근 제작 가능 ≤5.
- 나머지 메뉴·"새 영상 만들기"는 외부 링크만(URL은 환경변수 `NEXT_PUBLIC_OPS_SITE_URL`, 기본값은 시안의 운영 사이트 주소 — 사용자 결정 2026-11-16).

## 하지 않을 것
- 기간 선택·일별 차트·할 일 목록(이후), 메뉴 화면 내재화.

## 완료 조건 (실행 가능한 확인)
- [ ] `pnpm typecheck && pnpm lint && pnpm test` 통과(빈 데이터·로딩·오류, null 3칸 라벨)
- [ ] `shot`으로 3구간 캡처 확인
