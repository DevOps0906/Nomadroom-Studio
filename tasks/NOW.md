# NOW — 재진입 스냅샷 (30줄 이내, 매 작업 끝에 덮어쓴다)

- 갱신: 2026-11-20 · 사용자 지시로 여기서 멈춤(045까지 커밋·푸시, 이후 작업 미착수)
- 완료: W1~W7(039 받아쓰기 보류 — PyAV GPL 코덱, Q10 기본값), W8 042~046, 055. 마지막 기능 커밋 4789ab3(task-045)
- 다음 한 걸음: `/next` → task-047 쇼핑 인수 SHOP-01~06(실환경 종단 + 3구간 화면 캡처) → W9 048 AI 대본 3안·054 AI 영상 연동(Q16: 어댑터만, 기본 꺼짐) → (범위 밖) W10 일본어판 049~053
- 결정 기록: 각 `tasks/task-0NN.md`의 착수·구현·리뷰 반영 결정, 사용자 결정은 `tasks/plan-*.md#사용자 결정`(Q9~Q16 기본값·Claude 목 전용·쇼핑 내레이션 문장별 녹음 4개)
- 실행 순서(로컬):
  1. `npx supabase@3.1.0 start` → `db reset`(000001~000024) → `status -o env`
  2. API `apps/api/.env.local`(SUPABASE_URL·SUPABASE_SERVICE_ROLE_KEY·YOUTUBE_API_KEY·ANTHROPIC_API_KEY 선택·API_PORT=8001) → `cd apps/api && uv run python -m app` (`.env`·`.env.local` 둘 다 읽음)
  3. 워커 토큰 `uv run python -m app.cli.worker_tokens issue --workspace <uuid> --name <이름>`
  4. 웹 `apps/web/.env.local`(API_BASE_URL·APP_ORIGIN·SUPABASE_URL·SUPABASE_PUBLISHABLE_KEY) → `npx corepack pnpm dev`
  5. 워커 env(WORKER_API_BASE_URL·WORKER_TOKEN·WORKER_FFMPEG·WORKER_FFPROBE·WORKER_WORK_DIR·WORKER_TTS_ENABLED=0) → `cd apps/worker && uv run python main.py`
  6. 배포 시 워커 먼저 → 000024 적용(쇼핑 배정은 capabilities를 알린 워커만)
- 사람 할 일: `.env.example`에 이름 추가(WORKER_* 11개·ANTHROPIC_API_KEY·AI_DRAFT_* 7개) · 미커밋 `design/`(spec.json·와이어프레임 8개, 출처 미상·문구 깨짐) 유지/되돌리기 · 실제 외부 호출 첫 확인(Claude·edge-tts·yt-dlp — 모두 목으로만 검증) · 운영 Supabase Pro·GitHub 보안 알림·Dependabot PR
- 알려진 한계: ERD 도구가 ADD COLUMN 미표시 · jsdom 없음(클릭·visibility 자동 테스트 불가) · 3구간 캡처 미검증(046) · 쇼핑은 영상 원본 ≥1 필요·원본당 최대 60초 · YouTube URL은 JS 런타임 미사용이라 실패 잦음
- 주의(함정): Supabase 키는 셸 변수로만 · 테스트 가짜 키는 런타임 조립(gitleaks) · lock·.env* 읽기 거부 → 취약점은 `uv export`+`uvx pip-audit --no-deps` · 병렬 작업은 마이그레이션 번호·로컬 DB 순서를 팀장이 조정 · Codex CLI 401 → reviewer
- 모델 규칙: 워커 model 위험도별 낮음 haiku · 보통 sonnet · 높음 opus, Opus 2회 실패 → fable
- SDLC 단계: 06 구현
- 테스트 상태: supabase test db 533 · api pytest 1174 + integration 13 · web test 522 · worker pytest 348(skip 0)
