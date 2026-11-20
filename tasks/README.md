# 작업 표

| 번호 | 제목 | 웨이브 | 선행 | 위험도 | 담당 | 상태 |
|---|---|---|---|---|---|---|
| task-001 | 프로젝트 생성 · 토큰 | W1 | — | 낮음 | builder | 완료 |
| task-002 | Supabase 스키마 · RLS · 시드 · ERD | W1 | 001 | 높음 | builder | 완료 |
| task-003 | FastAPI 뼈대 · JWT · 워커 토큰 인증 | W1 | 001, 002 | 높음 | builder | 완료 |
| task-004 | 보안 L1 설정 (`/secure setup`) | W1 | 001 | 높음 | builder | 완료 |
| task-018 | 공통 레이아웃(앱 셸) | W1 | 001 | 낮음 | builder | 완료 |
| task-005 | 판정 엔진 | W2 | 003 | 보통 | builder + tester | 완료 |
| task-006 | YouTube 관측 · A-07 · 할당량 방어선 | W2 | 005 | 높음 | builder + tester | 완료 |
| task-007 | 워커 API W-01~W-04 · job 상태 | W2 | 006 | 높음 | builder + tester | 완료 |
| task-008 | 수집 작업 API A-05 | W2 | 007 | 높음 | builder + tester | 완료 |
| task-009 | 로컬 워커 (Playwright · vidIQ) | W2 | 007, vidIQ 약관 확인 | 높음 | builder | 보류(준비 중) |
| task-010 | 프로필 API A-03 | W2 | 003 | 높음 | builder + tester | 완료 |
| task-011 | 조회 API A-02 · A-04 · A-06 | W2 | 005, 010 | 높음 | builder + tester | 완료 |
| task-012 | AUTH-01 로그인 | W3 | 001, 002 | 높음 | builder | 완료 |
| task-013 | MON-01 소재수집 목록 | W3 | 006, 008, 010, 011, 012, 018 | 높음 | builder | 완료 |
| task-014 | MON-D1 프로필 조건 | W3 | 010, 012, 018 | 보통 | builder | 완료 |
| task-015 | MON-D2 관측 근거 | W3 | 011, 013, 018 | 높음 | builder | 완료 |
| task-016 | DASH-01 대시보드 | W3 | 011, 012, 018 | 보통 | builder | 완료 |
| task-017 | A-08 사용한 소재 | W3 | 011, 013 | 높음 | builder + tester | 완료 |
| task-019 | YouTube 검색 후보 수집 (vidIQ 대체) | W3 | 006, 008, 013 | 높음 | builder + tester | 완료 |
| task-020 | 제작 스키마 · RLS · Storage 버킷 | W4 | 002 | 높음 | builder + tester | 완료 |
| task-021 | 편집안 검증 모듈 | W4 | 003 | 보통 | builder + tester | 완료 |
| task-022 | 제작 작업 API A-09~A-13·A-17·A-18 | W4 | 020, 021 | 높음 | builder + tester | 완료 |
| task-023 | 렌더 요청·재시도 A-15·A-16 · 워커 API W-05~W-09 | W4 | 022 | 높음 | builder + tester | 완료 |
| task-024 | 로컬 제작 워커 prepare·render | W4 | 023 | 높음 | builder + tester | 완료 |
| task-025 | PROD-00·PROD-01 화면 + MON-01 제작 버튼 | W4 | 022 | 보통 | builder | 완료 |
| task-026 | PROD-02 편집안 화면 | W4 | 022, 025 | 보통 | builder | 완료 |
| task-027 | PROD-03 작업·검수 화면 | W4 | 023, 025 | 보통 | builder | 완료 |
| task-028 | P0 인수 테스트 CAT-01~07 | W4 | 024, 026, 027 | 보통 | tester | 완료 |
| task-029 | AI 초안 A-14 (Claude) | W5 | 028 | 높음 | builder + tester | 완료 |
| task-030 | TTS (edge-tts, 워커 전용) | W5 | 028 | 높음 | builder | 완료 |
| task-031 | URL 원본 (권리 확인 · yt-dlp · SSRF 방지) | W5 | 028 | 높음 | builder + tester | 완료 |
| task-032 | 댓글·출처 오버레이 레이어 | W5 | 028 | 보통 | builder | 완료 |
| task-033 | P1 인수 테스트 CAT-08 + 회귀 | W5 | 029, 030, 031, 032 | 보통 | tester | 완료 |
| task-034 | 예능형 편집안 검증 모듈 | W6 | 021, 028 | 보통 | builder + tester | 완료 |
| task-035 | 예능형 API 연결 (A-09·A-12·어댑터·W-05 task.format) | W6 | 034 | 높음 | builder + tester | 완료 |
| task-036 | 예능형 렌더러 (로컬 워커 · 글꼴 라이선스) | W6 | 035 | 높음 | builder + tester | 완료 |
| task-037 | PROD-01 형식 선택 + PROD-02 예능형 패널 | W6 | 035 | 보통 | builder | 완료 |
| task-038 | 예능형 P0 인수 테스트 VAR-01~05 | W6 | 036, 037 | 보통 | tester | 완료 |
| task-039 | 로컬 받아쓰기 transcribe (faster-whisper · A-19 · transcribe_state) | W7 | 038 | 높음 | builder + tester | 보류 |
| task-040 | 예능형 AI 초안 (A-14 형식 분기) | W7 | 029(039 보류 — 수동 대사로 대체) | 높음 | builder + tester | 완료 |
| task-041 | 예능형 P1 인수 테스트 VAR-06·07 + 회귀 | W7 | 040 | 보통 | tester | 완료 |
| task-042 | 스키마: 유형·분야·brief·제휴·권리·리비전 언어 | W8 | 038 | 높음 | builder + tester | 완료 |
| task-043 | 쇼핑 편집안 검증 | W8 | 042 | 보통 | builder + tester | 완료 |
| task-044 | 쇼핑 API | W8 | 043 | 높음 | builder + tester | 완료 |
| task-045 | 쇼핑 렌더러 (로컬 워커) | W8 | 044, 030 | 높음 | builder + tester | 완료 |
| task-046 | 화면: 유형 선택·PROD-01S·PROD-02S·게시 문구 | W8 | 044 | 보통 | builder | 완료 |
| task-047 | 쇼핑 P0 인수 SHOP-01~06 | W8 | 045, 046 | 보통 | tester | 완료 |
| task-048 | AI 대본 3안 + 게시 문구 초안 | W9 | 047, 029 | 높음 | builder + tester | 완료 |
| task-049 | 일본어판 파생·번역 A-20 | W10 | 047 | 높음 | builder + tester | 완료 |
| task-050 | 일본어 TTS·렌더 | W10 | 049, 030 | 높음 | builder + tester | 완료 |
| task-051 | 예능형 일본어 더빙 | W10 | 050, 038 | 높음 | builder + tester | 완료 |
| task-052 | 언어 탭 화면 | W10 | 049 | 보통 | builder | 완료 |
| task-053 | 일본어판·쇼핑 P1 인수 + 회귀 | W10 | 048, 051, 052, 054 | 보통 | tester | 완료 |
| task-054 | AI 영상 생성 연동 (플랫폼 어댑터 · 비용 상한) | W9 | 047, Q16 | 높음 | builder + tester | 완료 |
| task-055 | W4·W5 인수 결함 보완(화면 안내·TTS 선택·오버레이) | W5 후속 | 033, 037 | 보통 | builder | 완료 |
| task-056 | PROD-02S AI 대본 3안 선택 UI·brief 외부 전송 고지 | W9 | 048 | 보통 | builder | 완료 |
| task-057 | PROD-02S 컷별 AI 생성 견적·확인·검수 체크 UI | W9 | 054 | 보통 | builder | 완료 |
| task-058 | 쇼핑 녹음 상한 ko·ja 공용 8개(task-053 결함) | W10 후속 | 049 | 높음 | builder | 완료 |

상태: 대기 / 진행 / 완료 / 보류

개발 단계(M0~M5)·병렬 묶음·단계별 데모: `docs/06_AGENT_PLAN.md`

수익·검증 1줄 요약: 내부 도구라 수익 없음(제작 시간 절감 가치), 가장 싼 검증은 운영자가 MVP를 직접 써서 제작 가능 판정 비율·제작 전환을 재는 것(`docs/01_PRD.md#5`), 정부지원사업 연결은 `미확인`.

## 발견한 문제 (범위 밖 — 나중 작업 후보)
| 날짜 | 위치 | 내용 | 제안 |
|---|---|---|---|
| 2026-11-16 | 배포(운영 Supabase·프록시) | 로컬 config에만 반영한 인증 설정: recovery 메일 템플릿, secure_password_change, 비밀번호 최소 10자, 가입 차단. 프록시의 X-Forwarded-For 덮어쓰기와 Host 전달, 접근 로그의 쿼리 문자열(token_hash) 마스킹 | 08 배포 단계 체크리스트에 포함 |
| 2026-11-16 | AUTH-01 `/auth/confirm` | 로그인 CSRF 여지: 타인 재설정 링크의 버튼을 누르면 세션이 바뀜(내부 도구라 낮음) | 이미 로그인 상태면 확인 화면에 경고 표시 검토 |
| 2026-11-16 | 기록 검증(task-006) | 삭제·비공개 영상은 매번 대상 상한(200) 자리를 차지할 수 있음 | 연속 실패 n회 후보 제외 규칙(후보 수가 커질 때) |
| 2026-11-16 | A-04 categories(task-011) | PostgREST max_rows 1000까지만 받아 중복 제거 → 후보 1000건 초과 시 일부 카테고리 누락 | 후보 수가 커지면 distinct 뷰 또는 RPC |
| 2026-11-16 | A-04 q 검색 | ilike는 `*`를 와일드카드로 바꿔 `*`를 `_`로 대체 → 약간 넓게 일치 | 정확 일치가 필요하면 imatch(정규식) 전환 |
| 2026-11-17 | 배포(API 서버) | 워커 라우트 본문 1MB 제한은 앱 수준. 서버 수신 타임아웃·동시 연결 제한은 없음 | 08 배포 체크리스트(uvicorn/프록시 timeout·limit-concurrency) |
| 2026-11-17 | DASH-01 빈 상태 | 첫 사용 판정이 근사(기간 수집+제작 가능+근거 대기=0) → 제외·사용됨 후보만 있으면 첫 사용으로 보임 | A-02에 전체 후보 수 필드 추가 |
| 2026-11-17 | ERD 생성(sql2erd) | ALTER TABLE ADD COLUMN을 읽지 못해 `jobs.lookup_count`가 erd.mmd에 빠짐 | 도구 보강 또는 ERD에 주석 한 줄 |
| 2026-11-17 | jobs.error 제약 | 허용 코드가 check로 고정 → 008 등에서 새 오류 코드를 쓰면 새 마이그레이션 필요 | 코드 추가 시 함께 마이그레이션 |
| 2026-11-17 | 웹 테스트 도구 | jsdom·testing-library 없음 → 클릭 배선(MonitorWorkbench 통합)·포커스 이동을 자동 테스트 못 함 | 테스트 의존성 추가 작업(새 의존성 → secscan) |
| 2026-11-17 | 웹 CSP | Content-Security-Policy(img-src 등) 미설정, 썸네일 host 검사가 유일한 방어선 | 배포 전 CSP 헤더 작업 |
| 2026-11-18 | 검색 할당량(task-019) | 검색 일 상한 2,000 unit은 서버 공용(워크스페이스별 아님). 단일 워크스페이스라 수용 | 다중 워크스페이스 도입 시 워크스페이스별 상한 |
| 2026-11-18 | 검색 후보 category(task-019) | 검색 결과에 자체 분류가 없어 찾은 프로필의 category·market을 그대로 기록 | 실측 분류가 필요하면 snippet.categoryId 매핑 표 |
| 2026-11-18 | 수집 POST 키 미설정(task-019) | YOUTUBE_API_KEY가 없으면 API 502 → 화면은 일반 "요청을 처리하지 못했습니다" | 배포 체크리스트에 키 설정 확인, 필요 시 전용 문구 |
| 2026-11-16 | 앱 셸 | 로그아웃 버튼(SignOutButton)이 셸에 아직 없음 | DASH-01(task-016) 또는 셸 보강 때 상단 바에 배치 |
| 2026-11-19 | 배포(원격 Supabase) | 원본 업로드 한도 500MB(Q8 확정) → 원격은 Pro 플랜 필요, 프로젝트 Storage 업로드 상한 500MB로 설정. 적용 후 `production` 버킷 public=false 확인(기존 버킷이 있으면 on conflict로 유지됨) | 08 배포 체크리스트 |
| 2026-11-19 | PROD-03·워커 실패 보고(task-028 CAT-04) | 훅 음성이 길 때 필요한 초 안내가 화면·W-09 보고에 없음(`it.fails` 재현: cat-acceptance.test.tsx) | W-09 실패에 필요 초(detail) 추가 + REASON_TEXT 안내(보통) |
| 2026-11-19 | PROD-03 검수(task-028 CAT-06) | 글자 잘림·검은 틈·피사체 잘림 확인 안내 없음, docs/03에도 항목 없음. 가로 원본 중앙 크롭은 자동 탐지 없음 | docs/03 PROD-03에 검수 3항목 추가 + 화면 체크리스트(낮음) |

## 교훈 (다음 작업에 그대로 적용할 것만, 20줄 이내 유지)
- 테스트의 가짜 JWT·키는 문자열 리터럴로 두지 말고 런타임에 조립한다(gitleaks pre-commit 차단).
- 외부 인증 방식(JWT alg 등)은 계획 전에 실제 엔드포인트로 확인한다(모킹 테스트만으로는 거짓 통과). 
| 2026-11-20 | A-12 저장(ko·ja, task-049) | 낙관적 잠금이 rev_no만 비교 → 미승인본을 같은 rev_no로 두 사람이 동시에 저장하면 앞선 편집 유실(ko 000016·ja 000027 동일 계약) | base_updated_at(또는 저장 버전) 추가 — API·웹 계약 변경(보통) |
| 2026-11-20 | 배포(W-06 훅 음성, task-050 K4) | W-06이 리비전 spec의 hook.audio_asset_id만 줌 → 참조 없이 승인된 기존 category ko 리비전은 audio_missing 실패 가능(운영 데이터 없음) | 배포 전 해당 리비전 탐지 후 재승인 — 08 배포 체크리스트 |
| 2026-11-20 | A-09 상세 lang(task-052) | latest_run·assets에 lang이 없어 PROD-03 ja 탭이 ja 진행률·MP4 재생·언어별 리포트를 구분 못 함. ja 녹음 대체(JA-04) 업로드 UI도 없음 | A-09에 언어별 latest_run·자산 lang 노출 + ja 녹음 업로드 UI(보통) |
