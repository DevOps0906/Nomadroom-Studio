# NOW — 재진입 스냅샷 (30줄 이내, 매 작업 끝에 덮어쓴다)

- 갱신: 2026-11-16
- 현재 작업: /plan 기획 보강 — 상태: 완료(커밋 전) → 다음은 task-001 프로젝트 생성 · 토큰
- 마지막으로 한 일: 00~05·ADR 2건·benchmark·다이어그램·task-001~017 작성, doc 리뷰 🔴5 반영, plan2spec 🔴 0
- 다음 한 걸음: 기획 산출물 커밋 → `/clear` → `/next`(task-001)
- 결정됨(사용자 2026-11-16): MVP=로그인+대시보드+소재수집(정체) · 데이터=YouTube API+Chrome·vidIQ · 내부 도구 · 사용한 소재=수동 표시 · 방송사 시드=주요 방송사 기본 목록 · 외부 링크=`NEXT_PUBLIC_OPS_SITE_URL`
- 결정됨(팀장): 워커는 FastAPI만 호출 · 판정 규칙 정본 `docs/01_PRD.md#9` · 후보 상한 200 · 재시도 3 · 하트비트 3분 · 보안 L1 · 토큰 회전 90일(가정) · market KR/JP
- 열린 결정: vidIQ 약관(사용자 확인 후 결정) → task-009 보류
- 주의: Codex CLI 인증 실패(401) — codex-* 대신 designer/reviewer로 대체 중. `codex login` 필요.
  `mmd-check`는 폴더가 아니라 파일 단위로 넘긴다. 벤치마킹은 실제 화면 미확인.
- SDLC 단계: 05 기술 설계 완료 → 06 구현 시작 전
- 수정 파일: docs/**, design/**, tasks/**, AGENTS.md(1장·4장), README.md(진행 현황·바로가기)
- 테스트 상태: 미실행(코드 없음)
- 남은 작업: task-001~017 (task-009 보류)
