# NOW — 재진입 스냅샷 (30줄 이내, 매 작업 끝에 덮어쓴다)

- 갱신: 2026-11-16
- 현재 작업: task-018 완료 → 다음 task-004 보안 L1 설정(`/secure setup`) — 상태: 대기
- 단계: M0 기반·디자인 셸 2/3 (001·018 완료). 004 끝나면 M1(002 → 003 · 012)
- 다음 한 걸음: `/next 004` — 위험도 높음 → challenger 착수 전 검토 + code·security 리뷰
- task-018 결과: apps/web/src/components/shell/**(app-shell·sidebar-nav·nav-link·nav-config), app/(dashboard)/layout.tsx, /dashboard·/monitor 빈 슬롯, / → /dashboard
  - 외부 링크 기본값 = 시안 운영 사이트 주소(`nav-config.ts` DEFAULT_OPS_SITE_URL), env 빈 문자열이면 "(연동 전)"
  - 모바일 드로어: Esc 닫기·포커스 이동/복귀·본문 inert. "진단 · 채널 관리" 한 항목
- 주의(함정):
  - pnpm 미설치 → `corepack pnpm`, 명령은 `apps/web`에서 실행
  - 반응형 접두사는 `tablet:`·`desktop:`만
  - `shot` 390 캡처는 Chrome 최소 창 폭 때문에 520px로 찍힘(오른쪽 회색은 도구 여백, 앱 문제 아님)
  - jsdom·testing-library 없음 → 클라이언트 상호작용 테스트는 renderToStaticMarkup 수준. 필요 시 새 의존성 작업으로 추가
  - `.env*` 읽기 거부 규칙 · Codex CLI 401 → designer/reviewer 대체
  - Pretendard 웹폰트 로딩 미적용
- 열린 결정: vidIQ 약관(task-009 보류) · 구간별 폰트 최종값 사용자 확인
- SDLC 단계: 06 구현
- 테스트 상태: lint·typecheck·test(4) 통과, 3구간 캡처 확인, reviewer(design) 🔴 2건 반영
