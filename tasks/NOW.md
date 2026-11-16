# NOW — 재진입 스냅샷 (30줄 이내, 매 작업 끝에 덮어쓴다)

- 갱신: 2026-11-16
- 현재 작업: task-003 완료(959dc55) → 다음 task-012 AUTH-01 로그인 — 상태: 대기
- 단계: M1 데이터·인증(002·003 완료 → 012). 012는 위험도 높음 → challenger 착수 전 + code·security(+design) 리뷰
- 다음 한 걸음: `/next 012`. 그다음 M2: 005 ∥ 010 병렬
- task-003 결과: apps/api(uv·Python 3.14·fastapi 0.163.1), JWKS ES256 검증·소속 1행·워커 토큰·CLI·로그 마스킹, pytest 69 + integration 2
  - 결정: `tasks/task-003.md#구현 결정`. docs 기본 끔(API_DOCS_ENABLED), 원격 SUPABASE_URL https만, JWKS 실패 60초 쿨다운 503
  - 세션 철회: JWT exp(≤3600초)까지 유효, 소속은 매 요청 확인(팀장 결정)
- task-002 결과: 마이그레이션 5개·RLS·seed(로컬 전용)·pgTAP 50/50. 후속 메모 `tasks/task-002.md#이후 작업 메모`
- 주의(함정):
  - Supabase CLI는 `npx supabase@3.1.0`, Docker Desktop 필요. 로컬 포트 547xx. JWKS http://127.0.0.1:54721/auth/v1/.well-known/jwks.json
  - api 통합 테스트: `npx supabase@3.1.0 status -o env` 값을 셸 환경변수로만(파일 금지) → `uv run pytest -q -m integration`
  - gitleaks는 winget 설치. bash에서는 PATH에 `.../WinGet/Packages/Gitleaks.Gitleaks_Microsoft.Winget.Source_8wekyb3d8bbwe` 추가
  - 테스트의 가짜 JWT·키는 런타임 조립(문자열 리터럴이면 gitleaks에 걸림)
  - pnpm은 `corepack pnpm`, `apps/web`에서 실행 · 반응형은 `tablet:`·`desktop:` · jsdom 없음 · `.env*` 읽기 거부 · Codex CLI 401이라 reviewer로 대체
- 열린 결정: vidIQ 약관(task-009 보류) · 구간별 폰트 최종값 · Dependabot PR 9건(TS 7은 ci 실패) · GitHub Dependabot alerts·비공개 신고 켜기(사람) · 미확인 방송사 채널(tvN 본채널·SBS NOW·NHK 뉴스·CJ ENM 계열)
- 커밋 안 된 사용자 수정: AGENTS.md·CLAUDE.md·.claude/rules/db.md(건드리지 않음)
- SDLC 단계: 06 구현
- 테스트 상태: supabase test db 50/50 · api pytest 69 + integration 2 · web lint·typecheck 통과
