# NOW — 재진입 스냅샷 (30줄 이내, 매 작업 끝에 덮어쓴다)

- 갱신: 2026-11-20 · **작업 표 전부 완료**(W1~W10, 056·057·058 후속 포함). 남은 표 작업은 task-039 보류(PyAV GPL)뿐
- 다음 한 걸음: 새 작업 없음. 후보 = `tasks/README.md#발견한 문제`(A-12 낙관적 잠금 updated_at · A-09 언어별 latest_run·ja 녹음 업로드 UI · 배포 체크리스트 항목) → 사용자가 고르면 작업 파일 만들고 `/next`
- 결정 기록: 각 `tasks/task-0NN.md`의 착수·구현 결정. 사용자 결정 `tasks/plan-*.md#사용자 결정`. 팀장 기본값(사용자 "묻지 말고 진행" 지시): 054 확인=owner만·본인 검수 허용, 049 현재 승인 ko에서만 파생·variety 포함, 050 ja 렌더는 ko inspect·done, 051 대사만 더빙·목소리 워커 상수·variety 녹음 대체 없음, 058 녹음 상한 8
- P1 인수 결과(api `acceptance/test_ja_shop_p1_api_acceptance.py` · worker `acceptance/test_ja_shop_p1_worker_acceptance.py`)
  | ID | 결과 | 확인 |
  |---|---|---|
  | JA-01 | 통과 | 3형식 파생: 번역 경로만 변경·실제 값 다름, ko·ja 각각 MP4·컷 타이밍 동일 |
  | JA-02 | 통과 | 카테고리 훅·쇼핑 내레이션 ja 목소리, report fonts JP만 |
  | JA-03 | 통과 | 창 안 배치 무경고, 넘치면 dub_overflow·창에서 자름, TTS 꺼짐 tts_failed |
  | JA-04 | 통과 | ja 수정·승인(job 불변), ko 녹음 4개 작업에 ja 녹음 4개→승인, ko 녹음 참조 차단, TTS 꺼짐 무음 금지 |
  | JA-05 | 통과 | 【PR】·라쿠텐·아마존 ja 링크만 |
  | SHOP-07 | 통과 | 3안 후킹 유형 상이·4문장, 5문장·중복 유형 502 |
  | SHOP-08 | 통과 | 예산 0·상한 초과 409, 미검수 AI 컷 승인 차단, 여행 사진 pan·zoom 실제 움직임 |
  | 회귀 | 통과 | api 1397 · worker 411 · web 570 · db 672 |
- 사람 할 일: `.env.example` 이름 추가(WORKER_* 11·ANTHROPIC_API_KEY·AI_DRAFT_* 7·VIDEOGEN_ENABLED·VIDEOGEN_XAI_API_KEY·VIDEOGEN_KRW_PER_USD·VIDEOGEN_TIMEOUT_SEC) · 미커밋 `design/`(출처 미상) 정리 · 실제 외부 호출 첫 확인(Claude 번역·대본, edge-tts ja, yt-dlp, xAI — 모두 목으로만 검증, xAI 엔드포인트·단가·결과 호스트는 가정) · 실환경 3구간 화면 캡처 · 운영 Supabase Pro·배포(워커 먼저 → 000024~000029)
- 알려진 한계: A-12 동시 저장 유실(rev_no만 비교) · PROD-03 ja 탭 진행률·MP4 구분 불가(A-09 lang 없음) · ja 녹음 대체 업로드 UI 없음 · 관용어·금칙·ja 금지 문구·제목 간격은 가정 목록 · 무음 정리가 녹음당 약 0.04초 유음 깎음 · ERD 도구 ADD COLUMN 미표시 · jsdom 없음
- 주의(함정): Supabase 키는 셸 변수로만 · 테스트 가짜 키 런타임 조립 · lock·.env* 읽기 거부 · Codex 리뷰 로그는 작업별 -o 경로(공유 파일 덮어씀)
- 모델 규칙: 워커 model 위험도별 낮음 haiku · 보통 sonnet · 높음 opus, Opus 2회 실패 → fable
- SDLC 단계: 06 구현 완료 → 07 검증·08 배포 대기
