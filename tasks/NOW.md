# NOW — 재진입 스냅샷 (30줄 이내, 매 작업 끝에 덮어쓴다)

- 갱신: 2026-11-19
- 현재 작업: W5 029~032 완료, W6 034(bf46d56)·035(b054227) 완료. 진행 중(병렬): task-033 W5 인수 테스트(tester) · task-036 예능형 렌더러(opus, 착수 결정 W1~W11) · task-037 예능형 화면(sonnet). 다음: 038 예능형 인수 → W7(039~041) → W8(042~047) → W9(048·054)
- 단계: W5(P1: 029~033) → W6·W7 예능형(034~041, 브리프 `tasks/plan-variety-shorts.md`, 미결 Q9~Q11) → W8~W10 쇼핑·AI 영상·일본어판(042~054, 브리프 `tasks/plan-shopping-japanese.md`, 미결 Q12~Q16). 카테고리형 브리프 `tasks/plan-category-shorts.md`
- 다음 한 걸음: `/next` (task-029). 사용자 지시(2026-11-19): W5~W9(029~048·054) 멈추지 말고 연속 진행. Q9~Q16·Claude API 목 전용 결정은 `tasks/plan-*.md#사용자 결정`
- W4 결과(커밋 7fb183f·b5267ec·634d949·131a458·1f83631·1fc1d2c·a3bfed5 + 028): 제작 API A-09~A-18·워커 API W-05~W-09(000016·000017 RPC), 화면 PROD-00~03, 로컬 제작 워커 `apps/worker`(배포본 이식, 사용자 권리 확인). 결정은 각 task 파일 "착수 결정·구현 결정·리뷰 반영 결정"
- task-028 CAT-01~07: 단위 모두 통과, 실환경(로컬 Supabase+API 8028+워커) 렌더 608x1080·30/1·h264/aac 15초 → 검수 승인 done. CAT-05 실환경 미실행·CAT-07 재시도는 단위만. 상세 `tasks/task-028.md#구현 결정`
  - 결함 2건(🟡, `it.fails`로 재현, `tasks/README.md#발견한 문제`): 훅 초과 시 필요 초 안내 없음 · PROD-03 검수 3항목 안내 없음
- 계약 메모: 업로드 서명 만료는 Supabase 고정 2시간(04 반영) · finish 재호출 409=이미 처리됨 · 오프라인 3분·queued 10분 만료 · 렌더 ko만(ja 400) · URL 원본 400(task-031)
- 사람 할 일: `.env.example`에 WORKER_API_BASE_URL·WORKER_TOKEN·WORKER_FFMPEG·WORKER_FFPROBE·WORKER_WORK_DIR·WORKER_POLL_INTERVAL_SEC·WORKER_PROGRESS_INTERVAL_SEC 이름 추가(.env* 에이전트 권한 없음) · 미커밋 `design/`(spec.json·와이어프레임 8개, 20:25 수정, 문구 깨짐, 출처 미상) 유지/되돌리기 결정
- 모델 규칙: 워커 model 위험도별 — 낮음 haiku · 보통 sonnet · 높음 opus. Opus 2회 실패 → fable
- 주의(함정):
  - Supabase CLI `npx supabase@3.1.0`, Docker Desktop 필요, 로컬 포트 547xx. 키는 `status -o env`를 셸 변수로만(파일 금지)
  - api 통합 테스트 `uv run pytest -q -m integration` · pnpm은 `npx corepack pnpm`(apps/web) · jsdom 없음(클릭·visibility 동작은 자동 테스트 불가)
  - 테스트의 가짜 키·토큰은 런타임 조립(gitleaks) — 조립 결과가 원래 값과 같은지 테스트로 확인 후 커밋
  - lock·.env* 읽기 거부 → 의존성 취약점은 `uv export` + `uvx pip-audit --no-deps`
  - Docker 실행 후 9327~9526 포트 예약 → CDP 19335. 실환경 스크립트 scratchpad `acc028/e2e_real.py`(API 8028)
  - Codex CLI 401 → codex-reviewer 대신 reviewer
  - 워커 실행: `cd apps/worker && uv run python main.py`(WORKER_* 환경변수, 로컬은 http://127.0.0.1 허용), 시스템 ffmpeg 8.1.1
- 열린 결정: vidIQ 준비 중(수집은 YouTube 검색) · 구간별 폰트 최종값 · Dependabot PR 9건 · GitHub 보안 알림 켜기(사람) · .env.example API_BASE_URL 중복 줄 · nomad-agent-os 미커밋 21파일
- 커밋 안 된 사용자 수정: AGENTS.md·CLAUDE.md·.claude/rules/db.md(건드리지 않음)
- SDLC 단계: 06 구현
- 테스트 상태: supabase test db 432 · api pytest 901(acceptance 제외) + integration 13 · web test 417 · worker pytest 236

## task-033 인수 결과 (2026-11-19, tester) — 상세 `tasks/task-033.md#구현 결정`
| CAT | 결과 | 근거(실환경=로컬 Supabase+API+워커, 목: Claude·edge-tts·yt-dlp) |
|---|---|---|
| 01~07 | PASS | 단위(api 975·worker 246·web 433) + P0 실환경 e2e 재실행(608x1080 30/1 h264/aac) |
| 08 오버레이 | PASS | 실환경 A(URL목·AI초안목·오버레이·TTS실패→첨부·렌더·done)·B(TTS 성공+오버레이), ffprobe 15.00s, 프레임 확인 |
| 목 대체 | 표시 | Claude=로컬 HTTP(ANTHROPIC_BASE_URL)·edge-tts=워커 래퍼 목·yt-dlp=워커 다운로더 목 |
| 결함 🟡 | it.fails | TTS 선택 UI 없음 · review 복귀 시 사유·편집 링크 안 보임 · header 가림 경고 없음 · AI 초안이 overlays 누락 |
