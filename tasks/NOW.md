# NOW — 재진입 스냅샷 (30줄 이내, 매 작업 끝에 덮어쓴다)

- 갱신: 2026-11-16
- 현재 작업: task-001 완료 → 다음 task-018 공통 레이아웃(앱 셸) — 상태: 대기
- 단계: M0 기반·디자인 셸 (`docs/06_AGENT_PLAN.md`) 1/3. 남은 M0: 018(낮음) · 004(높음, 018과 병렬 가능). 그다음 M1(002→003·012)
- 다음 한 걸음: `/next 018` (단계 순서상 002보다 먼저). 근거: 작업 파일의 시안 사이드바·상단 바·작업 탭
- task-001 결과: pnpm 모노레포 + apps/web(Next.js 16.4.6 · React 19.3.1 · Tailwind 4.3.5 · TS 5.9.3 · ESLint 9.39.1 · Vitest 4.1.0), tokens.css(@theme, 3구간 폰트 rem, breakpoint tablet 768 / desktop 1200), DESIGN.md, docs/DESIGN_TOKENS.md
- 주의(함정):
  - pnpm 미설치 → `corepack pnpm`. 루트 스크립트는 내부에서 `pnpm`을 불러 실패 → `cd apps/web` 후 실행(또는 `corepack enable`)
  - 반응형 접두사는 `tablet:`·`desktop:`만(Tailwind 기본 sm/md/lg/xl 제거됨)
  - `secscan license`는 pnpm-lock에 라이선스가 없어 판정 불가 → `corepack pnpm licenses list --json`으로 확인
  - `.env*`는 읽기 거부 규칙 대상
  - Codex CLI 인증 실패(401) → codex-* 대신 designer/reviewer
  - Pretendard 웹폰트 로딩 미적용(018에서 layout.tsx 처리 후보)
- 열린 결정: vidIQ 약관(task-009 보류) · 구간별 폰트 최종값 사용자 확인(display 30/36/42, h1 24/28/34, h2 18/20/21, body 15/14/14)
- SDLC 단계: 06 구현
- 테스트 상태: lint·typecheck·test(1) 통과, dev 홈 200, GPL·AGPL 0건
