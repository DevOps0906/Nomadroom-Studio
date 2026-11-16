# 02 아키텍처 — Nomadroom Studio

> 그림: [`diagrams/architecture.mmd`](diagrams/architecture.mmd) — 코드가 생기면 `deps2mmd`로 다시 생성
> 범위: MVP(로그인 · 대시보드 · 소재수집(정체)). 나머지 메뉴는 운영 사이트 외부 링크(`01_PRD.md`). 스택 정본: `AGENTS.md#2`.

## 1. 구성 요소
| 요소 | 책임 | 기술 | 소유 경로 | 비밀 보유 |
|---|---|---|---|---|
| 웹 | 로그인·대시보드·소재수집(정체) 화면, 서버 측에서 API 중계 | Next.js 16 · React 19 · Tailwind v4 | `apps/web` | 없음 (Supabase anon 키·URL만, 공개 가능) |
| DB·인증 | 사용자·워크스페이스·프로필 조건·후보·관측값·판정·작업(job) 저장, RLS | Supabase Postgres · Auth | `supabase/` | service_role은 Supabase 안·API에만 |
| API | 판정·조건 검증, YouTube Data API v3 관측, 작업 등록, 워커 결과 수신 | FastAPI · Pydantic v2 | `apps/api` | YouTube 키 · service_role (클라우드 호스트 환경변수) |
| 수집 워커 | 운영자 PC에서 Chrome(Playwright)·vidIQ로 후보 수집, Chrome 준비 상태 보고 | Python · Playwright (`apps/api` 내 worker 모듈) | `apps/api/worker` | 워커 토큰만 (YouTube 키·service_role 없음). Chrome·vidIQ 로그인 프로필은 PC 로컬에만 |
| YouTube Data API v3 | 조회수·라이선스(C.C)·채널 정보 | 외부 | — | API 키는 API 요소만 |
| 운영 사이트 | 그 외 메뉴·"새 영상 만들기" | 외부(기존) | — | 해당 없음 (링크 이동만) |

결정(2026-11-16): API는 클라우드에 둔다(ADR-0001). 구체 호스팅처는 08 배포 단계에서 고른다.

## 2. 경계 규칙 (누가 누구를 부르나)
| 호출자 | 대상 | 방법 | 금지 |
|---|---|---|---|
| 브라우저 | Supabase | 직접 호출 안 함. 로그인·읽기는 웹 서버(Server Action·Server Component)가 anon 키 + 사용자 세션(httpOnly 쿠키)으로 대신, 전 테이블 RLS (사용자 결정 2026-11-16) | 브라우저 Supabase 클라이언트·Realtime, 쓰기 |
| 브라우저 | API | 직접 호출 안 함. 웹 서버(Route Handler)가 중계 | 브라우저에서 API 주소·키 노출 |
| 웹 서버 | API | HTTPS, `Authorization: Bearer <Supabase 사용자 JWT>` 전달. API가 JWT 서명·만료·워크스페이스 소속 검증 | JWT 없는 호출, 웹이 API 대신 YouTube·service_role 사용 |
| API | Supabase | service_role로 읽기·쓰기 (서버 환경변수) | 사용자 JWT 검증 없이 사용자 데이터 처리 |
| API | YouTube Data API | 서버에서 키로 호출, 일일 할당량 예산 준수 (`adr/0002-*.md`) | `search.list` 사용(100 unit), 키를 응답·로그에 포함 |
| 워커 | API | 아웃바운드 HTTPS만, 워커 토큰으로 작업 요청 폴링·결과 전송. 로컬 포트 개방 없음 | 워커가 DB 직접 접속, 외부에서 워커 호출 |
| 워커 | Chrome·vidIQ | 로컬 Playwright, 운영자 로그인 프로필 | vidIQ 계정 정보를 API·DB로 전송 |
| 웹 | 운영 사이트 | 외부 링크(새 탭) | 토큰·세션을 링크에 실어 보내기 |

공통: 금액 없음(결제 제외, D3). LLM 호출 없음(D4). 시간은 UTC 저장, 한국 시간 표시. 보안 레벨 정본은 `01_PRD.md#8`.

## 3. 주요 흐름
### 3-1. 후보 가져오기
| 단계 | 주체 | 동작 |
|---|---|---|
| 1 | 웹 | "후보 가져오기" 클릭 → 선택된 프로필(최대 3) 조건과 함께 API 호출 |
| 2 | API | 입력 검증 후 `collect` 작업(job)을 DB에 `대기`로 등록, job id 반환 |
| 3 | 워커 | 폴링으로 작업 수령 → Chrome 준비 확인(3-3) |
| 4 | 워커 | vidIQ로 프로필 조건별 후보(영상 id·제목·썸네일 등) 수집 |
| 5 | 워커 | 후보 묶음(실행당 ≤200, `01_PRD.md#7` Q3)을 API에 전송 → API가 중복 제거 후 저장 |
| 6 | API | 신규 후보를 YouTube API로 1차 관측(조회수·라이선스·채널) 저장 → 판정은 근거 대기 |
| 7 | 웹 | job 상태를 읽어 진행·완료 표시, 후보 목록 갱신 |

> 그림: [`diagrams/flow-1.mmd`](diagrams/flow-1.mmd)

### 3-2. 기록 검증 실행
| 단계 | 주체 | 동작 |
|---|---|---|
| 1 | 웹 | "기록 검증 실행" 클릭 → API 호출 (워커 불필요) |
| 2 | API | 마지막 관측 후 24시간 미만인 후보는 건너뜀(간격 24시간~7일) |
| 3 | API | 대상 후보를 50개 단위로 YouTube API 조회, 두 시점 관측값 저장 (할당량 예산 `adr/0002-*.md`) |
| 4 | API | 판정 규칙(`01_PRD.md#9`)으로 프로필별 판정 후 대표 판정 계산 |
| 5 | API | 할당량 소진·API 오류 시 남은 후보는 이전 판정 유지, 실패 사유 기록 |
| 6 | 웹 | 상태 지표 5개·후보 카드 갱신 |

> 그림: [`diagrams/flow-2.mmd`](diagrams/flow-2.mmd)

### 3-3. Chrome 준비 실패 → 재시도 / 중지
| 단계 | 주체 | 동작 |
|---|---|---|
| 1 | 워커 | 프로필별 Chrome 준비 점검(준비 완료 / 창 확대 필요 / 로그인 필요 등), 결과를 API로 전송 |
| 2 | 웹 | 프로필별 상태 표시. 실패 항목은 "해당 후보부터 재시도"·"수집 중지" 노출 |
| 3a | 웹→API→워커 | 재시도 선택: 실패한 프로필 지점부터 이어서 수집(이미 수집한 후보 유지) |
| 3b | 웹→API→워커 | 중지 선택: job을 `중지`로 변경, 워커는 현재 단계 정리 후 종료. 수집된 후보는 보존 |
| 4 | 워커 | 하트비트 3분 미수신 = 오프라인(가정) → API가 job을 `실패`로 표시 |

수치 정본(가정): 재시도 상한 3회(초과 시 재시도 불가) · 하트비트 3분 미수신 = 워커 오프라인. 04·05는 이 절을 링크한다.

> 그림: [`diagrams/flow-3.mmd`](diagrams/flow-3.mmd)

## 다이어그램 요청 (diagrammer)
- `diagrams/architecture.mmd` 갱신: 구성도(웹 · Supabase · API · 수집 워커(운영자 PC) · YouTube API · vidIQ/Chrome · 운영 사이트), 비밀 보유 요소 표시, 신뢰 경계(클라우드/운영자 PC) 구분.
- `diagrams/flow-1.mmd`: 시퀀스 — 후보 가져오기(3-1).
- `diagrams/flow-2.mmd`: 시퀀스 — 기록 검증 실행(3-2).
- `diagrams/flow-3.mmd`: 상태도 — job(대기·진행·재시도·중지·실패·완료)과 Chrome 준비 실패 분기(3-3).
