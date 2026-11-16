# task-001 프로젝트 생성 · 토큰

| 항목 | 내용 |
|---|---|
| 웨이브 | W1 |
| 선행 | — |
| 위험도 | 낮음 |
| 보안 영향 | 없음 (새 의존성은 `secscan license`로 확인) |
| 담당 | builder |
| 근거 | `AGENTS.md#2·#3`, `docs/02_ARCHITECTURE.md#1`, `docs/design/Nomadroom_Dashboard_Design.html`(시안), `DESIGN.md` |
| 쓰기 허용 | `package.json`, `pnpm-workspace.yaml`, `apps/web/**`, `DESIGN.md`, `docs/DESIGN_TOKENS.md`(생성만), `.env.example` |

## 할 것
- pnpm 모노레포 + `apps/web`(Next.js 16 · React 19 · TS · Tailwind v4 · shadcn/ui, 작업 시점 stable 버전 고정).
- 시안에서 색·타이포·간격을 뽑아 `apps/web/src/styles/tokens.css`(3구간 폰트 토큰)·`DESIGN.md` 작성, `design-preview --md`로 토큰 표 생성.
- `pnpm dev`·`lint`·`typecheck`·`test` 스크립트, 빈 홈 페이지, `.env.example`(이름만).

## 하지 않을 것
- 화면 구현·Supabase 연동·API 코드(이후 작업). hex·px를 컴포넌트에 직접 쓰지 않는다.

## 완료 조건 (실행 가능한 확인)
- [x] `pnpm install && pnpm lint && pnpm typecheck` 통과
- [x] `pnpm dev` 기동 후 홈 200 응답
- [x] `~/.claude/nomad/bin/secscan license` GPL·AGPL 0건
- [x] `grep -rE "#[0-9a-fA-F]{3,6}\b" apps/web/src --include=*.tsx` 결과 0건
