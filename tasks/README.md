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
| task-009 | 로컬 워커 (Playwright · vidIQ) | W2 | 007, vidIQ 약관 확인 | 높음 | builder | 보류 |
| task-010 | 프로필 API A-03 | W2 | 003 | 높음 | builder + tester | 완료 |
| task-011 | 조회 API A-02 · A-04 · A-06 | W2 | 005, 010 | 높음 | builder + tester | 완료 |
| task-012 | AUTH-01 로그인 | W3 | 001, 002 | 높음 | builder | 완료 |
| task-013 | MON-01 소재수집 목록 | W3 | 006, 008, 010, 011, 012, 018 | 높음 | builder | 완료 |
| task-014 | MON-D1 프로필 조건 | W3 | 010, 012, 018 | 보통 | builder | 완료 |
| task-015 | MON-D2 관측 근거 | W3 | 011, 013, 018 | 높음 | builder | 대기 |
| task-016 | DASH-01 대시보드 | W3 | 011, 012, 018 | 보통 | builder | 완료 |
| task-017 | A-08 사용한 소재 | W3 | 011, 013 | 높음 | builder + tester | 대기 |

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
| 2026-11-16 | 앱 셸 | 로그아웃 버튼(SignOutButton)이 셸에 아직 없음 | DASH-01(task-016) 또는 셸 보강 때 상단 바에 배치 |

## 교훈 (다음 작업에 그대로 적용할 것만, 20줄 이내 유지)
- 테스트의 가짜 JWT·키는 문자열 리터럴로 두지 말고 런타임에 조립한다(gitleaks pre-commit 차단).
- 외부 인증 방식(JWT alg 등)은 계획 전에 실제 엔드포인트로 확인한다(모킹 테스트만으로는 거짓 통과). 
