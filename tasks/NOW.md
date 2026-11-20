# NOW — 재진입 스냅샷 (30줄 이내, 매 작업 끝에 덮어쓴다)

- 갱신: 2026-11-20 · task-054 완료, task-056 구현 중
- 완료: W1~W7(039 받아쓰기 보류 — PyAV GPL 코덱, Q10 기본값), W8 042~047, 055
- 다음 한 걸음: `/next` → task-048 AI 대본 3안 + 게시 문구 초안(높음, challenger 먼저) → task-054 AI 영상 연동(높음, Q16: 어댑터만·기본 꺼짐) → (범위 밖) W10 일본어판 049~053
- 결정 기록: 각 `tasks/task-0NN.md`, 사용자 결정 `tasks/plan-*.md#사용자 결정`. 2026-11-20: SHOP-01 길이 기준 = 무음 정리(hook_audio TRIM) 후 내레이션 합 ±1프레임
- SHOP 인수 결과(api `tests/production/acceptance/test_shop_api_acceptance.py` · worker `.../test_shop_worker_acceptance.py`, 원본은 실행 중 ffmpeg 합성)
  | ID | 결과 | 확인 |
  |---|---|---|
  | SHOP-01 | 통과 | API: 생성→원본 3→prepare→4문장·녹음 4→승인→렌더 페이로드. 워커: 1080×1920·30fps, 길이=정리 후 문장 합 ±1프레임, 자막=문장 구간 |
  | SHOP-02 | 통과 | 마스크 안 분산 <0.3배, 밖 >0.7배, 캔버스 밖 마스크 render_failed |
  | SHOP-03 | 통과 | 차단 4종(400·렌더 거부·run 미생성), 경고 3종(승인 200), 원본 3개 경계 |
  | SHOP-04 | 통과 | 건기식·의약품·공백 우회 400 banned_category, 미생성 |
  | SHOP-05 | 통과 | [광고]·지정 키워드 안내·고정 댓글 제휴 링크, ja 【PR】 |
  | SHOP-06 | 통과 | api tests/production 678 · worker tests/production 352 (CAT·VAR 인수 포함) |
- 실행 순서(로컬): 1 `npx supabase@3.1.0 start`→`db reset`(000001~000024)→`status -o env` · 2 API `apps/api/.env.local` → `cd apps/api && uv run python -m app` · 3 워커 토큰 `uv run python -m app.cli.worker_tokens issue --workspace <uuid> --name <이름>` · 4 웹 `apps/web/.env.local` → `npx corepack pnpm dev` · 5 워커 env(WORKER_*·WORKER_TTS_ENABLED=0) → `cd apps/worker && uv run python main.py` · 6 배포 시 워커 먼저 → 000024
- 사람 할 일: `.env.example`에 이름 추가(WORKER_* 11개·ANTHROPIC_API_KEY·AI_DRAFT_* 7개) · 미커밋 `design/`(spec.json·와이어프레임 8개, 출처 미상·문구 깨짐) 유지/되돌리기 · 실제 외부 호출 첫 확인(Claude·edge-tts·yt-dlp — 목으로만 검증) · 실환경 3구간 화면 캡처(046·047 미검증) · 운영 Supabase Pro·GitHub 보안 알림·Dependabot PR
- 알려진 한계: 무음 정리가 녹음당 약 0.04초 유음도 깎음(허용) · ERD 도구 ADD COLUMN 미표시 · jsdom 없음 · 쇼핑은 영상 원본 ≥1·원본당 최대 60초 · YouTube URL 실패 잦음
- 주의(함정): Supabase 키는 셸 변수로만 · 테스트 가짜 키 런타임 조립(gitleaks) · lock·.env* 읽기 거부 → `uv export`+`uvx pip-audit --no-deps` · 병렬 작업은 마이그레이션 번호를 팀장이 조정 · Codex CLI 401 → reviewer
- 모델 규칙: 워커 model 위험도별 낮음 haiku · 보통 sonnet · 높음 opus, Opus 2회 실패 → fable
- SDLC 단계: 06 구현
- 테스트 상태: supabase test db 533 · api pytest 1174+신규 20(전체 미재실행, production 678 통과) + integration 13 · web test 522 · worker pytest 352(skip 0)
