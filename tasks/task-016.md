# task-016 DASH-01 대시보드

| 항목 | 내용 |
|---|---|
| 웨이브 | W3 |
| 선행 | task-011, task-012, task-018 |
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
- 셸 재구현 금지(task-018 사용).

## 완료 조건 (실행 가능한 확인)
- [x] `pnpm typecheck && pnpm lint && pnpm test` 통과(빈 데이터·로딩·오류, null 3칸 라벨)
- [x] `shot`으로 3구간 캡처 확인

## 구현 결정 (팀장, 2026-11-17)
- 웹→API 공용 클라이언트 `apps/web/src/server/api/client.ts`(server-only)를 이 작업에서 만든다: 환경변수 `API_BASE_URL`(서버 전용), 현재 세션 access token을 `Authorization: Bearer`로 전달(getClaims로 검증한 뒤 getSession의 토큰 사용), 타임아웃 10초, 응답 `{code,message,field?}`를 타입 있는 오류로 변환, 401이면 /login, 403 FORBIDDEN이면 소속 없음 안내. 014가 이 클라이언트를 재사용한다.
- 읽기는 Server Component에서 호출(`/api/**` Route Handler 만들지 않음). 쓰기는 Server Action(Next Origin 검사).
- 미연동 3칸은 "—" + "운영 사이트 연동 전". 외부 링크는 `NEXT_PUBLIC_OPS_SITE_URL`(기본값은 시안의 운영 사이트 주소), `target=_blank rel="noopener noreferrer"`.
- 로그아웃 버튼(SignOutButton, task-012)을 상단 바 사용자 영역에 배치(셸 파일에서 버튼 1개만 추가, 구조 변경 금지).
- 쓰기 허용 확장: `apps/web/src/server/api/**`, `apps/web/src/components/shell/**`(로그아웃 버튼 배치만), `.env.example`(이름만 `cat >>`).
