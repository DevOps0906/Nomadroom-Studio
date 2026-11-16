# NOW — 재진입 스냅샷 (30줄 이내, 매 작업 끝에 덮어쓴다)

- 갱신: 2026-11-16
- 현재 작업: M0 완료(001·018·004) → 다음 task-002 Supabase 스키마·RLS·시드·ERD — 상태: 대기
- 단계: M1 데이터·인증(002 → 003 · 012). 002는 위험도 높음 → challenger 착수 전 + code·security 리뷰
- 다음 한 걸음: `/next 002`
- task-004 결과: .githooks/pre-commit(gitleaks 8.30.1, prepare로 hooksPath 자동), 워크플로 ci·secrets·sbom(액션 SHA 고정, contents: read), Dependabot, SECURITY.md, deny에 모든 깊이 .env·Chrome 프로필
  - main push에서 ci·secrets·sbom 모두 success 확인(2d8fc65)
- 열린 PR(Dependabot 9건): TypeScript 7.0.2 PR은 ci 실패(Next 호환 문제 예상) → 닫거나 무시 결정 필요. 나머지(vitest 5, lucide 1.x, @types/node 26, 액션 메이저 업데이트)는 검토 후 병합 여부 결정
- 주의(함정):
  - pnpm 미설치 → `corepack pnpm`, 명령은 `apps/web`에서. `pnpm licenses`는 `-r` 필요(루트는 0개)
  - 반응형 접두사는 `tablet:`·`desktop:`만 · `shot` 390 캡처는 520px로 찍힘(도구 한계)
  - jsdom 없음 → 클라이언트 상호작용 테스트 제한 · `.env*` 읽기 거부 · Codex CLI 401 → designer/reviewer
  - jq 로컬 없음(CI에만)
- 열린 결정: vidIQ 약관(task-009 보류) · 구간별 폰트 최종값 · Dependabot PR 처리 · GitHub에서 Dependabot alerts·비공개 취약점 신고 켜기(사람)
- SDLC 단계: 06 구현
- 테스트 상태: web lint·typecheck·test(4) 통과, CI main 통과
